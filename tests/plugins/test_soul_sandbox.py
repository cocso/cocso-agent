"""Tests for the soul_sandbox plugin.

Pins:
- pre_tool_call hook blocks writes against ${COCSO_HOME}/SOUL.md
- glob ``**/SOUL.md`` blocks the file anywhere on disk
- Terminal commands matching protected name + risky pattern are blocked
- Env-leak patterns (``echo $X``) blocked when X is in protected_env_vars
- ${COCSO_HOME} placeholder resolves to the actual cocso home (Docker /
  profile mode aware)
- audit_only mode logs but does not block
- yaml hot-reload picks up edits via mtime
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_PATH = PROJECT_ROOT / "plugins" / "soul_sandbox" / "__init__.py"


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Load a fresh soul_sandbox module bound to a tempdir COCSO_HOME."""
    home = tmp_path / "cocso_home"
    home.mkdir()
    monkeypatch.setenv("COCSO_HOME", str(home))

    spec = importlib.util.spec_from_file_location(
        f"_ssbox_test_{tmp_path.name}", str(PLUGIN_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Reset cache so each test starts fresh
    mod._CACHE["mtime"] = 0
    mod._CACHE["cfg"] = None
    mod._CACHE["expanded_paths"] = set()
    mod._CACHE["config_path"] = None
    return mod, home


class TestPathProtection:
    def test_blocks_soul_md_in_cocso_home(self, sandbox):
        mod, home = sandbox
        result = mod.block_protected("write_file", {"path": str(home / "SOUL.md")})
        assert result is not None
        assert result["action"] == "block"
        assert "SOUL.md" in result["message"]

    def test_blocks_soul_md_anywhere_via_glob(self, sandbox):
        mod, _ = sandbox
        result = mod.block_protected("edit_file", {"file_path": "/random/proj/SOUL.md"})
        assert result is not None
        assert result["action"] == "block"

    def test_blocks_dotenv_in_cocso_home(self, sandbox):
        mod, home = sandbox
        result = mod.block_protected("write_file", {"path": str(home / ".env")})
        assert result is not None

    def test_allows_unprotected_path(self, sandbox):
        mod, _ = sandbox
        assert mod.block_protected("write_file", {"path": "/tmp/foo.txt"}) is None

    def test_recognizes_multiple_path_keys(self, sandbox):
        mod, home = sandbox
        # Each of these arg keys should be checked
        for key in ("path", "file_path", "filename", "target", "dest"):
            assert mod.block_protected(
                "write_file", {key: str(home / "SOUL.md")}
            ) is not None, f"key {key!r} not checked"


class TestTerminalProtection:
    def test_blocks_rm_on_protected(self, sandbox):
        mod, home = sandbox
        result = mod.block_protected(
            "terminal", {"command": f"rm {home}/SOUL.md"}
        )
        assert result is not None
        assert "SOUL.md" in result["message"]

    def test_blocks_redirect_to_protected(self, sandbox):
        mod, home = sandbox
        result = mod.block_protected(
            "terminal", {"command": f"echo X > {home}/SOUL.md"}
        )
        assert result is not None

    def test_allows_safe_terminal(self, sandbox):
        mod, _ = sandbox
        for cmd in ("ls -la", "git status", "python --version"):
            assert mod.block_protected("terminal", {"command": cmd}) is None

    def test_blocks_env_leak(self, sandbox):
        mod, _ = sandbox
        result = mod.block_protected(
            "terminal", {"command": "echo $COCSO_CLIENT_KEY"}
        )
        assert result is not None
        assert "COCSO_CLIENT_KEY" in result["message"]

    def test_blocks_glob_env_leak(self, sandbox):
        mod, _ = sandbox
        result = mod.block_protected(
            "terminal", {"command": "echo $OPENAI_API_KEY"}
        )
        assert result is not None
        # Pattern *_API_KEY matched OPENAI_API_KEY
        assert "API_KEY" in result["message"]


class TestCocsoHomeResolution:
    def test_placeholder_resolves_to_actual_home(self, sandbox):
        mod, home = sandbox
        cfg, paths = mod._load_config()
        assert any(str(home) in p for p in paths), (
            f"${{COCSO_HOME}} not resolved. paths={paths}"
        )

    def test_protection_works_in_docker_style_home(self, monkeypatch, tmp_path):
        # Simulate a Docker deployment where COCSO_HOME is /app/data
        docker_home = tmp_path / "app" / "data"
        docker_home.mkdir(parents=True)
        monkeypatch.setenv("COCSO_HOME", str(docker_home))

        spec = importlib.util.spec_from_file_location(
            f"_ssbox_docker_{tmp_path.name}", str(PLUGIN_PATH)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._CACHE["mtime"] = 0
        mod._CACHE["cfg"] = None
        mod._CACHE["expanded_paths"] = set()
        mod._CACHE["config_path"] = None

        result = mod.block_protected(
            "write_file", {"path": str(docker_home / "SOUL.md")}
        )
        assert result is not None, "Docker-style COCSO_HOME SOUL.md not protected"


class TestAuditOnlyMode:
    def test_audit_only_does_not_block(self, sandbox, monkeypatch, caplog):
        mod, home = sandbox
        # Mutate cached config to enable audit mode
        cfg, _ = mod._load_config()
        cfg["audit_only"] = True
        mod._CACHE["cfg"] = cfg

        with caplog.at_level("WARNING"):
            result = mod.block_protected(
                "write_file", {"path": str(home / "SOUL.md")}
            )
        assert result is None, "audit_only mode must not produce a block directive"
        assert any("AUDIT" in rec.message for rec in caplog.records)


class TestRegister:
    def test_register_attaches_hook(self, sandbox):
        mod, _ = sandbox

        class FakeCtx:
            def __init__(self):
                self.hooks = []
                self.commands = []

            def register_hook(self, name, fn):
                self.hooks.append((name, fn))

            def register_command(self, name, handler, description=""):
                self.commands.append((name, handler, description))

        ctx = FakeCtx()
        mod.register(ctx)
        assert len(ctx.hooks) == 1
        assert ctx.hooks[0][0] == "pre_tool_call"
        assert any(c[0] == "sandbox" for c in ctx.commands)
