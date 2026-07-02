"""Unit tests for app.pingfed.hub_sso — DX Hub SSO login."""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_jwt(payload: dict) -> str:
    """Build a fake 3-part JWT with the given payload dict."""
    header = base64.b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


def _make_cookie(name: str, value: str):
    """Return a mock cookie object with .name and .value."""
    c = MagicMock()
    c.name = name
    c.value = value
    return c


class _FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, url: str = "https://pfedprod.wal-mart.com/login", text: str = "", status_code: int = 200):
        self.url = url
        self.text = text
        self.status_code = status_code


# ── Tests: _upn ──────────────────────────────────────────────────────────────

class TestUpn:
    def test_appends_suffix_when_missing(self):
        from app.pingfed.hub_sso import _upn, UPN_SUFFIX
        assert _upn("jsmith") == f"jsmith{UPN_SUFFIX}"

    def test_preserves_existing_domain(self):
        from app.pingfed.hub_sso import _upn
        assert _upn("jsmith@corp.com") == "jsmith@corp.com"


# ── Tests: _get_token_expiry ─────────────────────────────────────────────────

class TestGetTokenExpiry:
    def test_valid_jwt_returns_exp(self):
        from app.pingfed.hub_sso import _get_token_expiry
        token = _make_jwt({"exp": 1712345678.0})
        assert _get_token_expiry(token) == 1712345678.0

    def test_jwt_without_exp_returns_zero(self):
        from app.pingfed.hub_sso import _get_token_expiry
        token = _make_jwt({"sub": "user"})
        assert _get_token_expiry(token) == 0.0

    def test_invalid_jwt_two_parts_returns_zero(self):
        from app.pingfed.hub_sso import _get_token_expiry
        assert _get_token_expiry("header.body") == 0.0

    def test_invalid_jwt_garbage_returns_zero(self):
        from app.pingfed.hub_sso import _get_token_expiry
        assert _get_token_expiry("not-a-jwt") == 0.0

    def test_corrupt_base64_returns_zero(self):
        from app.pingfed.hub_sso import _get_token_expiry
        assert _get_token_expiry("a.!!!.c") == 0.0


# ── Tests: _create_session ───────────────────────────────────────────────────

class TestCreateSession:
    def test_creates_configured_session(self):
        from app.pingfed.hub_sso import _create_session, BROWSER_UA
        with patch("requests.Session") as mock_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_cls.return_value = mock_session

            s = _create_session()

            assert s.verify is False
            assert s.trust_env is False
            assert s.headers["User-Agent"] == BROWSER_UA


# ── Tests: _parse_hub_cookie ────────────────────────────────────────────────

class TestParseHubCookie:
    def test_valid_cookie_with_jwt(self):
        from app.pingfed.hub_sso import _parse_hub_cookie
        token = _make_jwt({"exp": 1712345678.0})
        raw = json.dumps({"token": token})
        result = _parse_hub_cookie(raw)
        assert result is not None
        assert result["access_token"] == token
        assert result["expires_at"] == 1712345678.0

    def test_empty_token_field_returns_none(self):
        from app.pingfed.hub_sso import _parse_hub_cookie
        raw = json.dumps({"token": ""})
        assert _parse_hub_cookie(raw) is None

    def test_missing_token_field_returns_none(self):
        from app.pingfed.hub_sso import _parse_hub_cookie
        raw = json.dumps({"other": "value"})
        assert _parse_hub_cookie(raw) is None

    def test_invalid_json_returns_none(self):
        from app.pingfed.hub_sso import _parse_hub_cookie
        assert _parse_hub_cookie("not-json{{{") is None

    def test_url_encoded_cookie(self):
        from app.pingfed.hub_sso import _parse_hub_cookie
        from urllib.parse import quote
        token = _make_jwt({"exp": 99.0})
        raw = quote(json.dumps({"token": token}))
        result = _parse_hub_cookie(raw)
        assert result is not None
        assert result["access_token"] == token


# ── Tests: login ─────────────────────────────────────────────────────────────

class TestLogin:
    @patch("app.pingfed.hub_sso._create_session")
    @patch("app.pingfed.hub_sso.follow_auto_submit_forms")
    @patch("app.pingfed.hub_sso.submit_credentials")
    def test_successful_login_extracts_jwt(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.hub_sso import login

        token = _make_jwt({"exp": 9999999999.0})
        cookie_val = json.dumps({"token": token})

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth")
        mock_session.cookies = [_make_cookie("hub-ping", cookie_val)]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        result = login("user", "pass")
        assert result is not None
        assert result["access_token"] == token

    @patch("app.pingfed.hub_sso._create_session")
    def test_already_authenticated_extracts_cookie(self, mock_create_session):
        from app.pingfed.hub_sso import login

        token = _make_jwt({"exp": 1234.0})
        cookie_val = json.dumps({"token": token})

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://dx.walmart.com/dashboard")
        mock_session.cookies = [_make_cookie("hub-ping", cookie_val)]
        mock_create_session.return_value = mock_session

        result = login("user@homeoffice.wal-mart.com", "pass")
        assert result is not None
        assert result["access_token"] == token

    @patch("app.pingfed.hub_sso._create_session")
    def test_not_redirected_no_cookie_returns_none(self, mock_create_session):
        from app.pingfed.hub_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://other.site.com")
        mock_session.cookies = []
        mock_create_session.return_value = mock_session

        assert login("user", "pass") is None

    @patch("app.pingfed.hub_sso._create_session")
    @patch("app.pingfed.hub_sso.follow_auto_submit_forms")
    @patch("app.pingfed.hub_sso.submit_credentials")
    def test_login_no_cookie_after_redirect_returns_none(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.hub_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth")
        mock_session.cookies = [_make_cookie("other-cookie", "val")]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        assert login("user", "pass") is None

    @patch("app.pingfed.hub_sso._create_session")
    def test_exception_during_login_returns_none(self, mock_create_session):
        from app.pingfed.hub_sso import login

        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("network down")
        mock_create_session.return_value = mock_session

        assert login("user", "pass") is None

    @patch("app.pingfed.hub_sso._create_session")
    @patch("app.pingfed.hub_sso.follow_auto_submit_forms")
    @patch("app.pingfed.hub_sso.submit_credentials")
    def test_meta_refresh_loop_followed(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.hub_sso import login

        token = _make_jwt({"exp": 5000.0})
        cookie_val = json.dumps({"token": token})

        # Initial GET returns pfedprod URL; subsequent .get calls for meta-refresh loop
        pfed_resp = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth", text='<meta http-equiv="refresh" content="0;url=next">')
        login_resp = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth", text='<form id="loginForm">')

        mock_session = MagicMock()
        mock_session.get.side_effect = [pfed_resp, pfed_resp, login_resp]
        mock_session.cookies = [_make_cookie("hub-ping", cookie_val)]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        result = login("user", "pass")
        assert result is not None
