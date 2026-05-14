"""cocso_audit — compliance audit log + per-session rate limit.

Two responsibilities:

1. **Audit log** — every user turn, assistant response, and tool call is
   written to ``${COCSO_HOME}/audit/<session_id>.jsonl`` as one JSON line.
   Records include timestamp, event type, model, platform, and a redacted
   payload preview (truncated to keep logs scannable).

2. **Rate limit** — tracks tool-call count per session in a sliding
   window. When a session exceeds the configured threshold, further tool
   calls are blocked via a ``pre_tool_call`` directive until the window
   slides forward.

Config lives at ``${COCSO_HOME}/audit.yaml`` (auto-seeded with defaults
on first run). Hot-reloads on mtime change.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    # Where audit logs go (relative to COCSO_HOME).
    "log_dir": "audit",
    # Truncate text fields to this many characters in the JSONL records.
    # Full-fidelity capture is rarely needed; truncation keeps files
    # scannable and avoids leaking long prompt content.
    "max_text_chars": 500,
    # Log rotation — 디스크 무한 증가 방지. 세션별 .jsonl 파일이
    # 임계 넘으면 .jsonl.<ts>.gz 로 압축 보관. 보관 기간 후 삭제.
    "rotation": {
        "max_file_bytes": 5_000_000,    # 5 MB 넘으면 gzip rotate
        "retain_days": 90,              # gzip 90일 후 삭제 (0 = 영구)
    },
    # Per-session sliding-window rate limit on tool calls.
    # 정산서 변환 1건 = sniff + read + 보강 5~10 + create = ~15 호출.
    # 사용자가 연속 2~3건 처리하는 흔한 시나리오 + post_tool_call 자기
    # 자신도 카운트되므로 충분한 여유 필요. 0 = 비활성.
    "rate_limit": {
        "max_tool_calls": 300,       # within window_seconds
        "window_seconds": 60,
    },
    # Drop these tool args from the log record (sensitive).
    "redact_tool_args": [
        "password", "secret", "token", "api_key", "key",
    ],
}


# ---------------------------------------------------------------------------
# Config loading with mtime cache
# ---------------------------------------------------------------------------

_CACHE: Dict[str, Any] = {"mtime": 0.0, "cfg": None, "path": None, "log_dir": None}
_LOCK = threading.Lock()
_RATE_BUCKETS: Dict[str, Deque[float]] = defaultdict(deque)


def _cocso_home() -> Path:
    try:
        from cocso_core.cocso_constants import get_cocso_home
        return get_cocso_home()
    except Exception:
        return Path.home() / ".cocso"


def _config_path() -> Path:
    cached = _CACHE.get("path")
    if cached is not None:
        return cached
    p = _cocso_home() / "audit.yaml"
    _CACHE["path"] = p
    return p


def _seed_default(path: Path) -> None:
    if not yaml:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("cocso_audit: seeded default config at %s", path)
    except Exception as exc:
        logger.warning("cocso_audit: failed to seed config: %s", exc)


def _load_config() -> Dict[str, Any]:
    path = _config_path()
    if not path.exists():
        _seed_default(path)
        if not path.exists():
            return DEFAULT_CONFIG
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return DEFAULT_CONFIG
    if mtime == _CACHE["mtime"] and _CACHE["cfg"] is not None:
        return _CACHE["cfg"]
    cfg: Dict[str, Any] = DEFAULT_CONFIG
    if yaml:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                cfg = {**DEFAULT_CONFIG, **loaded}
                # nested merge for rate_limit
                rl = {**DEFAULT_CONFIG["rate_limit"], **(loaded.get("rate_limit") or {})}
                cfg["rate_limit"] = rl
        except Exception as exc:
            logger.warning("cocso_audit: %s parse error: %s", path, exc)
    _CACHE.update({"mtime": mtime, "cfg": cfg})
    return cfg


def _log_dir() -> Path:
    cfg = _load_config()
    sub = cfg.get("log_dir", "audit")
    p = _cocso_home() / sub
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


# ---------------------------------------------------------------------------
# Log rotation — 디스크 무한 증가 방지
# ---------------------------------------------------------------------------

def _maybe_rotate(path: Path, max_bytes: int) -> bool:
    """파일 크기가 max_bytes 넘으면 gzip 으로 rename 후 새 파일 시작.

    Returns True if rotation happened. Best-effort: 실패해도 audit 계속.
    """
    if max_bytes <= 0:
        return False
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False
    try:
        import gzip
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d-%H%M%S")
        archive = path.with_suffix(path.suffix + f".{ts}.gz")
        with path.open("rb") as src, gzip.open(archive, "wb") as dst:
            dst.write(src.read())
        path.unlink()
        logger.info("audit log rotated: %s -> %s", path.name, archive.name)
        return True
    except Exception as exc:
        logger.warning("audit log rotation failed for %s: %s", path, exc)
        return False


def _purge_old_archives(log_dir: Path, retain_days: int) -> int:
    """retain_days 지난 .gz 보관본 삭제. retain_days=0 이면 영구 보관.

    Returns count of files deleted.
    """
    if retain_days <= 0:
        return 0
    try:
        import time as _time
        cutoff = _time.time() - retain_days * 86400
    except Exception:
        return 0
    deleted = 0
    try:
        for f in log_dir.glob("*.gz"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                continue
    except Exception:
        pass
    if deleted:
        logger.info("audit log purge: %d archive(s) older than %d days", deleted, retain_days)
    return deleted


def _rotate_and_purge(session_id: str) -> None:
    """on_session_end 마다 호출 — 해당 세션 파일 rotate 시도 + 오래된 archive 정리.

    Hot path 아니라 안전하게 best-effort.
    """
    cfg = _load_config()
    rot = cfg.get("rotation") or {}
    max_bytes = int(rot.get("max_file_bytes", 0) or 0)
    retain_days = int(rot.get("retain_days", 0) or 0)
    log_dir = _log_dir()
    if max_bytes > 0 and session_id:
        _maybe_rotate(log_dir / f"{session_id}.jsonl", max_bytes)
    if retain_days > 0:
        _purge_old_archives(log_dir, retain_days)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: Any, n: int) -> str:
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return text if len(text) <= n else text[:n] + f"… [+{len(text)-n} chars]"


def _redact_args(args: Dict[str, Any], redact_keys: list) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if any(s in k.lower() for s in redact_keys):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def _write(session_id: str, event: str, **fields) -> None:
    if not session_id:
        session_id = "_unknown"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    path = _log_dir() / f"{session_id}.jsonl"
    try:
        with _LOCK, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logger.debug("cocso_audit: write failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Hook callbacks
# ---------------------------------------------------------------------------

def on_session_start(session_id: str = "", model: str = "", platform: str = "", **_kw) -> None:
    _write(session_id, "session_start", model=model, platform=platform)


def on_session_end(session_id: str = "", completed: bool = False, interrupted: bool = False,
                   model: str = "", platform: str = "", **_kw) -> None:
    _write(session_id, "session_end", model=model, platform=platform,
           completed=completed, interrupted=interrupted)
    # release rate-limit bucket so the deque doesn't grow unbounded
    with _LOCK:
        _RATE_BUCKETS.pop(session_id, None)
    # Best-effort log rotation + archive purge (off critical path).
    try:
        _rotate_and_purge(session_id)
    except Exception as exc:
        logger.debug("rotate_and_purge failed for %s: %s", session_id, exc)


def on_user_turn(session_id: str = "", user_message: str = "", model: str = "",
                 is_first_turn: bool = False, **_kw) -> Optional[Dict[str, Any]]:
    cfg = _load_config()
    n = int(cfg.get("max_text_chars", 500))
    _write(session_id, "user", text=_truncate(user_message, n),
           model=model, first_turn=is_first_turn)
    return None  # no context injection


def on_assistant_turn(session_id: str = "", user_message: str = "",
                      assistant_response: str = "", model: str = "", **_kw) -> None:
    cfg = _load_config()
    n = int(cfg.get("max_text_chars", 500))
    _write(session_id, "assistant", text=_truncate(assistant_response, n), model=model)


def on_tool_pre(tool_name: str = "", args: Optional[Dict[str, Any]] = None,
                task_id: str = "", session_id: str = "", **_kw) -> Optional[Dict[str, Any]]:
    """Rate-limit gate. session_id and task_id are typically aliases."""
    cfg = _load_config()
    rl = cfg.get("rate_limit") or {}
    cap = int(rl.get("max_tool_calls", 0) or 0)
    if cap <= 0:
        return None
    window = float(rl.get("window_seconds", 60) or 60)
    sid = session_id or task_id or "_unknown"
    now = time.monotonic()
    with _LOCK:
        bucket = _RATE_BUCKETS[sid]
        # drop entries outside the window
        cutoff = now - window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= cap:
            return {
                "action": "block",
                "message": (
                    f"[cocso_audit] 세션 도구 호출 한도 초과 "
                    f"({cap}회 / {int(window)}초). 잠시 후 다시 시도하세요."
                ),
            }
        bucket.append(now)
    return None


def on_tool_post(tool_name: str = "", args: Optional[Dict[str, Any]] = None,
                 result: str = "", task_id: str = "", duration_ms: int = 0,
                 **_kw) -> None:
    cfg = _load_config()
    n = int(cfg.get("max_text_chars", 500))
    redact = list(cfg.get("redact_tool_args") or [])
    _write(
        task_id,
        "tool",
        tool=tool_name,
        args=_redact_args(args or {}, redact),
        result_size=len(result or ""),
        result_preview=_truncate(result or "", n),
        duration_ms=int(duration_ms or 0),
    )


# ---------------------------------------------------------------------------
# Slash command — /audit list|tail|stats
# ---------------------------------------------------------------------------

def _slash_handler(raw_args: str) -> str:
    parts = (raw_args or "").strip().split()
    cmd = (parts[0] if parts else "stats").lower()
    log_dir = _log_dir()

    if cmd in ("list", "ls"):
        files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return f"audit log: {log_dir} (비어있음)"
        lines = [f"audit log: {log_dir}"]
        for p in files[:10]:
            size = p.stat().st_size
            lines.append(f"  {p.name}  {size:>8} bytes")
        if len(files) > 10:
            lines.append(f"  ... ({len(files) - 10}개 더)")
        return "\n".join(lines)

    if cmd in ("tail", "show"):
        files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return "audit log: 비어있음"
        latest = files[0]
        n = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 10
        try:
            lines = latest.read_text(encoding="utf-8").splitlines()[-n:]
        except Exception as exc:
            return f"audit tail 실패: {exc}"
        return f"--- {latest.name} (마지막 {n}줄) ---\n" + "\n".join(lines)

    if cmd == "stats":
        files = list(log_dir.glob("*.jsonl"))
        total_size = sum(p.stat().st_size for p in files)
        cfg = _load_config()
        rl = cfg.get("rate_limit") or {}
        return (
            f"audit log dir: {log_dir}\n"
            f"세션 수: {len(files)}\n"
            f"총 크기: {total_size} bytes\n"
            f"rate limit: {rl.get('max_tool_calls')}/{rl.get('window_seconds')}초 "
            f"(0이면 비활성)\n"
            f"활성 rate buckets: {len(_RATE_BUCKETS)}"
        )

    return "Usage: /audit [list|tail [N]|stats]"


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end",   on_session_end)
    ctx.register_hook("pre_llm_call",     on_user_turn)
    ctx.register_hook("post_llm_call",    on_assistant_turn)
    ctx.register_hook("pre_tool_call",    on_tool_pre)
    ctx.register_hook("post_tool_call",   on_tool_post)
    try:
        ctx.register_command(
            "audit",
            handler=_slash_handler,
            description="Show / inspect cocso_audit logs",
        )
    except Exception as exc:
        logger.debug("cocso_audit: register_command failed: %s", exc)
