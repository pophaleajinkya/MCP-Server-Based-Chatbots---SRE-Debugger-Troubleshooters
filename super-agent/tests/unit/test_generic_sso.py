"""Unit tests for app.pingfed.generic_sso — Generic PingFed SSO login."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


def _make_cookie(name: str, value: str):
    c = MagicMock()
    c.name = name
    c.value = value
    return c


class _FakeResponse:
    def __init__(self, url: str = "https://pfedprod.wal-mart.com/login", text: str = "", status_code: int = 200):
        self.url = url
        self.text = text
        self.status_code = status_code


# ── Tests: _upn ──────────────────────────────────────────────────────────────

class TestUpn:
    def test_appends_suffix(self):
        from app.pingfed.generic_sso import _upn, UPN_SUFFIX
        assert _upn("user") == f"user{UPN_SUFFIX}"

    def test_preserves_existing(self):
        from app.pingfed.generic_sso import _upn
        assert _upn("user@corp.com") == "user@corp.com"


# ── Tests: _create_session ───────────────────────────────────────────────────

class TestCreateSession:
    def test_creates_configured_session(self):
        from app.pingfed.generic_sso import _create_session, BROWSER_UA
        with patch("requests.Session") as mock_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_cls.return_value = mock_session
            s = _create_session()
            assert s.verify is False
            assert s.trust_env is False


# ── Tests: _parse_cookie ────────────────────────────────────────────────────

class TestParseCookie:
    def test_with_token_parser(self):
        from app.pingfed.generic_sso import _parse_cookie
        parser = lambda raw: {"access_token": f"parsed-{raw}"}
        result = _parse_cookie("rawval", "mycookie", parser)
        assert result == {"access_token": "parsed-rawval"}

    def test_without_parser_returns_raw(self):
        from app.pingfed.generic_sso import _parse_cookie
        result = _parse_cookie("rawval", "mycookie", None)
        assert result == {"access_token": "rawval"}

    def test_empty_raw_without_parser_returns_none(self):
        from app.pingfed.generic_sso import _parse_cookie
        assert _parse_cookie("", "mycookie", None) is None

    def test_parser_returning_none(self):
        from app.pingfed.generic_sso import _parse_cookie
        result = _parse_cookie("rawval", "mycookie", lambda _: None)
        assert result is None


# ── Tests: login ─────────────────────────────────────────────────────────────

class TestLogin:
    @patch("app.pingfed.generic_sso._create_session")
    @patch("app.pingfed.generic_sso.follow_auto_submit_forms")
    @patch("app.pingfed.generic_sso.submit_credentials")
    def test_successful_login(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.generic_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth")
        mock_session.cookies = [_make_cookie("_oauth2_proxy", "token123")]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        result = login("https://prometheus.query.prod.mms.walmart.net", "user", "pass", "_oauth2_proxy")
        assert result is not None
        assert result["access_token"] == "token123"

    @patch("app.pingfed.generic_sso._create_session")
    def test_already_authenticated(self, mock_create_session):
        from app.pingfed.generic_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://prometheus.query.prod.mms.walmart.net")
        mock_session.cookies = [_make_cookie("_oauth2_proxy", "existing-token")]
        mock_create_session.return_value = mock_session

        result = login("https://prometheus.query.prod.mms.walmart.net", "user@corp.com", "pass", "_oauth2_proxy")
        assert result == {"access_token": "existing-token"}

    @patch("app.pingfed.generic_sso._create_session")
    def test_not_redirected_no_cookie_returns_none(self, mock_create_session):
        from app.pingfed.generic_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://other.site.com")
        mock_session.cookies = []
        mock_create_session.return_value = mock_session

        assert login("https://target.com", "user", "pass", "_oauth2_proxy") is None

    @patch("app.pingfed.generic_sso._create_session")
    @patch("app.pingfed.generic_sso.follow_auto_submit_forms")
    @patch("app.pingfed.generic_sso.submit_credentials")
    def test_no_cookie_after_login_returns_none(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.generic_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth")
        mock_session.cookies = [_make_cookie("other", "val")]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        assert login("https://target.com", "user", "pass", "_oauth2_proxy") is None

    @patch("app.pingfed.generic_sso._create_session")
    def test_exception_returns_none(self, mock_create_session):
        from app.pingfed.generic_sso import login

        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("down")
        mock_create_session.return_value = mock_session

        assert login("https://target.com", "user", "pass", "_oauth2_proxy") is None

    @patch("app.pingfed.generic_sso._create_session")
    @patch("app.pingfed.generic_sso.follow_auto_submit_forms")
    @patch("app.pingfed.generic_sso.submit_credentials")
    def test_login_with_custom_token_parser(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.generic_sso import login

        mock_session = MagicMock()
        mock_session.get.return_value = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth")
        mock_session.cookies = [_make_cookie("my-cookie", "raw-cookie-val")]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        custom_parser = lambda raw: {"access_token": f"parsed:{raw}", "extra": True}
        result = login("https://target.com", "user", "pass", "my-cookie", token_parser=custom_parser)
        assert result == {"access_token": "parsed:raw-cookie-val", "extra": True}

    @patch("app.pingfed.generic_sso._create_session")
    @patch("app.pingfed.generic_sso.follow_auto_submit_forms")
    @patch("app.pingfed.generic_sso.submit_credentials")
    def test_meta_refresh_loop(self, mock_submit, mock_follow, mock_create_session):
        from app.pingfed.generic_sso import login

        pfed_resp = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth", text='<meta http-equiv="refresh">')
        login_resp = _FakeResponse(url="https://pfedprod.wal-mart.com/as/auth", text='<form id="loginForm">')
        mock_session = MagicMock()
        mock_session.get.side_effect = [pfed_resp, pfed_resp, login_resp]
        mock_session.cookies = [_make_cookie("_oauth2_proxy", "tok")]
        mock_create_session.return_value = mock_session
        mock_submit.return_value = _FakeResponse()
        mock_follow.return_value = _FakeResponse()

        result = login("https://target.com", "user", "pass", "_oauth2_proxy")
        assert result is not None
