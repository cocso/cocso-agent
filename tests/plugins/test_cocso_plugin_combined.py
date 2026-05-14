"""Combined ``cocso_plugin`` registration test.

The 4 sub-modules (sandbox / audit / excel / settlement) used to ship as
separate plugins. They were merged into a single ``cocso_plugin`` so a
deployment only has to enable one name. This test pins:

- The single ``register(ctx)`` entry-point successfully registers all
  expected tools, hooks, and slash commands across every sub-module.
- A failure in one sub-module does not silently break sibling modules
  (the combined ``register`` swallows + logs).
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_INIT = PROJECT_ROOT / "plugins" / "cocso_plugin" / "__init__.py"

EXPECTED_HOOKS = {
    "pre_tool_call",     # sandbox + audit both register
    "post_tool_call",    # audit
    "pre_llm_call",      # audit
    "post_llm_call",     # audit
    "on_session_start",  # audit
    "on_session_end",    # audit
}

EXPECTED_TOOLS = {
    "excel_open",
    "excel_read_range",
    "excel_write_cell",
    "excel_write_range",
    "excel_add_sheet",
    "excel_save_as",
    "cocso_settlement_create",
    "cocso_settlement_template_info",
    "cocso_mcp_inventory",
}

EXPECTED_COMMANDS = {"sandbox", "audit"}


class FakeCtx:
    def __init__(self):
        self.hooks = []
        self.tools = []
        self.commands = []
        self.skills = []

    def register_hook(self, name, fn):
        self.hooks.append(name)

    def register_tool(self, **kw):
        self.tools.append(kw["name"])

    def register_command(self, name, handler, description=""):
        self.commands.append(name)

    def register_skill(self, name, path):
        self.skills.append((name, str(path)))


@pytest.fixture
def cocso_plugin(monkeypatch, tmp_path):
    """Load the combined cocso_plugin against an isolated COCSO_HOME."""
    monkeypatch.setenv("COCSO_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    # Load as a real package so relative ``from . import sandbox, audit, ...``
    # resolves. We seed the package + each submodule via spec_from_file_location.
    import sys

    pkg_name = f"_cp_combined_{tmp_path.name}"
    pkg_spec = importlib.util.spec_from_file_location(
        pkg_name,
        str(PLUGIN_INIT),
        submodule_search_locations=[str(PLUGIN_INIT.parent)],
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[pkg_name] = pkg
    pkg_spec.loader.exec_module(pkg)
    yield pkg
    # cleanup
    for k in list(sys.modules):
        if k.startswith(pkg_name):
            sys.modules.pop(k, None)


class TestCombinedRegistration:
    def test_register_attaches_all_tools(self, cocso_plugin):
        ctx = FakeCtx()
        cocso_plugin.register(ctx)
        assert set(ctx.tools) == EXPECTED_TOOLS, (
            f"missing/extra tools: {set(ctx.tools) ^ EXPECTED_TOOLS}"
        )

    def test_register_attaches_expected_hooks(self, cocso_plugin):
        ctx = FakeCtx()
        cocso_plugin.register(ctx)
        registered = set(ctx.hooks)
        assert EXPECTED_HOOKS.issubset(registered), (
            f"missing hooks: {EXPECTED_HOOKS - registered}"
        )
        # pre_tool_call should appear from BOTH sandbox + audit
        assert ctx.hooks.count("pre_tool_call") == 2, (
            f"pre_tool_call not double-registered (sandbox+audit): "
            f"{ctx.hooks.count('pre_tool_call')}"
        )

    def test_register_attaches_slash_commands(self, cocso_plugin):
        ctx = FakeCtx()
        cocso_plugin.register(ctx)
        assert set(ctx.commands) == EXPECTED_COMMANDS

    def test_register_attaches_bundled_skill(self, cocso_plugin):
        ctx = FakeCtx()
        cocso_plugin.register(ctx)
        names = [n for n, _ in ctx.skills]
        assert "cocso-settlement-excel" in names


class TestSubmoduleFailureIsolation:
    """One sub-module raising must not block the others."""

    def test_failing_sub_does_not_block_siblings(self, cocso_plugin, monkeypatch, caplog):
        # Make ``sandbox.register`` raise; ``audit/excel/settlement`` should
        # still register.
        def boom(_ctx):
            raise RuntimeError("simulated boom")

        monkeypatch.setattr(cocso_plugin.sandbox, "register", boom)

        ctx = FakeCtx()
        with caplog.at_level(logging.WARNING):
            cocso_plugin.register(ctx)

        # Tools (excel + settlement) still registered
        assert "excel_open" in ctx.tools
        assert "cocso_settlement_create" in ctx.tools
        # Audit hooks still attached
        assert "post_tool_call" in ctx.hooks
        # Sandbox slash command absent because sandbox crashed before reach
        assert "sandbox" not in ctx.commands
        # And the failure was logged
        assert any("sandbox" in r.message for r in caplog.records)
