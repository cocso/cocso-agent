"""Tests for the cocso_audit plugin.

Pins:
- Each event type writes one JSONL line to ``${COCSO_HOME}/audit/<sid>.jsonl``
- Tool args matching redact patterns are blanked
- Long text fields are truncated with a marker
- Per-session sliding-window rate limit blocks excess tool calls
- session_end clears the rate-limit bucket
- /audit slash command emits stats / list / tail output
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_PATH = PROJECT_ROOT / "plugins" / "cocso_plugin" / "audit.py"


@pytest.fixture
def audit(monkeypatch, tmp_path):
    """Fresh cocso_audit module bound to a tempdir COCSO_HOME."""
    home = tmp_path / "cocso_home"
    home.mkdir()
    monkeypatch.setenv("COCSO_HOME", str(home))

    spec = importlib.util.spec_from_file_location(
        f"_audit_test_{tmp_path.name}", str(PLUGIN_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._CACHE.update({"mtime": 0, "cfg": None, "path": None, "log_dir": None})
    mod._RATE_BUCKETS.clear()
    return mod, home


def _read_records(home: Path, session_id: str) -> list:
    path = home / "audit" / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestEventLogging:
    def test_session_start_recorded(self, audit):
        mod, home = audit
        mod.on_session_start(session_id="s1", model="opus-4-7", platform="cli")
        records = _read_records(home, "s1")
        assert len(records) == 1
        assert records[0]["event"] == "session_start"
        assert records[0]["model"] == "opus-4-7"
        assert records[0]["platform"] == "cli"

    def test_user_turn_recorded(self, audit):
        mod, home = audit
        mod.on_user_turn(
            session_id="s1", user_message="hello", model="opus-4-7", is_first_turn=True
        )
        records = _read_records(home, "s1")
        assert records[-1]["event"] == "user"
        assert records[-1]["text"] == "hello"
        assert records[-1]["first_turn"] is True

    def test_assistant_turn_recorded(self, audit):
        mod, home = audit
        mod.on_assistant_turn(
            session_id="s1",
            user_message="q",
            assistant_response="answer",
            model="opus-4-7",
        )
        records = _read_records(home, "s1")
        assert records[-1]["event"] == "assistant"
        assert records[-1]["text"] == "answer"

    def test_tool_post_recorded(self, audit):
        mod, home = audit
        mod.on_tool_post(
            tool_name="web_search",
            args={"q": "test"},
            result="result body",
            task_id="s1",
            duration_ms=42,
        )
        rec = _read_records(home, "s1")[-1]
        assert rec["event"] == "tool"
        assert rec["tool"] == "web_search"
        assert rec["duration_ms"] == 42
        assert rec["result_size"] == len("result body")

    def test_session_end_recorded(self, audit):
        mod, home = audit
        mod.on_session_end(
            session_id="s1", completed=True, interrupted=False, model="m", platform="cli"
        )
        rec = _read_records(home, "s1")[-1]
        assert rec["event"] == "session_end"
        assert rec["completed"] is True


class TestRedaction:
    def test_secret_args_redacted(self, audit):
        mod, home = audit
        mod.on_tool_post(
            tool_name="api_call",
            args={"endpoint": "/x", "api_key": "supersecret", "password": "p"},
            result="ok",
            task_id="s1",
            duration_ms=1,
        )
        rec = _read_records(home, "s1")[-1]
        assert rec["args"]["api_key"] == "[REDACTED]"
        assert rec["args"]["password"] == "[REDACTED]"
        assert rec["args"]["endpoint"] == "/x"


class TestTruncation:
    def test_long_text_truncated(self, audit):
        mod, home = audit
        long_text = "x" * 5000
        mod.on_user_turn(session_id="s1", user_message=long_text, model="m")
        rec = _read_records(home, "s1")[-1]
        # Default max_text_chars = 500
        assert len(rec["text"]) < 1000
        assert "[+" in rec["text"]


class TestRateLimit:
    def test_allows_under_cap(self, audit):
        mod, _ = audit
        cfg = mod._load_config()
        cap = cfg["rate_limit"]["max_tool_calls"]
        for _ in range(min(cap, 5)):
            assert mod.on_tool_pre(tool_name="t", task_id="s1", session_id="s1") is None

    def test_blocks_over_cap(self, audit):
        mod, _ = audit
        # Force cap=2 for the test
        cfg = mod._load_config()
        cfg["rate_limit"]["max_tool_calls"] = 2
        mod._CACHE["cfg"] = cfg
        mod._RATE_BUCKETS.clear()

        assert mod.on_tool_pre(tool_name="t", task_id="s1", session_id="s1") is None
        assert mod.on_tool_pre(tool_name="t", task_id="s1", session_id="s1") is None
        block = mod.on_tool_pre(tool_name="t", task_id="s1", session_id="s1")
        assert block is not None
        assert block["action"] == "block"
        assert "한도 초과" in block["message"]

    def test_disabled_when_cap_zero(self, audit):
        mod, _ = audit
        cfg = mod._load_config()
        cfg["rate_limit"]["max_tool_calls"] = 0
        mod._CACHE["cfg"] = cfg
        mod._RATE_BUCKETS.clear()
        for _ in range(100):
            assert mod.on_tool_pre(tool_name="t", task_id="s1", session_id="s1") is None

    def test_session_end_clears_bucket(self, audit):
        mod, _ = audit
        cfg = mod._load_config()
        cfg["rate_limit"]["max_tool_calls"] = 5
        mod._CACHE["cfg"] = cfg

        for _ in range(3):
            mod.on_tool_pre(tool_name="t", task_id="s1", session_id="s1")
        assert "s1" in mod._RATE_BUCKETS

        mod.on_session_end(session_id="s1", completed=True)
        assert "s1" not in mod._RATE_BUCKETS

    def test_per_session_isolation(self, audit):
        mod, _ = audit
        cfg = mod._load_config()
        cfg["rate_limit"]["max_tool_calls"] = 1
        mod._CACHE["cfg"] = cfg
        mod._RATE_BUCKETS.clear()

        mod.on_tool_pre(tool_name="t", task_id="A", session_id="A")
        # session B should not be affected by A's quota
        assert mod.on_tool_pre(tool_name="t", task_id="B", session_id="B") is None
        # but A is now over cap
        assert mod.on_tool_pre(tool_name="t", task_id="A", session_id="A") is not None


class TestSlashCommand:
    def test_stats_runs(self, audit):
        mod, _ = audit
        # Seed something to log
        mod.on_session_start(session_id="s1", model="m", platform="cli")
        out = mod._slash_handler("stats")
        assert "audit log dir" in out
        assert "세션 수" in out

    def test_list_runs(self, audit):
        mod, _ = audit
        mod.on_session_start(session_id="s1", model="m", platform="cli")
        out = mod._slash_handler("list")
        assert "s1.jsonl" in out

    def test_tail_runs(self, audit):
        mod, _ = audit
        mod.on_session_start(session_id="s1", model="m", platform="cli")
        out = mod._slash_handler("tail 5")
        assert "session_start" in out


class TestRegister:
    def test_register_attaches_six_hooks(self, audit):
        mod, _ = audit

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
        names = {h[0] for h in ctx.hooks}
        assert names == {
            "on_session_start",
            "on_session_end",
            "pre_llm_call",
            "post_llm_call",
            "pre_tool_call",
            "post_tool_call",
        }
        assert any(c[0] == "audit" for c in ctx.commands)
