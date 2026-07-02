"""
Negative and edge-case tests for auth_tool.py and remote_agent.py.

Covers error paths, boundary conditions, malformed inputs, network failures,
and unusual response shapes for both PingFed token tools and the remote A2A
agent proxy.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings_with_sso(**overrides):
    """Return a mock Settings object with SSO credentials set."""
    s = MagicMock()
    s.sso_username = overrides.get("sso_username", "user@walmart.com")
    s.sso_password = overrides.get("sso_password", "s3cret")
    return s


def _settings_without_sso():
    """Return a mock Settings object with SSO credentials missing."""
    s = MagicMock()
    s.sso_username = ""
    s.sso_password = ""
    return s


# ===========================================================================
# pingfed_token — negative / edge-case tests
# ===========================================================================


class TestPingfedTokenEmptyInput:
    """cluster_lb validation: empty, whitespace, None."""

    @pytest.mark.asyncio
    async def test_empty_string(self):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("")
        assert result["success"] is False
        assert "cluster_lb is required" in result["error"]

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("   ")
        assert result["success"] is False
        assert "cluster_lb is required" in result["error"]

    @pytest.mark.asyncio
    async def test_none_value(self):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token(None)
        assert result["success"] is False
        assert "cluster_lb is required" in result["error"]


class TestPingfedTokenSSONotConfigured:
    """SSO username/password missing."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_without_sso())
    async def test_missing_username_and_password(self, _gs):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "SSO not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_settings")
    async def test_missing_password_only(self, mock_gs):
        s = MagicMock()
        s.sso_username = "user"
        s.sso_password = ""
        mock_gs.return_value = s
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "SSO not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_settings")
    async def test_missing_username_only(self, mock_gs):
        s = MagicMock()
        s.sso_username = ""
        s.sso_password = "pass"
        mock_gs.return_value = s
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "SSO not configured" in result["error"]


class TestPingfedTokenGetFullTokensErrors:
    """get_full_tokens raises exceptions."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, side_effect=RuntimeError("browser crashed"))
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_runtime_error(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "browser crashed" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, side_effect=Exception("generic boom"))
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_generic_exception(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "generic boom" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, side_effect=TimeoutError("network timeout"))
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_network_timeout(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "network timeout" in result["error"]


class TestPingfedTokenEmptyTokenReturned:
    """get_full_tokens returns tokens with empty / missing access_token."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "", "refresh_token": "rt"})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_empty_access_token(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "empty access_token" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_empty_dict_returned(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "empty access_token" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "   ", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_whitespace_access_token(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "empty access_token" in result["error"]


class TestPingfedTokenSessionMissingRefresh:
    """Session tokens with missing refresh_token."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "session abc123", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_session_token_no_refresh(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is False
        assert "refresh_token is missing" in result["error"]


class TestPingfedTokenNoneReturned:
    """get_full_tokens returns None (edge case)."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_none_return_raises(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        # None has no .get() so it will raise AttributeError caught by except
        assert result["success"] is False
        assert result["error"]  # some error string


class TestPingfedTokenControlCharsAndLongInput:
    """Unusual cluster_lb values."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "jwt.tok.en", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_control_characters_in_cluster_lb(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster\x00\x01.example.com")
        assert result["success"] is True
        assert result["cluster_lb"] == "cluster\x00\x01.example.com"

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "jwt.tok.en", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_extremely_long_cluster_lb(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        long_name = "a" * 10_000
        result = await pingfed_token(long_name)
        assert result["success"] is True
        assert result["cluster_lb"] == long_name

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "jwt.tok.en", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_unicode_and_spaces_in_cluster_lb(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster \u00e9\u00e8\u00ea.example.com")
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "jwt.tok.en", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_newline_in_cluster_lb(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster\n.example.com")
        assert result["success"] is True


class TestPingfedTokenValidJWT:
    """Valid JWT (non-session) token: happy path through exception-path tests."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "eyJhbGciOiJSUzI1NiJ9.payload.sig", "refresh_token": ""})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_valid_jwt_returned(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is True
        assert result["token"] == "eyJhbGciOiJSUzI1NiJ9.payload.sig"
        assert result["token_type"] == "Bearer"


class TestPingfedTokenSessionWithRefresh:
    """Session token with valid refresh_token — JSON cookie path."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_full_tokens", new_callable=AsyncMock, return_value={"access_token": "session abc123", "refresh_token": "refresh_xyz"})
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_session_token_with_refresh(self, _gs, _gft):
        from app.tools.auth_tool import pingfed_token
        result = await pingfed_token("cluster.example.com")
        assert result["success"] is True
        cookie = json.loads(result["token"])
        assert cookie["access_token"] == "session abc123"
        assert cookie["refresh_token"] == "refresh_xyz"


# ===========================================================================
# pingfed_hub — negative / edge-case tests
# ===========================================================================


class TestPingfedHubSSONotConfigured:
    """SSO not configured for hub token."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_without_sso())
    async def test_sso_not_configured(self, _gs):
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "SSO not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_settings")
    async def test_sso_password_missing(self, mock_gs):
        s = MagicMock()
        s.sso_username = "user"
        s.sso_password = ""
        mock_gs.return_value = s
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "SSO not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_settings")
    async def test_sso_username_missing(self, mock_gs):
        s = MagicMock()
        s.sso_username = ""
        s.sso_password = "pass"
        mock_gs.return_value = s
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "SSO not configured" in result["error"]


