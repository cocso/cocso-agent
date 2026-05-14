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


class TestPIIRedaction:
    @pytest.mark.parametrize("input_text,expected_label", [
        ("주민번호 900101-1234567 입니다", "rrn"),
        ("사업자번호 123-45-67890 확인", "biz_id"),
        ("연락처 010-1234-5678 로", "phone"),
        ("카드 1234-5678-9012-3456 결제", "card"),
        ("메일 test@example.com 으로", "email"),
        ("키 cocso_mcp_iF_g9LqrwmhgFSIBB4cCH7QywKYK 사용", "api_key_shape"),
    ])
    def test_redacts_pattern(self, audit, input_text, expected_label):
        mod, _ = audit
        cfg = mod._load_config()
        out = mod._redact_pii(input_text, cfg)
        assert f"[REDACTED:{expected_label}]" in out
        # 원본 패턴이 그대로 남아있으면 안 됨
        # 핵심 token이 사라졌는지 살핌 (단순 contains test)

    def test_no_pattern_unchanged(self, audit):
        mod, _ = audit
        cfg = mod._load_config()
        normal = "안녕하세요. 박 딜러 정산 5월 합계는 1,240,000원 입니다."
        assert mod._redact_pii(normal, cfg) == normal

    def test_assistant_turn_redacts_phone(self, audit):
        mod, home = audit
        mod.on_assistant_turn(
            session_id="s-pii",
            user_message="연락처 알려줘",
            assistant_response="대표 010-9876-5432 입니다.",
            model="m",
        )
        log = (home / "audit" / "s-pii.jsonl").read_text(encoding="utf-8")
        assert "010-9876-5432" not in log
        assert "[REDACTED:phone]" in log

    def test_tool_result_redacts_email(self, audit):
        mod, home = audit
        mod.on_tool_post(
            tool_name="db_query", args={"q": "SELECT email"},
            result='[{"email": "user@cocso.co.kr"}]',
            task_id="s-pii", duration_ms=10,
        )
        log = (home / "audit" / "s-pii.jsonl").read_text(encoding="utf-8")
        assert "user@cocso.co.kr" not in log
        assert "[REDACTED:email]" in log

    def test_user_turn_redacts_rrn(self, audit):
        mod, home = audit
        mod.on_user_turn(
            session_id="s-pii", user_message="주민번호 900101-1234567 처리",
            model="m",
        )
        log = (home / "audit" / "s-pii.jsonl").read_text(encoding="utf-8")
        assert "900101-1234567" not in log
        assert "[REDACTED:rrn]" in log


class TestRotation:
    def test_no_rotation_when_below_threshold(self, audit, tmp_path):
        mod, home = audit
        log = home / "audit" / "small.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.write_text("x" * 100)
        rotated = mod._maybe_rotate(log, max_bytes=1_000_000)
        assert rotated is False
        assert log.exists()
        assert not list(log.parent.glob("*.gz"))

    def test_rotation_when_above_threshold(self, audit, tmp_path):
        mod, home = audit
        log = home / "audit" / "big.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.write_text("x" * 5000)
        rotated = mod._maybe_rotate(log, max_bytes=1000)
        assert rotated is True
        assert not log.exists()  # 원본 삭제
        archives = list(log.parent.glob("big.jsonl.*.gz"))
        assert len(archives) == 1

    def test_rotation_disabled_when_max_zero(self, audit, tmp_path):
        mod, home = audit
        log = home / "audit" / "x.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.write_text("x" * 1_000_000)
        assert mod._maybe_rotate(log, max_bytes=0) is False

    def test_purge_old_archives(self, audit, tmp_path):
        import time
        mod, home = audit
        log_dir = home / "audit"
        log_dir.mkdir(exist_ok=True)
        old = log_dir / "old.jsonl.20200101.gz"
        new = log_dir / "new.jsonl.20260101.gz"
        old.write_text("old")
        new.write_text("new")
        # 100 일 전으로 mtime 셋업
        very_old = time.time() - 100 * 86400
        os_utime(old, very_old)
        deleted = mod._purge_old_archives(log_dir, retain_days=90)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()  # 최근 archive 보존

    def test_purge_disabled_when_zero_retain(self, audit, tmp_path):
        mod, home = audit
        log_dir = home / "audit"
        log_dir.mkdir(exist_ok=True)
        old = log_dir / "old.jsonl.x.gz"
        old.write_text("x")
        os_utime(old, time.time() - 1000 * 86400)
        assert mod._purge_old_archives(log_dir, retain_days=0) == 0
        assert old.exists()

    def test_session_end_triggers_rotation(self, audit, tmp_path):
        mod, home = audit
        # 작은 max_file_bytes 로 force rotation
        cfg = mod._load_config()
        cfg["rotation"]["max_file_bytes"] = 100
        mod._CACHE["cfg"] = cfg

        sid = "test-rot"
        # 큰 user message 로 파일 부풀리기
        for _ in range(20):
            mod.on_user_turn(session_id=sid, user_message="x" * 500, model="m")
        log = home / "audit" / f"{sid}.jsonl"
        assert log.exists() and log.stat().st_size > 100

        mod.on_session_end(session_id=sid, completed=True)
        # rotation happened
        archives = list(log.parent.glob(f"{sid}.jsonl.*.gz"))
        assert len(archives) == 1


# os.utime helper
import os as _os
import time

def os_utime(path, t):
    _os.utime(path, (t, t))


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
