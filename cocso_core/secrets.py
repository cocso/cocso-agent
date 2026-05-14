"""Secret backend abstraction — Keychain / Vault / systemd-creds / env.

cocso 의 모든 secret (`COCSO_*_KEY`, LLM API key, 봇 토큰 등) 은
``get_secret(name)`` 로만 읽도록 권장. 그러면 backend 만 바꿔서:

  - macOS Keychain (`COCSO_SECRET_BACKEND=keychain`)
  - HashiCorp Vault (`COCSO_SECRET_BACKEND=vault`)
  - systemd-creds (`COCSO_SECRET_BACKEND=systemd`)
  - 환경 변수 / ``.env`` (default — 후방 호환)

Env backend 는 항상 작동. 다른 backend 가 unavailable 하거나 키
못 찾으면 env 로 자동 fallback (값 0 보호).

ISMS / 개인정보보호법 컴플라이언스 대응을 위해 prod 배포는 Keychain
또는 Vault 권장. 평문 ``.env`` 는 dev / 첫 셋업 단계 한정.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger(__name__)

# Backend 식별자 (config / env 에서 선택)
BACKEND_ENV = "env"
BACKEND_KEYCHAIN = "keychain"
BACKEND_SYSTEMD = "systemd"
BACKEND_VAULT = "vault"

ALL_BACKENDS = (BACKEND_ENV, BACKEND_KEYCHAIN, BACKEND_SYSTEMD, BACKEND_VAULT)

# Keychain 항목 service prefix — 다른 cocso 인스턴스와 안 겹치게
KEYCHAIN_SERVICE = "cocso-agent"


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class SecretBackend(ABC):
    """Abstract secret store."""

    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool:
        """이 backend 가 현재 환경에서 작동 가능?"""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """key 에 대응하는 secret 반환. 없으면 None."""

    def set(self, key: str, value: str) -> bool:
        """key 에 secret 저장. 미지원 backend 는 False. Default 미지원."""
        return False

    def delete(self, key: str) -> bool:
        """key 삭제. 미지원 backend 는 False."""
        return False

    def list_keys(self) -> List[str]:
        """알려진 key 목록 (가능한 backend만). Default 빈 list."""
        return []


# ---------------------------------------------------------------------------
# Env backend (default — 후방 호환)
# ---------------------------------------------------------------------------

class EnvBackend(SecretBackend):
    """``os.environ`` + ``.env`` (cocso_cli.env_loader). 항상 작동."""

    name = BACKEND_ENV

    def is_available(self) -> bool:
        return True

    def get(self, key: str) -> Optional[str]:
        # .env 가 init 단계에서 로드돼 있으면 os.environ 에 이미 들어감
        v = os.environ.get(key)
        if v is None or v == "":
            return None
        return v

    def set(self, key: str, value: str) -> bool:
        # ``.env`` 파일에 저장 — env_loader 다음 로드 시 반영
        try:
            from cocso_cli.config import save_env_value  # type: ignore[import-untyped]
            save_env_value(key, value)
            os.environ[key] = value
            return True
        except Exception as exc:
            logger.warning("EnvBackend set failed: %s", exc)
            return False

    def delete(self, key: str) -> bool:
        try:
            from cocso_cli.config import save_env_value
            save_env_value(key, "")
            os.environ.pop(key, None)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# macOS Keychain backend
# ---------------------------------------------------------------------------

class KeychainBackend(SecretBackend):
    """macOS Keychain via the ``security`` CLI (system 내장).

    각 key 는 ``cocso-agent`` service 아래 generic-password 로 저장.
    Linux / Windows 에선 unavailable.
    """

    name = BACKEND_KEYCHAIN

    def is_available(self) -> bool:
        # macOS 의 security CLI 존재 확인
        return shutil.which("security") is not None and os.uname().sysname == "Darwin"

    def _run(self, *argv: str, input_text: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["security", *argv],
            input=input_text.encode() if input_text else None,
            capture_output=True, timeout=10,
        )

    def get(self, key: str) -> Optional[str]:
        try:
            r = self._run(
                "find-generic-password",
                "-s", KEYCHAIN_SERVICE,
                "-a", key,
                "-w",
            )
            if r.returncode != 0:
                return None
            v = r.stdout.decode("utf-8").rstrip("\n")
            return v or None
        except Exception as exc:
            logger.debug("KeychainBackend.get(%s) failed: %s", key, exc)
            return None

    def set(self, key: str, value: str) -> bool:
        try:
            # -U: update if exists, create if not
            r = self._run(
                "add-generic-password",
                "-s", KEYCHAIN_SERVICE,
                "-a", key,
                "-w", value,
                "-U",
            )
            return r.returncode == 0
        except Exception as exc:
            logger.warning("KeychainBackend.set(%s) failed: %s", key, exc)
            return False

    def delete(self, key: str) -> bool:
        try:
            r = self._run(
                "delete-generic-password",
                "-s", KEYCHAIN_SERVICE,
                "-a", key,
            )
            return r.returncode == 0
        except Exception:
            return False

    def list_keys(self) -> List[str]:
        # security dump-keychain 은 길고 시끄러움; 대신 알려진 cocso 키만 반환
        # KNOWN_COCSO_KEYS 에서 get(key) 로 존재 여부 확인
        return [k for k in KNOWN_COCSO_KEYS if self.get(k) is not None]


# ---------------------------------------------------------------------------
# systemd-creds backend (Linux managed installs)
# ---------------------------------------------------------------------------

class SystemdCredsBackend(SecretBackend):
    """systemd-creds — Linux 에서 systemd-managed 환경 (CoreOS, NixOS 등).

    write 는 root 필요. 읽기는 ``$CREDENTIALS_DIRECTORY`` 가 set 돼있을 때
    파일에서 직접. 일반 desktop 에선 거의 unavailable.
    """

    name = BACKEND_SYSTEMD

    def is_available(self) -> bool:
        return os.environ.get("CREDENTIALS_DIRECTORY") is not None

    def get(self, key: str) -> Optional[str]:
        d = os.environ.get("CREDENTIALS_DIRECTORY")
        if not d:
            return None
        try:
            from pathlib import Path
            p = Path(d) / key
            if not p.exists():
                return None
            return p.read_text(encoding="utf-8").strip() or None
        except Exception as exc:
            logger.debug("SystemdCredsBackend.get(%s) failed: %s", key, exc)
            return None


# ---------------------------------------------------------------------------
# Vault backend (HashiCorp Vault HTTP)
# ---------------------------------------------------------------------------

class VaultBackend(SecretBackend):
    """HashiCorp Vault HTTP API.

    Env: ``VAULT_ADDR``, ``VAULT_TOKEN``. KV v2 path:
    ``secret/data/cocso-agent/<key>``. Read-only 구현 (write 는 admin tooling).
    """

    name = BACKEND_VAULT

    def is_available(self) -> bool:
        return bool(os.environ.get("VAULT_ADDR") and os.environ.get("VAULT_TOKEN"))

    def _kv_path(self, key: str) -> str:
        addr = os.environ.get("VAULT_ADDR", "").rstrip("/")
        return f"{addr}/v1/secret/data/cocso-agent/{key}"

    def get(self, key: str) -> Optional[str]:
        try:
            import json as _json
            from urllib.request import Request, urlopen
            req = Request(
                self._kv_path(key),
                headers={"X-Vault-Token": os.environ["VAULT_TOKEN"]},
            )
            with urlopen(req, timeout=5) as r:
                if r.status != 200:
                    return None
                data = _json.loads(r.read())
                # KV v2: data.data.value
                v = (data.get("data") or {}).get("data", {}).get("value")
                return v if isinstance(v, str) and v else None
        except Exception as exc:
            logger.debug("VaultBackend.get(%s) failed: %s", key, exc)
            return None


# ---------------------------------------------------------------------------
# Backend selection + public API
# ---------------------------------------------------------------------------

# 자주 다루는 cocso secret 키 — list_keys / migration 에서 사용
KNOWN_COCSO_KEYS = (
    "COCSO_CLIENT_KEY",
    "COCSO_SERVICE_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "XIAOMI_API_KEY",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "TELEGRAM_BOT_TOKEN",
)


_BACKENDS: dict = {
    BACKEND_ENV:      EnvBackend,
    BACKEND_KEYCHAIN: KeychainBackend,
    BACKEND_SYSTEMD:  SystemdCredsBackend,
    BACKEND_VAULT:    VaultBackend,
}

_active_backend: Optional[SecretBackend] = None
_env_fallback: Optional[EnvBackend] = None


def _get_env_fallback() -> EnvBackend:
    global _env_fallback
    if _env_fallback is None:
        _env_fallback = EnvBackend()
    return _env_fallback


def get_active_backend() -> SecretBackend:
    """``COCSO_SECRET_BACKEND`` env 기준 활성 backend.

    값이 unavailable 하면 env 로 자동 fallback (warning 로그).
    """
    global _active_backend
    requested = os.environ.get("COCSO_SECRET_BACKEND", BACKEND_ENV).lower().strip()
    if requested not in ALL_BACKENDS:
        logger.warning(
            "unknown COCSO_SECRET_BACKEND=%r — falling back to %s. "
            "valid: %s", requested, BACKEND_ENV, ", ".join(ALL_BACKENDS),
        )
        requested = BACKEND_ENV

    cls = _BACKENDS[requested]
    if _active_backend is None or _active_backend.name != requested:
        instance = cls()
        if not instance.is_available():
            logger.warning(
                "backend %s unavailable — falling back to env. Install / "
                "configure %s to enable.", requested, requested,
            )
            instance = _get_env_fallback()
        _active_backend = instance
    return _active_backend


def reset_backend_cache() -> None:
    """Test 용 — 활성 backend 캐시 무효화."""
    global _active_backend
    _active_backend = None


def get_secret(key: str, default: str = "") -> str:
    """Top-level secret lookup. 활성 backend → env fallback.

    빈 문자열은 not-found 와 동일 처리 (default 반환).
    """
    backend = get_active_backend()
    v = backend.get(key)
    if v is None or v == "":
        # env fallback (active 가 이미 env 면 한 번 더 호출 = 비용 거의 0)
        if backend.name != BACKEND_ENV:
            v = _get_env_fallback().get(key)
    return v if v else default


def set_secret(key: str, value: str) -> bool:
    """활성 backend 에 secret 저장. 미지원이면 False."""
    return get_active_backend().set(key, value)


def delete_secret(key: str) -> bool:
    """활성 backend 에서 secret 삭제."""
    return get_active_backend().delete(key)


def list_known_secrets() -> List[dict]:
    """Known cocso 키들의 current 상태 (위치, 마지막 char 만)."""
    backend = get_active_backend()
    out = []
    env = _get_env_fallback()
    for k in KNOWN_COCSO_KEYS:
        v_active = backend.get(k)
        v_env = env.get(k) if backend.name != BACKEND_ENV else None
        present = v_active or v_env
        out.append({
            "key": k,
            "in_active_backend": v_active is not None,
            "in_env_fallback": v_env is not None,
            "preview": (present[-4:] if present and len(present) > 4 else None),
        })
    return out
