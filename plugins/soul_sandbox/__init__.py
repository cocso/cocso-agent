"""soul_sandbox — block agent writes to protected files and credential leaks.

Mechanism: ``pre_tool_call`` hook returns ``{"action":"block",...}`` when the
LLM tries to use a write/terminal tool against a path or env var listed in
the user's ``~/.cocso/sandbox.yaml``.

Config file is auto-created on first invocation with sensible defaults.
Hot-reload: edit the YAML, next tool call picks it up (mtime-cached).
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# Lazy import — yaml is optional at module import time inside the agent.
try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Default config — written to ~/.cocso/sandbox.yaml on first run
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "protected_paths": [
        # ${COCSO_HOME} resolves to the active COCSO home (Docker /
        # profile mode aware). ~ also expands. Glob ** supported.
        "${COCSO_HOME}/SOUL.md",
        "**/SOUL.md",
        "${COCSO_HOME}/.env",
        "**/.env",
        "${COCSO_HOME}/config.yaml",
        "${COCSO_HOME}/sessions/**",
        "${COCSO_HOME}/credentials/**",
    ],
    "protected_env_vars": [
        "COCSO_CLIENT_KEY",
        "COCSO_SERVICE_KEY",
        "COCSO_CLIENT_MCP_URL",
        "COCSO_SERVICE_MCP_URL",
        "*_API_KEY",
        "*_TOKEN",
        "*_SECRET",
        "*_PASSWORD",
    ],
    "write_tools": [
        "write_file",
        "edit_file",
        "patch_file",
        "str_replace",
        "create_file",
    ],
    "terminal_block_patterns": [
        "rm ",
        "mv ",
        " > ",
        " >> ",
        "tee ",
        "sed -i",
        "truncate",
        "chmod ",
        "chown ",
        "shred ",
    ],
    "env_leak_triggers": [
        "echo $",
        "printenv ",
        "env ",
        "set | grep",
    ],
    # When True, log blocked attempts but allow them through. Useful while
    # tuning patterns. Set to False once happy.
    "audit_only": False,
}


# ---------------------------------------------------------------------------
# Config loading with mtime cache
# ---------------------------------------------------------------------------

_CACHE: Dict[str, Any] = {
    "mtime": 0.0,
    "cfg": None,
    "expanded_paths": set(),
    "config_path": None,
}


def _config_path() -> Path:
    """Return ``$COCSO_HOME/sandbox.yaml`` path, lazily resolved."""
    cached = _CACHE.get("config_path")
    if cached is not None:
        return cached
    try:
        from cocso_core.cocso_constants import get_cocso_home
        path = get_cocso_home() / "sandbox.yaml"
    except Exception:
        path = Path.home() / ".cocso" / "sandbox.yaml"
    _CACHE["config_path"] = path
    return path


def _seed_default(path: Path) -> None:
    """Create sandbox.yaml with defaults if missing."""
    if not yaml:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("soul_sandbox: seeded default config at %s", path)
    except Exception as exc:
        logger.warning("soul_sandbox: failed to seed config: %s", exc)


def _load_config() -> Tuple[Dict[str, Any], Set[str]]:
    """Read sandbox.yaml. Hot-reload on mtime change. Auto-seed on first run."""
    path = _config_path()

    if not path.exists():
        _seed_default(path)
        if not path.exists():
            # yaml unavailable or write failed — return defaults in-memory
            return DEFAULT_CONFIG, _expand_paths(DEFAULT_CONFIG.get("protected_paths", []))

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return DEFAULT_CONFIG, _expand_paths(DEFAULT_CONFIG.get("protected_paths", []))

    if mtime == _CACHE["mtime"] and _CACHE["cfg"] is not None:
        return _CACHE["cfg"], _CACHE["expanded_paths"]

    cfg: Dict[str, Any] = DEFAULT_CONFIG
    if yaml:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                # Merge with defaults so missing keys still work.
                cfg = {**DEFAULT_CONFIG, **loaded}
        except Exception as exc:
            logger.warning(
                "soul_sandbox: %s parse error, using defaults: %s", path, exc
            )

    expanded = _expand_paths(cfg.get("protected_paths", []))
    _CACHE.update({"mtime": mtime, "cfg": cfg, "expanded_paths": expanded})
    return cfg, expanded


def _cocso_home_str() -> str:
    """Return the active COCSO home dir as a string. Falls back to ~/.cocso."""
    try:
        from cocso_core.cocso_constants import get_cocso_home
        return str(get_cocso_home())
    except Exception:
        return os.path.expanduser("~/.cocso")


def _expand_paths(patterns: List[str]) -> Set[str]:
    """Resolve patterns: substitute ${COCSO_HOME}, expand ~, keep globs intact."""
    home = _cocso_home_str()
    out: Set[str] = set()
    for p in patterns or []:
        # Substitute placeholder first so the result still gets ~ / glob handling.
        resolved = p.replace("${COCSO_HOME}", home).replace("$COCSO_HOME", home)
        resolved = os.path.expanduser(resolved)
        out.add(resolved)
    return out


# ---------------------------------------------------------------------------
# Match logic
# ---------------------------------------------------------------------------

def _resolved(path: str) -> str:
    """Resolve to absolute, real (symlink-followed) path."""
    try:
        return os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    except Exception:
        return path


def _path_matches(target: str, patterns: Set[str]) -> bool:
    if not target:
        return False
    abs_t = _resolved(target)
    for pat in patterns:
        # 1. Exact match (after realpath on both sides where possible)
        try:
            if abs_t == _resolved(pat):
                return True
        except Exception:
            pass
        # 2. Glob match against absolute path
        if fnmatch.fnmatch(abs_t, pat):
            return True
        # 3. Trailing-name match for short globs like **/SOUL.md
        if pat.startswith("**/") and abs_t.endswith(pat[2:]):
            return True
    return False


def _env_in_command(cmd: str, env_patterns: List[str]) -> str:
    """Return matched env name if cmd appears to leak any protected env."""
    for pat in env_patterns or []:
        if "*" in pat:
            # Crude: scan all $TOKENS in cmd, glob-match against pattern
            for token in cmd.split():
                clean = token.lstrip("$").rstrip(",;")
                if fnmatch.fnmatch(clean, pat):
                    return clean
        else:
            if pat in cmd:
                return pat
    return ""


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

_PATH_KEYS = ("path", "file_path", "filename", "target", "dest", "destination")


def _block(message: str, audit_only: bool) -> Dict[str, Any] | None:
    """Return block directive, or None if audit_only mode."""
    if audit_only:
        logger.warning("soul_sandbox AUDIT (would block): %s", message)
        return None
    return {"action": "block", "message": f"[soul_sandbox] {message}"}


def block_protected(tool_name: str, args: Dict[str, Any], **_kw) -> Dict[str, Any] | None:
    cfg, paths = _load_config()
    write_tools: Set[str] = set(cfg.get("write_tools", []))
    audit = bool(cfg.get("audit_only", False))

    # 1. Write tools — check path-shaped args
    if tool_name in write_tools:
        for key in _PATH_KEYS:
            target = args.get(key, "")
            if _path_matches(target, paths):
                return _block(f"보호된 경로 쓰기 차단: {target}", audit)

    # 2. Terminal — combine protected name with risky pattern
    if tool_name == "terminal":
        cmd = args.get("command", "") or ""
        # 2a. file modification of protected paths
        risky = cfg.get("terminal_block_patterns", [])
        for pat in paths:
            name = os.path.basename(pat).replace("*", "")
            if name and name in cmd and any(r in cmd for r in risky):
                return _block(f"보호된 파일 수정 명령 차단: {name}", audit)
        # 2b. env leak triggers + protected env names
        env_triggers = cfg.get("env_leak_triggers", [])
        if any(t in cmd for t in env_triggers):
            leaked = _env_in_command(cmd, cfg.get("protected_env_vars", []))
            if leaked:
                return _block(f"보호된 자격증명 노출 시도 차단: {leaked}", audit)

    return None


# ---------------------------------------------------------------------------
# Slash command — /sandbox list|reload|edit|audit
# ---------------------------------------------------------------------------

def _slash_handler(raw_args: str) -> str:
    arg = (raw_args or "").strip().lower()
    path = _config_path()

    if arg in ("", "list", "show", "status"):
        cfg, paths = _load_config()
        lines = [
            f"sandbox config: {path}",
            f"audit_only: {cfg.get('audit_only', False)}",
            f"protected_paths ({len(paths)}):",
        ]
        for p in sorted(paths):
            lines.append(f"  - {p}")
        envs = cfg.get("protected_env_vars", [])
        lines.append(f"protected_env_vars ({len(envs)}):")
        for e in envs:
            lines.append(f"  - {e}")
        return "\n".join(lines)

    if arg == "reload":
        _CACHE["mtime"] = 0
        _load_config()
        return f"sandbox config reloaded from {path}"

    if arg == "edit":
        return f"sandbox config: {path}\n($EDITOR로 직접 편집 후 /sandbox reload — mtime 변화는 자동 감지)"

    if arg == "audit":
        cfg, _ = _load_config()
        cur = bool(cfg.get("audit_only", False))
        return (
            f"audit_only currently {cur}. "
            "토글하려면 sandbox.yaml에서 audit_only 값을 직접 변경하세요."
        )

    return "Usage: /sandbox [list|reload|edit|audit]"


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", block_protected)
    try:
        ctx.register_command(
            "sandbox",
            handler=_slash_handler,
            description="Show / reload soul_sandbox protection config",
        )
    except Exception as exc:
        # register_command is optional — older plugin runtimes may lack it.
        logger.debug("soul_sandbox: register_command failed: %s", exc)
