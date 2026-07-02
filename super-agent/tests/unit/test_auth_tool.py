"""Unit tests for app.tools.auth_tool."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestPingfedTokenTool:
    @pytest.mark.asyncio
    async def test_rejects_empty_cluster_lb(self):
        from app.tools.auth_tool import pingfed_token

        result = await pingfed_token("   ")

        assert result["success"] is False
        assert "cluster_lb is required" in result["error"]
        assert result["cluster_lb"] == ""

    @pytest.mark.asyncio
    async def test_rejects_when_sso_not_configured(self, monkeypatch):
        from app.tools import auth_tool

        monkeypatch.setattr(
            auth_tool,
            "get_settings",
            lambda: SimpleNamespace(sso_username="", sso_password=""),
        )

        result = await auth_tool.pingfed_token("intl.logs.prod.walmart.com")

        assert result["success"] is False
        assert "SSO not configured" in result["error"]
        assert result["cluster_lb"] == "intl.logs.prod.walmart.com"

    @pytest.mark.asyncio
    async def test_success_with_jwt_access_token(self, monkeypatch):
        from app.tools import auth_tool

        monkeypatch.setattr(
            auth_tool,
            "get_settings",
            lambda: SimpleNamespace(sso_username="u", sso_password="p"),
        )
        monkeypatch.setattr(
            auth_tool,
            "get_full_tokens",
            AsyncMock(return_value={"access_token": "jwt-token", "refresh_token": "ignored"}),
        )

        result = await auth_tool.pingfed_token("intl.logs.prod.walmart.com")

        assert result == {
            "success": True,
            "token": "jwt-token",
            "token_type": "Bearer",
            "cluster_lb": "intl.logs.prod.walmart.com",
        }

    @pytest.mark.asyncio
    async def test_success_with_session_token_builds_cookie_json(self, monkeypatch):
        from app.tools import auth_tool

        monkeypatch.setattr(
            auth_tool,
            "get_settings",
            lambda: SimpleNamespace(sso_username="u", sso_password="p"),
        )
        monkeypatch.setattr(
            auth_tool,
            "get_full_tokens",
            AsyncMock(return_value={"access_token": "session abc", "refresh_token": "refresh-1"}),
        )

        result = await auth_tool.pingfed_token("gtp.logs.prod.walmart.com")

        assert result["success"] is True
        assert json.loads(result["token"]) == {
            "access_token": "session abc",
            "refresh_token": "refresh-1",
        }

    @pytest.mark.asyncio
    async def test_session_token_without_refresh_token_returns_error(self, monkeypatch):
        from app.tools import auth_tool

        monkeypatch.setattr(
            auth_tool,
            "get_settings",
            lambda: SimpleNamespace(sso_username="u", sso_password="p"),
        )
        monkeypatch.setattr(
            auth_tool,
            "get_full_tokens",
            AsyncMock(return_value={"access_token": "session abc", "refresh_token": ""}),
        )

        result = await auth_tool.pingfed_token("gtp.logs.prod.walmart.com")

        assert result["success"] is False
        assert "refresh_token is missing" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_access_token_returns_error(self, monkeypatch):
        from app.tools import auth_tool

        monkeypatch.setattr(
            auth_tool,
            "get_settings",
            lambda: SimpleNamespace(sso_username="u", sso_password="p"),
        )
        monkeypatch.setattr(
            auth_tool,
            "get_full_tokens",
            AsyncMock(return_value={"access_token": "   ", "refresh_token": "r"}),
        )

        result = await auth_tool.pingfed_token("gtp.logs.prod.walmart.com")

        assert result["success"] is False
        assert "empty access_token" in result["error"]

    @pytest.mark.asyncio
    async def test_get_full_tokens_exception_is_returned(self, monkeypatch):
        from app.tools import auth_tool

        monkeypatch.setattr(
            auth_tool,
            "get_settings",
            lambda: SimpleNamespace(sso_username="u", sso_password="p"),
        )

        async def _boom(_cluster):
            raise RuntimeError("sso backend unavailable")

        monkeypatch.setattr(auth_tool, "get_full_tokens", _boom)

        result = await auth_tool.pingfed_token("intl.logs.prod.walmart.com")

        assert result == {
            "success": False,
            "error": "sso backend unavailable",
            "cluster_lb": "intl.logs.prod.walmart.com",
        }