class TestPingfedHubGetHubTokenErrors:
    """get_hub_token raises exceptions."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_hub_token", new_callable=AsyncMock, side_effect=RuntimeError("playwright timeout"))
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_runtime_error(self, _gs, _ght):
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "playwright timeout" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_hub_token", new_callable=AsyncMock, side_effect=Exception("unexpected"))
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_generic_exception(self, _gs, _ght):
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "unexpected" in result["error"]


class TestPingfedHubEmptyToken:
    """get_hub_token returns empty or None."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_hub_token", new_callable=AsyncMock, return_value="")
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_empty_token_returned(self, _gs, _ght):
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "empty token" in result["error"]

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_hub_token", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_none_token_returned(self, _gs, _ght):
        from app.tools.auth_tool import pingfed_hub
        result = await pingfed_hub()
        assert result["success"] is False
        assert "empty token" in result["error"]


class TestPingfedHubConcurrent:
    """Concurrent calls to pingfed_hub."""

    @pytest.mark.asyncio
    @patch("app.tools.auth_tool.get_hub_token", new_callable=AsyncMock, return_value="jwt-token-abc")
    @patch("app.tools.auth_tool.get_settings", return_value=_settings_with_sso())
    async def test_concurrent_calls(self, _gs, _ght):
        from app.tools.auth_tool import pingfed_hub
        results = await asyncio.gather(pingfed_hub(), pingfed_hub(), pingfed_hub())
        assert all(r["success"] is True for r in results)
        assert all(r["token"] == "jwt-token-abc" for r in results)


# ===========================================================================
# remote_agent — negative / edge-case tests
# ===========================================================================

def _make_httpx_response(status_code: int, json_body=None, text_body=""):
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "http://test/a2a"),
        json=json_body,
        text=text_body if json_body is None else None,
    )
    return resp


class TestRemoteAgentHTTPErrors:
    """HTTP error status codes from remote agent."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 500, 502, 503])
    async def test_http_error_codes(self, status_code):
        from app.tools.remote_agent import make_remote_agent_tool

        tool = make_remote_agent_tool("test_agent", "test desc", "http://remote:8000")

        mock_resp = httpx.Response(
            status_code=status_code,
            request=httpx.Request("POST", "http://remote:8000/a2a"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            f"HTTP {status_code}", request=mock_resp.request, response=mock_resp
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert f"HTTP {status_code}" in result
        assert "[remote-agent error]" in result


class TestRemoteAgentConnectionErrors:
    """Network-level failures: timeout, refused, SSL."""

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectTimeout("connect timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "[remote-agent error]" in result
        assert "Could not reach" in result

    @pytest.mark.asyncio
    async def test_read_timeout(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "[remote-agent error]" in result

    @pytest.mark.asyncio
    async def test_connect_error(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "[remote-agent error]" in result
        assert "Could not reach" in result

    @pytest.mark.asyncio
    async def test_ssl_error(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "https://remote:8000")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "[remote-agent error]" in result


def _mock_client_returning_json(json_body):
    """Build a mock httpx.AsyncClient that returns a 200 with the given JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = json_body

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


