"""Unit tests for app.tools.auth_tool.pingfed_hub — DX Hub JWT tool."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestPingfedHub:
    @pytest.mark.asyncio
    async def test_sso_not_configured(self, monkeypatch):
        from app.tools import auth_tool
        monkeypatch.setattr(auth_tool, "get_settings", lambda: SimpleNamespace(sso_username="", sso_password=""))

        result = await auth_tool.pingfed_hub()
        assert result["success"] is False
        assert "SSO not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_sso_password_missing(self, monkeypatch):
        from app.tools import auth_tool
        monkeypatch.setattr(auth_tool, "get_settings", lambda: SimpleNamespace(sso_username="user", sso_password=""))

        result = await auth_tool.pingfed_hub()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_success_returns_token(self, monkeypatch):
        from app.tools import auth_tool
        monkeypatch.setattr(auth_tool, "get_settings", lambda: SimpleNamespace(sso_username="u", sso_password="p"))
        monkeypatch.setattr(auth_tool, "get_hub_token", AsyncMock(return_value="jwt-hub-token"))

        result = await auth_tool.pingfed_hub()
        assert result == {"success": True, "token": "jwt-hub-token", "token_type": "Bearer"}

    @pytest.mark.asyncio
    async def test_empty_token_returns_error(self, monkeypatch):
        from app.tools import auth_tool
        monkeypatch.setattr(auth_tool, "get_settings", lambda: SimpleNamespace(sso_username="u", sso_password="p"))
        monkeypatch.setattr(auth_tool, "get_hub_token", AsyncMock(return_value=""))

        result = await auth_tool.pingfed_hub()
        assert result["success"] is False
        assert "empty token" in result["error"]

    @pytest.mark.asyncio
    async def test_none_token_returns_error(self, monkeypatch):
        from app.tools import auth_tool
        monkeypatch.setattr(auth_tool, "get_settings", lambda: SimpleNamespace(sso_username="u", sso_password="p"))
        monkeypatch.setattr(auth_tool, "get_hub_token", AsyncMock(return_value=None))

        result = await auth_tool.pingfed_hub()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_exception_returns_error(self, monkeypatch):
        from app.tools import auth_tool
        monkeypatch.setattr(auth_tool, "get_settings", lambda: SimpleNamespace(sso_username="u", sso_password="p"))

        async def _boom():
            raise RuntimeError("hub login failed")

        monkeypatch.setattr(auth_tool, "get_hub_token", _boom)

        result = await auth_tool.pingfed_hub()
        assert result["success"] is False
        assert "hub login failed" in result["error"]
