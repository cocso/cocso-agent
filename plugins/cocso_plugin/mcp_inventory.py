"""cocso_plugin.mcp_inventory — MCP tool 인벤토리 조회 도구.

COCO가 응답 전에 "지금 어떤 MCP tool이 실제로 등록돼 있는지" 자기
스스로 점검할 수 있게 해주는 helper. 이름 추측·환각 방지.

노출 도구 1개:
  cocso_mcp_inventory(server=None)
    server="cocso-client" → cocso-client MCP 의 tool 만
    server=None          → 모든 MCP server의 tool

응답: 서버별로 grouping된 tool 목록 + 각 tool의 description, 필수 인자.

이 도구 자체는 MCP 서버 호출이 아니라 cocso 의 tool registry를
inspect 하므로 외부 통신 없이 즉시 응답.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str, **extra) -> str:
    return json.dumps({"error": msg, **extra}, ensure_ascii=False)


def _ok(**fields) -> str:
    return json.dumps({"ok": True, **fields}, ensure_ascii=False, default=str)


def _split_mcp_name(name: str) -> Optional[tuple]:
    """``mcp__<server>__<tool>`` → (server, tool). None if not MCP-shaped."""
    if not isinstance(name, str) or not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__"):]
    if "__" not in rest:
        return None
    server, tool = rest.split("__", 1)
    return server, tool


def _summarize_params(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Pull required + optional parameter names + types from JSON Schema."""
    if not isinstance(schema, dict):
        return {"required": [], "optional": []}
    params = schema.get("parameters") or schema.get("input_schema") or schema
    if not isinstance(params, dict):
        return {"required": [], "optional": []}
    props = params.get("properties") or {}
    required = list(params.get("required") or [])
    out_required = []
    out_optional = []
    for name, spec in props.items():
        typ = (spec or {}).get("type", "any") if isinstance(spec, dict) else "any"
        desc = (spec or {}).get("description", "") if isinstance(spec, dict) else ""
        entry = {"name": name, "type": typ}
        if desc:
            entry["description"] = (desc[:120] + "…") if len(desc) > 120 else desc
        if name in required:
            out_required.append(entry)
        else:
            out_optional.append(entry)
    return {"required": out_required, "optional": out_optional}


def _get_short_description(schema: Optional[Dict[str, Any]], fallback: str = "") -> str:
    if not isinstance(schema, dict):
        return fallback
    desc = schema.get("description", "") or fallback
    if not isinstance(desc, str):
        return fallback
    # Trim — first sentence or 200 chars
    desc = desc.strip()
    if len(desc) > 250:
        desc = desc[:250] + "…"
    return desc


# ---------------------------------------------------------------------------
# Tool: cocso_mcp_inventory
# ---------------------------------------------------------------------------

def cocso_mcp_inventory(args: Dict[str, Any], **_kw) -> str:
    """List MCP tools currently registered, grouped by server."""
    server_filter = (args.get("server") or "").strip() or None
    include_params = bool(args.get("include_params", True))

    try:
        from tools.registry import registry
    except Exception as exc:
        return _err(f"tool registry unavailable: {exc}")

    try:
        all_names = registry.get_all_tool_names()
    except Exception as exc:
        return _err(f"failed to enumerate tools: {exc}")

    # Group MCP-shaped tools by server.
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for name in all_names:
        parts = _split_mcp_name(name)
        if parts is None:
            continue
        server, tool = parts
        if server_filter and server != server_filter:
            continue
        entry = registry.get_entry(name)
        schema = getattr(entry, "schema", None) if entry else None
        info: Dict[str, Any] = {
            "name": name,
            "tool": tool,
            "description": _get_short_description(schema),
        }
        if include_params:
            info["params"] = _summarize_params(schema)
        grouped.setdefault(server, []).append(info)

    # Sort tools within each server alphabetically for stable output.
    for server in grouped:
        grouped[server].sort(key=lambda x: x["tool"])

    servers = sorted(grouped.keys())
    if not servers:
        msg = (
            f"no MCP tools registered for server '{server_filter}'."
            if server_filter
            else "no MCP tools registered."
        )
        # 진단 힌트
        return _ok(
            servers=[],
            total_tools=0,
            note=(
                f"{msg} 가능 원인: (1) mcp Python SDK 미설치 — "
                "`pip install 'mcp>=1.2.0,<2'` (2) MCP 서버 URL/KEY 미설정 — "
                "`cocso doctor` (3) 서버 연결 실패 — `cocso doctor` 의 ◆ "
                "COCSO MCP 섹션 확인."
            ),
        )

    return _ok(
        servers=servers,
        server_count=len(servers),
        total_tools=sum(len(v) for v in grouped.values()),
        tools=grouped,
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

INVENTORY_SCHEMA = {
    "name": "cocso_mcp_inventory",
    "description": (
        "현재 cocso agent에 등록된 MCP tool 목록을 서버별로 그룹화해 "
        "반환. 각 tool의 이름·짧은 설명·필수/선택 인자 포함. "
        "MCP 관련 사용자 요청을 받았을 때 **추측하기 전에 먼저 호출**해 "
        "실제 사용 가능한 tool을 확인하고 그 중에서 골라 호출. 이름 환각·"
        "있지도 않은 tool 호출 시도 방지에 필수. 외부 통신 없이 로컬 "
        "registry inspect 만 하므로 비용·지연 0."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": (
                    "특정 MCP 서버만 보려면 이름 (예: 'cocso-client', "
                    "'cocso-service'). 비우면 전체."
                ),
            },
            "include_params": {
                "type": "boolean",
                "description": "각 tool의 인자 명세 포함 여부. default true.",
            },
        },
    },
}


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_tool(
        name=INVENTORY_SCHEMA["name"],
        toolset="cocso-mcp",
        schema=INVENTORY_SCHEMA,
        handler=cocso_mcp_inventory,
    )
