"""Tests for src/http_client.py — O2HttpClient and auth helpers."""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

import httpx

from src.http_client import (
    O2HttpClient,
    O2Error,
    O2ApiError,
    O2ConnectionError,
    _bearer_to_basic,
    _is_session_token,
    _is_full_cookie_json,
)
from src.config import Settings


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

class TestBearerToBasic:
    """Test _bearer_to_basic helper."""

    def test_encodes_correctly(self):
        result = _bearer_to_basic("mytoken123")
        import base64
        decoded = base64.b64decode(result).decode()
        assert decoded == "root:mytoken123"

    def test_empty_token(self):
        result = _bearer_to_basic("")
        import base64
        decoded = base64.b64decode(result).decode()
        assert decoded == "root:"

    def test_special_characters(self):
        result = _bearer_to_basic("tok!@#$%")
        import base64
        decoded = base64.b64decode(result).decode()
        assert decoded == "root:tok!@#$%"


class TestIsSessionToken:
    """Test _is_session_token helper."""

    def test_session_token_identified(self):
        assert _is_session_token("session abc123")

    def test_session_token_with_spaces(self):
        assert _is_session_token("  session xyz  ")

    def test_jwt_not_session(self):
        assert not _is_session_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")

    def test_empty_string_not_session(self):
        assert not _is_session_token("")

    def test_none_not_session(self):
        assert not _is_session_token(None)


class TestIsFullCookieJson:
    """Test _is_full_cookie_json helper."""

    def test_valid_cookie_json(self):
        cookie = '{"access_token":"session xyz","refresh_token":"abc"}'
        assert _is_full_cookie_json(cookie)

    def test_minimal_valid_json(self):
        assert _is_full_cookie_json('{"access_token":"tok"}')

    def test_invalid_json(self):
        assert not _is_full_cookie_json('{invalid json')

    def test_missing_access_token(self):
        assert not _is_full_cookie_json('{"refresh_token":"xyz"}')

    def test_empty_access_token(self):
        assert not _is_full_cookie_json('{"access_token":""}')

    def test_not_json(self):
        assert not _is_full_cookie_json("plain text")

    def test_empty_string(self):
        assert not _is_full_cookie_json("")


# ---------------------------------------------------------------------------
# O2HttpClient
# ---------------------------------------------------------------------------

class TestO2HttpClientInit:
    """Test O2HttpClient initialization."""

    def test_requires_base_url(self):
        with pytest.raises(ValueError, match="base_url is required"):
            O2HttpClient(base_url="")

    def test_accepts_explicit_base_url(self):
        client = O2HttpClient(base_url="https://test.com/api")
        assert client.base_url == "https://test.com/api"

    def test_strips_trailing_slash(self):
        client = O2HttpClient(base_url="https://test.com/api/")
        assert client.base_url == "https://test.com/api"

    def test_bearer_token_converted_to_basic(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="mytoken"
        )
        assert client._auth_header.startswith("Basic ")

    def test_session_token_uses_cookie(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="session xyz123"
        )
        assert client._session_cookie
        assert not client._auth_header

    def test_full_cookie_json_uses_cookie(self):
        cookie = '{"access_token":"session xyz","refresh_token":"abc"}'
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token=cookie
        )
        assert client._session_cookie == cookie
        assert not client._auth_header

    def test_auth_token_priority(self):
        """bearer_token takes priority over auth_token."""
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="bearer123",
            auth_token="auth456"
        )
        # bearer_token should be converted to Basic auth
        assert client._auth_header.startswith("Basic")
        # The auth header should contain the base64 encoded version of "root:bearer123"
        import base64
        expected = base64.b64encode(b"root:bearer123").decode()
        assert expected in client._auth_header

    def test_custom_org_id(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123",
            org_id="custom-org"
        )
        assert client.org == "custom-org"

    def test_custom_timeout(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123",
            timeout=120.0
        )
        assert client._timeout == 120.0


class TestO2HttpClientHeaders:
    """Test _headers method."""

    def test_headers_with_auth_header(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="tok123"
        )
        headers = client._headers()
        assert "Authorization" in headers
        assert "Content-Type" in headers

    def test_headers_with_session_cookie(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="session xyz"
        )
        headers = client._headers()
        assert "Cookie" in headers
        assert "auth_tokens=" in headers["Cookie"]


