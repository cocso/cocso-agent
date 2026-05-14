"""Tests for ``cocso_mcp_inventory`` — MCP tool 인벤토리 조회.

Pins:
- mcp__<server>__<tool> 형식만 잡고 일반 tool은 제외
- server 인자로 서버 필터링
- 인벤토리 비어있을 때 진단 hint 포함
- include_params=False 일 때 params 키 생략
- 핸들러는 절대 raise 안 함 (registry 에러도 JSON 에러로 반환)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_PATH = PROJECT_ROOT / "plugins" / "cocso_plugin" / "mcp_inventory.py"


@pytest.fixture
def inv():
    spec = importlib.util.spec_from_file_location("cmcpinv", str(PLUGIN_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _decode(s):
    return json.loads(s)


# ---------------------------------------------------------------------------
# Fake registry — let us inject controlled tool sets without real MCP setup.
# ---------------------------------------------------------------------------

class FakeEntry:
    def __init__(self, name, schema):
        self.name = name
        self.schema = schema


class FakeRegistry:
    def __init__(self, entries):
        self._entries = {e.name: e for e in entries}

    def get_all_tool_names(self):
        return sorted(self._entries.keys())

    def get_entry(self, name):
        return self._entries.get(name)


@pytest.fixture
def fake_registry(monkeypatch):
    """Patch tools.registry.registry with a controllable fake."""
    import sys
    fake_module = type(sys)("tools.registry")
    fake = FakeRegistry([
        FakeEntry("read_file", {"description": "local file read"}),  # not MCP
        FakeEntry("mcp__cocso-client__list_dealers", {
            "description": "List dealers belonging to the calling business.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max rows"},
                    "active_only": {"type": "boolean"},
                },
                "required": ["limit"],
            },
        }),
        FakeEntry("mcp__cocso-client__get_settlement", {
            "description": "Get settlement summary for a period.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "YYYY-MM"},
                },
                "required": ["period"],
            },
        }),
        FakeEntry("mcp__cocso-service__check_eligibility", {
            "description": "Check eligibility for a hospital.",
            "parameters": {
                "type": "object",
                "properties": {"biz_id": {"type": "string"}},
                "required": ["biz_id"],
            },
        }),
    ])
    fake_module.registry = fake
    sys.modules["tools.registry"] = fake_module
    yield fake
    sys.modules.pop("tools.registry", None)


class TestInventoryShape:
    def test_lists_all_servers(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({}))
        assert out["ok"] is True
        assert set(out["servers"]) == {"cocso-client", "cocso-service"}
        assert out["server_count"] == 2
        assert out["total_tools"] == 3

    def test_excludes_non_mcp_tools(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({}))
        for server, tools in out["tools"].items():
            for t in tools:
                assert t["name"].startswith("mcp__")
                assert "read_file" not in t["name"]

    def test_server_filter(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({"server": "cocso-client"}))
        assert out["servers"] == ["cocso-client"]
        assert out["total_tools"] == 2
        assert "cocso-service" not in out["tools"]

    def test_unknown_server_returns_empty_with_hint(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({"server": "no-such"}))
        assert out["servers"] == []
        assert out["total_tools"] == 0
        assert "no MCP tools" in out["note"]

    def test_alphabetical_tool_order(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({}))
        client_tools = [t["tool"] for t in out["tools"]["cocso-client"]]
        assert client_tools == sorted(client_tools)


class TestParamsSummary:
    def test_required_and_optional_split(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({}))
        list_dealers = next(
            t for t in out["tools"]["cocso-client"] if t["tool"] == "list_dealers"
        )
        params = list_dealers["params"]
        names_required = {p["name"] for p in params["required"]}
        names_optional = {p["name"] for p in params["optional"]}
        assert names_required == {"limit"}
        assert names_optional == {"active_only"}

    def test_descriptions_truncated(self, inv, fake_registry):
        # build a giant description
        import sys
        fake = sys.modules["tools.registry"].registry
        long_desc = "X" * 500
        fake._entries["mcp__cocso-client__big"] = FakeEntry(
            "mcp__cocso-client__big",
            {"description": long_desc,
             "parameters": {"type": "object", "properties": {}}},
        )
        out = _decode(inv.cocso_mcp_inventory({"server": "cocso-client"}))
        big = next(t for t in out["tools"]["cocso-client"] if t["tool"] == "big")
        assert len(big["description"]) <= 251  # 250 + …

    def test_include_params_false_drops_params(self, inv, fake_registry):
        out = _decode(inv.cocso_mcp_inventory({"include_params": False}))
        for tools in out["tools"].values():
            for t in tools:
                assert "params" not in t


class TestEmptyAndErrors:
    def test_empty_registry_diagnostic_hint(self, inv, monkeypatch):
        import sys
        fake_module = type(sys)("tools.registry")
        fake_module.registry = FakeRegistry([])
        sys.modules["tools.registry"] = fake_module
        try:
            out = _decode(inv.cocso_mcp_inventory({}))
            assert out["servers"] == []
            assert "mcp Python SDK" in out["note"]
            assert "cocso doctor" in out["note"]
        finally:
            sys.modules.pop("tools.registry", None)

    def test_registry_unavailable(self, inv, monkeypatch):
        import sys
        # simulate import failure
        sys.modules["tools.registry"] = None  # type: ignore[assignment]
        try:
            out = _decode(inv.cocso_mcp_inventory({}))
            assert "error" in out
        finally:
            sys.modules.pop("tools.registry", None)

    def test_handler_never_raises(self, inv, fake_registry):
        # bizarre args
        for bad in ({}, {"server": None}, {"include_params": "yes"},
                    {"server": ""}, {"include_params": 0}):
            assert isinstance(inv.cocso_mcp_inventory(bad), str)


class TestRegister:
    def test_register_attaches_tool(self, inv):
        class FakeCtx:
            def __init__(self):
                self.tools = []

            def register_tool(self, **kw):
                self.tools.append(kw["name"])

        ctx = FakeCtx()
        inv.register(ctx)
        assert ctx.tools == ["cocso_mcp_inventory"]
