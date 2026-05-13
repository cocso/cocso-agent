"""Tests for COCSO dual MCP auto-registration (Client + Service).

Pins:
- COCSO_CLIENT_MCP_URL → ``cocso-client`` server with COCSO_CLIENT_KEY auth
- COCSO_SERVICE_MCP_URL → ``cocso-service`` server with COCSO_SERVICE_KEY auth
- Either MCP can be configured independently
- User-defined ``mcp_servers`` in config.yaml take precedence (no overwrite)
- Missing key → URL still registered, no Authorization header
- Both auto-registration sites (admin CLI + agent runtime) agree
"""
from __future__ import annotations

import pytest


@pytest.fixture
def env(monkeypatch):
    """Clean slate: clear all COCSO MCP env vars before each test."""
    for var in (
        "COCSO_CLIENT_MCP_URL",
        "COCSO_CLIENT_KEY",
        "COCSO_SERVICE_MCP_URL",
        "COCSO_SERVICE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _admin_servers(env_setup):
    """Run the admin-CLI mirror against an empty config dict."""
    from cocso_cli.mcp_config import _get_mcp_servers
    return _get_mcp_servers({})


class TestClientMcpAutoreg:
    def test_url_and_key_registered(self, env):
        env.setenv("COCSO_CLIENT_MCP_URL", "https://client.example.com/mcp")
        env.setenv("COCSO_CLIENT_KEY", "client-secret")

        servers = _admin_servers(env)
        assert "cocso-client" in servers
        assert servers["cocso-client"]["url"] == "https://client.example.com/mcp"
        assert servers["cocso-client"]["headers"] == {
            "Authorization": "Bearer client-secret"
        }

    def test_url_only_no_auth_header(self, env):
        env.setenv("COCSO_CLIENT_MCP_URL", "https://client.example.com/mcp")

        servers = _admin_servers(env)
        assert "cocso-client" in servers
        assert "headers" not in servers["cocso-client"]

    def test_key_only_does_not_register(self, env):
        env.setenv("COCSO_CLIENT_KEY", "orphan-key")
        servers = _admin_servers(env)
        assert "cocso-client" not in servers


class TestServiceMcpAutoreg:
    def test_url_and_key_registered(self, env):
        env.setenv("COCSO_SERVICE_MCP_URL", "https://service.example.com/mcp")
        env.setenv("COCSO_SERVICE_KEY", "service-secret")

        servers = _admin_servers(env)
        assert "cocso-service" in servers
        assert servers["cocso-service"]["url"] == "https://service.example.com/mcp"
        assert servers["cocso-service"]["headers"] == {
            "Authorization": "Bearer service-secret"
        }

    def test_independent_keys(self, env):
        """Client and Service must use their own keys, not shared."""
        env.setenv("COCSO_CLIENT_MCP_URL", "https://client.x/mcp")
        env.setenv("COCSO_CLIENT_KEY", "ck-only")
        env.setenv("COCSO_SERVICE_MCP_URL", "https://service.x/mcp")
        env.setenv("COCSO_SERVICE_KEY", "sk-only")

        servers = _admin_servers(env)
        assert servers["cocso-client"]["headers"]["Authorization"] == "Bearer ck-only"
        assert servers["cocso-service"]["headers"]["Authorization"] == "Bearer sk-only"

    def test_service_key_does_not_leak_to_client(self, env):
        env.setenv("COCSO_CLIENT_MCP_URL", "https://client.x/mcp")
        env.setenv("COCSO_SERVICE_KEY", "service-only")

        servers = _admin_servers(env)
        # Client URL set but Client KEY not — no header (Service key irrelevant)
        assert "cocso-client" in servers
        assert "headers" not in servers["cocso-client"]


class TestUserConfigPrecedence:
    def test_user_defined_cocso_client_wins(self, env):
        env.setenv("COCSO_CLIENT_MCP_URL", "https://env.example/mcp")
        env.setenv("COCSO_CLIENT_KEY", "from-env")

        from cocso_cli.mcp_config import _get_mcp_servers
        # User defined a custom cocso-client entry in config.yaml
        config = {
            "mcp_servers": {
                "cocso-client": {"url": "https://user.example/mcp"},
            }
        }
        servers = _get_mcp_servers(config)
        assert servers["cocso-client"]["url"] == "https://user.example/mcp"
        # No bearer because user entry has no headers
        assert "headers" not in servers["cocso-client"]


class TestRuntimeParity:
    """Admin CLI mirror and runtime loader must produce equivalent results."""

    def test_runtime_loader_matches_admin(self, env, monkeypatch, tmp_path):
        # Isolate runtime config from any real ~/.cocso/config.yaml
        monkeypatch.setenv("COCSO_HOME", str(tmp_path / "cocso_home"))
        (tmp_path / "cocso_home").mkdir()

        env.setenv("COCSO_CLIENT_MCP_URL", "https://c.x/mcp")
        env.setenv("COCSO_CLIENT_KEY", "ck")
        env.setenv("COCSO_SERVICE_MCP_URL", "https://s.x/mcp")
        env.setenv("COCSO_SERVICE_KEY", "sk")

        from tools.mcp_tool import _load_mcp_config

        runtime_servers = _load_mcp_config()
        admin_servers = _admin_servers(env)

        # Both must produce both COCSO entries with matching URL + auth
        for name in ("cocso-client", "cocso-service"):
            assert name in runtime_servers, f"runtime missing {name}"
            assert name in admin_servers, f"admin missing {name}"
            assert runtime_servers[name]["url"] == admin_servers[name]["url"]
            assert (
                runtime_servers[name].get("headers")
                == admin_servers[name].get("headers")
            )


class TestSetupApplyClassification:
    """Setup wizard env changes must trigger gateway restart."""

    @pytest.mark.parametrize(
        "var",
        [
            "COCSO_COMPANY_NAME",
            "COCSO_CLIENT_MCP_URL",
            "COCSO_CLIENT_KEY",
            "COCSO_SERVICE_MCP_URL",
            "COCSO_SERVICE_KEY",
        ],
    )
    def test_each_cocso_var_requires_restart(self, var):
        from cocso_cli.setup_apply import (
            RESTART_REQUIRED_ENV,
            classify_setup_changes,
        )
        assert var in RESTART_REQUIRED_ENV

        before = {"env": {var: ""}, "config": {}}
        after = {"env": {var: "new-value"}, "config": {}}
        action, env_changed, _ = classify_setup_changes(before, after)
        assert action == "restart"
        assert var in env_changed