@pytest.mark.asyncio
class TestO2HttpClientRequest:
    """Test request method."""

    async def test_successful_get(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client._http = AsyncMock()
        client._http.is_closed = False
        client._http.request = AsyncMock(return_value=mock_response)

        result = await client.request("GET", "/test")

        assert result == {"success": True}
        client._http.request.assert_called_once()

    async def test_handles_401_error(self):
        exc = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401, text="Unauthorized")
        )

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client._http = AsyncMock()
        client._http.is_closed = False
        client._http.request = AsyncMock(side_effect=exc)

        with pytest.raises(O2ApiError) as excinfo:
            await client.request("GET", "/test")

        assert excinfo.value.status_code == 401

    async def test_handles_timeout(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123",
            timeout=10.0
        )
        client._http = AsyncMock()
        client._http.is_closed = False
        client._http.request = AsyncMock(
            side_effect=httpx.TimeoutException("Timeout")
        )

        with pytest.raises(O2ConnectionError, match="timed out"):
            await client.request("GET", "/test")

    async def test_handles_connection_error(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client._http = AsyncMock()
        client._http.is_closed = False
        client._http.request = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(O2ConnectionError, match="Cannot connect"):
            await client.request("GET", "/test")

    async def test_handles_non_json_response(self):
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("test", "", 0)
        mock_response.status_code = 502
        mock_response.text = "<html>Bad Gateway</html>"
        mock_response.raise_for_status = MagicMock()

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client._http = AsyncMock()
        client._http.is_closed = False
        client._http.request = AsyncMock(return_value=mock_response)

        with pytest.raises(O2ApiError) as excinfo:
            await client.request("GET", "/test")

        assert "Non-JSON response" in str(excinfo.value)


@pytest.mark.asyncio
class TestO2HttpClientConvenience:
    """Test convenience methods (get, post, put, delete)."""

    async def test_get_method(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client.request = AsyncMock(return_value={"data": "test"})

        result = await client.get("/path", params={"key": "value"})

        client.request.assert_called_once_with("GET", "/path", params={"key": "value"})
        assert result == {"data": "test"}

    async def test_post_method(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client.request = AsyncMock(return_value={"created": True})

        result = await client.post("/path", json={"key": "value"})

        client.request.assert_called_once_with("POST", "/path", json={"key": "value"}, params=None)
        assert result == {"created": True}

    async def test_put_method(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client.request = AsyncMock(return_value={"updated": True})

        result = await client.put("/path", json={"key": "value"})

        client.request.assert_called_once_with("PUT", "/path", json={"key": "value"})

    async def test_delete_method(self):
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="tok123"
        )
        client.request = AsyncMock(return_value={"deleted": True})

        result = await client.delete("/path")

        client.request.assert_called_once_with("DELETE", "/path")


class TestParseTimeRange:
    """Test parse_time_range static method."""

    def test_parses_minutes(self):
        start, end = O2HttpClient.parse_time_range("30m")
        assert isinstance(start, int)
        assert isinstance(end, int)
        assert end > start
        # 30 minutes = 30 * 60 * 1_000_000 microseconds
        assert (end - start) == pytest.approx(30 * 60 * 1_000_000, rel=0.1)

    def test_parses_hours(self):
        start, end = O2HttpClient.parse_time_range("2h")
        assert (end - start) == pytest.approx(2 * 3600 * 1_000_000, rel=0.1)

    def test_parses_days(self):
        start, end = O2HttpClient.parse_time_range("1d")
        assert (end - start) == pytest.approx(24 * 3600 * 1_000_000, rel=0.1)

    def test_defaults_to_1h_on_empty(self):
        start, end = O2HttpClient.parse_time_range("")
        assert (end - start) == pytest.approx(3600 * 1_000_000, rel=0.1)

    def test_defaults_to_1h_on_invalid(self):
        start, end = O2HttpClient.parse_time_range("invalid")
        assert (end - start) == pytest.approx(3600 * 1_000_000, rel=0.1)

    def test_defaults_to_1h_on_negative(self):
        start, end = O2HttpClient.parse_time_range("-5h")
        assert (end - start) == pytest.approx(3600 * 1_000_000, rel=0.1)

    def test_defaults_to_1h_on_zero(self):
        start, end = O2HttpClient.parse_time_range("0h")
        assert (end - start) == pytest.approx(3600 * 1_000_000, rel=0.1)


class TestNowUs:
    """Test now_us static method."""

    def test_returns_microseconds(self):
        result = O2HttpClient.now_us()
        assert isinstance(result, int)
        assert result > 0

    def test_reasonable_value(self):
        """Should be close to current time in microseconds."""
        result = O2HttpClient.now_us()
        now = datetime.now(timezone.utc).timestamp() * 1_000_000
        # Should be within 1 second
        assert abs(result - now) < 1_000_000


class TestO2Exceptions:
    """Test custom exception classes."""

    def test_o2_error_is_exception(self):
        assert issubclass(O2Error, Exception)

    def test_o2_api_error_has_status_code(self):
        err = O2ApiError(404, "Not found")
        assert err.status_code == 404
        assert err.message == "Not found"
        assert "404" in str(err)

    def test_o2_connection_error_is_o2_error(self):
        assert issubclass(O2ConnectionError, O2Error)

