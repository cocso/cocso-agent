"""Tests for cocso_core.secrets — Secret backend abstraction.

Pins:
- Default backend = env, always available
- Unknown COCSO_SECRET_BACKEND → fallback to env + warning
- get_secret returns env value when set, default otherwise
- get_secret returns default for empty string (== not-found)
- list_known_secrets reports presence + last-4 preview
- KeychainBackend.is_available() correct for current platform
- Active backend cached, reset_backend_cache invalidates
"""
from __future__ import annotations

import os
import pytest

from cocso_core import secrets


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    """매 테스트 fresh — 백엔드 캐시 + COCSO_SECRET_BACKEND env 정리."""
    monkeypatch.delenv("COCSO_SECRET_BACKEND", raising=False)
    secrets.reset_backend_cache()
    yield
    secrets.reset_backend_cache()


class TestDefaultBackend:
    def test_default_is_env(self):
        b = secrets.get_active_backend()
        assert b.name == secrets.BACKEND_ENV
        assert b.is_available()

    def test_get_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("COCSO_TEST_KEY_X", "value-abc")
        assert secrets.get_secret("COCSO_TEST_KEY_X") == "value-abc"

    def test_get_returns_default_when_unset(self):
        assert secrets.get_secret("NO_SUCH_KEY_HERE", "fallback-X") == "fallback-X"

    def test_empty_string_treated_as_not_found(self, monkeypatch):
        monkeypatch.setenv("COCSO_EMPTY_KEY", "")
        assert secrets.get_secret("COCSO_EMPTY_KEY", "default-Y") == "default-Y"


class TestBackendSelection:
    def test_unknown_backend_falls_back_to_env(self, monkeypatch, caplog):
        monkeypatch.setenv("COCSO_SECRET_BACKEND", "nonsense")
        secrets.reset_backend_cache()
        with caplog.at_level("WARNING"):
            b = secrets.get_active_backend()
        assert b.name == secrets.BACKEND_ENV
        assert any("unknown COCSO_SECRET_BACKEND" in r.message for r in caplog.records)

    def test_unavailable_backend_falls_back(self, monkeypatch, caplog):
        # systemd backend requires CREDENTIALS_DIRECTORY env — usually unset
        monkeypatch.setenv("COCSO_SECRET_BACKEND", "systemd")
        monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
        secrets.reset_backend_cache()
        with caplog.at_level("WARNING"):
            b = secrets.get_active_backend()
        # systemd unavailable → env fallback
        assert b.name == secrets.BACKEND_ENV
        assert any("falling back to env" in r.message for r in caplog.records)

    def test_cache_invalidates_on_reset(self, monkeypatch):
        b1 = secrets.get_active_backend()
        monkeypatch.setenv("COCSO_SECRET_BACKEND", "env")  # same name still
        secrets.reset_backend_cache()
        b2 = secrets.get_active_backend()
        assert b1 is not b2  # new instance after reset


class TestEnvBackendOps:
    def test_is_always_available(self):
        b = secrets.EnvBackend()
        assert b.is_available()

    def test_get_returns_none_for_empty(self, monkeypatch):
        monkeypatch.setenv("X_EMPTY", "")
        b = secrets.EnvBackend()
        assert b.get("X_EMPTY") is None


class TestVaultBackend:
    def test_unavailable_without_env(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        b = secrets.VaultBackend()
        assert b.is_available() is False

    def test_available_with_both_env(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com")
        monkeypatch.setenv("VAULT_TOKEN", "tok")
        b = secrets.VaultBackend()
        assert b.is_available() is True


class TestSystemdCredsBackend:
    def test_unavailable_without_credentials_dir(self, monkeypatch):
        monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
        b = secrets.SystemdCredsBackend()
        assert b.is_available() is False

    def test_reads_file_when_available(self, monkeypatch, tmp_path):
        creds = tmp_path / "creds"
        creds.mkdir()
        (creds / "MY_KEY").write_text("secret-value")
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(creds))
        b = secrets.SystemdCredsBackend()
        assert b.is_available()
        assert b.get("MY_KEY") == "secret-value"
        assert b.get("MISSING") is None


class TestListKnownSecrets:
    def test_reports_presence_and_preview(self, monkeypatch):
        monkeypatch.setenv("COCSO_CLIENT_KEY", "cocso_mcp_abcdef1234567890")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        secrets.reset_backend_cache()

        listed = secrets.list_known_secrets()
        client_key = next(s for s in listed if s["key"] == "COCSO_CLIENT_KEY")
        assert client_key["in_active_backend"] is True
        assert client_key["preview"] == "7890"

        openai = next(s for s in listed if s["key"] == "OPENAI_API_KEY")
        assert openai["in_active_backend"] is False
        assert openai["preview"] is None