class TestRemoteAgentMalformedResponses:
    """Malformed or unexpected JSON response bodies."""

    @pytest.mark.asyncio
    async def test_malformed_json(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError("bad json", "", 0)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            # json() raises inside the try block -> caught by RequestError? No,
            # JSONDecodeError is not httpx error. It will propagate.
            # Actually it's inside the try block which catches httpx errors only.
            # Let's check: the try block catches HTTPStatusError and RequestError,
            # JSONDecodeError is neither. So it will be unhandled.
            with pytest.raises(json.JSONDecodeError):
                await tool("test query")

    @pytest.mark.asyncio
    async def test_empty_response_body(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError("empty", "", 0)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(json.JSONDecodeError):
                await tool("test query")

    @pytest.mark.asyncio
    async def test_jsonrpc_error_in_response(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "[remote-agent error]" in result
        assert "Invalid Request" in result

    @pytest.mark.asyncio
    async def test_empty_artifacts(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [], "status": {"state": "completed", "message": None}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "completed" in result
        assert "no text output" in result

    @pytest.mark.asyncio
    async def test_artifacts_no_text_parts(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "artifacts": [{"parts": [{"type": "image", "url": "http://img.png"}]}],
                "status": {"state": "completed", "message": None},
            },
        }
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "no text output" in result

    @pytest.mark.asyncio
    async def test_status_message_but_no_text_parts(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "artifacts": [],
                "status": {"state": "working", "message": {"parts": [{"type": "image", "url": "x"}]}},
            },
        }
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "no text output" in result

    @pytest.mark.asyncio
    async def test_missing_result_key(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert "no text output" in result

    @pytest.mark.asyncio
    async def test_status_message_with_text(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "artifacts": [],
                "status": {
                    "state": "working",
                    "message": {"parts": [{"type": "text", "text": "Still processing..."}]},
                },
            },
        }
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("test query")
        assert result == "Still processing..."


class TestRemoteAgentInputEdgeCases:
    """Edge cases for query and session_id parameters."""

    @pytest.mark.asyncio
    async def test_empty_query_string(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_none_session_id(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello", session_id=None)
        # Verify sessionId was NOT in the payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "sessionId" not in payload["params"]["configuration"]
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_valid_session_id(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello", session_id="sess-123")
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["params"]["configuration"]["sessionId"] == "sess-123"

    @pytest.mark.asyncio
    async def test_very_long_query(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        long_query = "x" * 100_000
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool(long_query)
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["params"]["message"]["parts"][0]["text"] == long_query

    @pytest.mark.asyncio
    async def test_unicode_in_query_and_response(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "\u2603 \u2764 \u00e9\u00e8"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("\u00fc\u00f6\u00e4 query \u2603")
        assert "\u2603" in result

    @pytest.mark.asyncio
    async def test_null_bytes_in_query(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello\x00world")
        assert result == "ok"


class TestRemoteAgentBaseURLEdgeCases:
    """base_url formatting edge cases."""

    @pytest.mark.asyncio
    async def test_trailing_slashes_stripped(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000///")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello")
        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url")
        # rstrip('/') only strips the trailing slashes, so endpoint should be correct
        assert url == "http://remote:8000/a2a"

    @pytest.mark.asyncio
    async def test_base_url_with_path_components(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000/api/v1")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await tool("hello")
        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url")
        assert url == "http://remote:8000/api/v1/a2a"


class TestRemoteAgentFactoryParams:
    """Factory parameters: extra_headers, timeout_seconds, function metadata."""

    def test_function_name_and_doc(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("my_cool_agent", "Does cool things", "http://remote:8000")
        assert tool.__name__ == "my_cool_agent"
        assert tool.__doc__ == "Does cool things"

    @pytest.mark.asyncio
    async def test_extra_headers_passed(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            "test_agent", "desc", "http://remote:8000",
            extra_headers={"Authorization": "Bearer tok123"},
        )

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await tool("hello")
        # Check that headers include extra_headers
        call_kwargs = mock_cls.call_args.kwargs if mock_cls.call_args.kwargs else {}
        headers = call_kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer tok123"
        assert headers.get("Content-Type") == "application/json"

    @pytest.mark.asyncio
    async def test_empty_extra_headers(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            "test_agent", "desc", "http://remote:8000",
            extra_headers={},
        )

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await tool("hello")
        call_kwargs = mock_cls.call_args.kwargs if mock_cls.call_args.kwargs else {}
        headers = call_kwargs.get("headers", {})
        assert headers.get("Content-Type") == "application/json"

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            "test_agent", "desc", "http://remote:8000",
            timeout_seconds=300.0,
        )

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await tool("hello")
        call_kwargs = mock_cls.call_args.kwargs if mock_cls.call_args.kwargs else {}
        timeout = call_kwargs.get("timeout")
        assert timeout is not None
        assert timeout.read == 300.0


class TestRemoteAgentResponseShapes:
    """Unusual response shapes: multiple artifacts, unknown state, etc."""

    @pytest.mark.asyncio
    async def test_multiple_artifacts_multiple_parts(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "artifacts": [
                    {"parts": [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]},
                    {"parts": [{"type": "text", "text": "artifact2-part1"}]},
                ],
                "status": {"state": "completed"},
            },
        }
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello")
        # Code only uses artifacts[0], so only first artifact's parts
        assert "part1" in result
        assert "part2" in result
        # artifact2 is not included (code uses artifacts[0] only)
        assert "artifact2" not in result

    @pytest.mark.asyncio
    async def test_unknown_state_value(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "artifacts": [],
                "status": {"state": "some_unknown_state", "message": None},
            },
        }
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello")
        assert "some_unknown_state" in result
        assert "no text output" in result

    @pytest.mark.asyncio
    async def test_status_message_with_non_text_parts_skipped(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "artifacts": [],
                "status": {
                    "state": "working",
                    "message": {"parts": [
                        {"type": "image", "url": "http://img.png"},
                        {"type": "data", "value": 42},
                    ]},
                },
            },
        }
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello")
        assert "no text output" in result

    @pytest.mark.asyncio
    async def test_follow_redirects_enabled(self):
        """Verify the client is created with follow_redirects=True."""
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "result": {"artifacts": [{"parts": [{"type": "text", "text": "ok"}]}], "status": {"state": "completed"}}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await tool("hello")
        call_kwargs = mock_cls.call_args.kwargs if mock_cls.call_args.kwargs else {}
        assert call_kwargs.get("follow_redirects") is True

    @pytest.mark.asyncio
    async def test_jsonrpc_error_with_missing_message(self):
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool("test_agent", "desc", "http://remote:8000")

        body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32700}}
        mock_client = _mock_client_returning_json(body)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool("hello")
        assert "[remote-agent error]" in result
        assert "unknown error" in result
