"""Unit tests for app.pingfed.sso."""

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class _Cookie:
    def __init__(self, name: str, value: str):
        self.name = name
        self.value = value


class _Resp:
    def __init__(self, *, text: str, url: str, status_code: int = 200):
        self.text = text
        self.url = url
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


class _FakeSession:
    def __init__(self, responses, cookies=None, timeout=(120, 300)):
        self._responses = list(responses)
        self.cookies = cookies or []
        self._default_timeout = timeout

    def get(self, _url, **_kwargs):
        if not self._responses:
            raise AssertionError("No prepared response left")
        return self._responses.pop(0)


class _Elem:
    def __init__(self, visible=True, fail_visible=False):
        self._visible = visible
        self._fail_visible = fail_visible

    async def is_visible(self, timeout=0):
        if self._fail_visible:
            raise RuntimeError("visibility check failed")
        return self._visible

    async def click(self):
        return None

    async def fill(self, _value):
        return None


class _Locator:
    def __init__(self, elem):
        self.first = elem


class _Page:
    def __init__(self, element_map, raise_wait_for_url=False):
        self._element_map = element_map
        self._raise_wait_for_url = raise_wait_for_url

    def locator(self, selector):
        return _Locator(self._element_map.get(selector, _Elem(visible=False)))

    async def goto(self, _url, wait_until):
        return None

    async def wait_for_load_state(self, _state, timeout=None):
        return None

    async def wait_for_url(self, _pattern, timeout=None):
        if self._raise_wait_for_url:
            raise RuntimeError("timed out")


class _Context:
    def __init__(self, page, cookies):
        self._page = page
        self._cookies = cookies

    async def new_page(self):
        return self._page

    async def cookies(self):
        return self._cookies


class _Browser:
    def __init__(self, context):
        self._context = context
        self.closed = False

    async def new_context(self, **_kwargs):
        return self._context

    async def close(self):
        self.closed = True


class _Chromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, **_kwargs):
        return self._browser


class _Playwright:
    def __init__(self, chromium):
        self.chromium = chromium
        self.stopped = False

    async def stop(self):
        self.stopped = True


class _APFactory:
    def __init__(self, pw):
        self._pw = pw

    def __call__(self):
        return self

    async def start(self):
        return self._pw


class TestSsoHelpers:
    def test_upn_appends_suffix_when_missing(self):
        from app.pingfed.sso import _upn

        assert _upn("john123") == "john123@homeoffice.wal-mart.com"

    def test_upn_preserves_existing_upn(self):
        from app.pingfed.sso import _upn

        assert _upn("john@homeoffice.wal-mart.com") == "john@homeoffice.wal-mart.com"

    def test_parse_auth_tokens_from_urlencoded_json(self):
        from app.pingfed.sso import _parse_auth_tokens

        raw = "%7B%22access_token%22%3A%22a1%22%2C%22refresh_token%22%3A%22r1%22%7D"
        assert _parse_auth_tokens(raw) == {"access_token": "a1", "refresh_token": "r1"}

    def test_parse_auth_tokens_regex_fallback_access_only(self):
        from app.pingfed.sso import _parse_auth_tokens

        raw = '{"access_token":"session abc"}'
        assert _parse_auth_tokens(raw) == {"access_token": "session abc"}

    def test_parse_auth_tokens_returns_none_without_access_token(self):
        from app.pingfed.sso import _parse_auth_tokens

        assert _parse_auth_tokens('{"refresh_token":"r1"}') is None

    def test_create_session_sets_required_flags(self):
        from app.pingfed.sso import BROWSER_UA, _create_session

        s = _create_session(timeout=(3, 9))
        assert s.verify is False
        assert s.trust_env is False
        assert s.headers["User-Agent"] == BROWSER_UA
        assert s._default_timeout == (3, 9)


class TestHttpLogin:
    def test_http_login_returns_none_when_dex_endpoint_not_url(self):
        from app.pingfed.sso import _http_login

        session = _FakeSession([
            _Resp(text="'not-a-url'", url="https://service/config/dex_login"),
        ])

        assert _http_login("https://service", "u", "p", session=session) is None

    def test_http_login_returns_tokens_when_already_authenticated(self):
        from app.pingfed.sso import _http_login

        cookies = [_Cookie("auth_tokens", '{"access_token":"a1","refresh_token":"r1"}')]
        session = _FakeSession([
            _Resp(text="http://dex/login", url="https://service/config/dex_login"),
            _Resp(text="ok", url="https://service/home"),
        ], cookies=cookies)

        assert _http_login("https://service", "u", "p", session=session) == {
            "access_token": "a1",
            "refresh_token": "r1",
        }

    def test_http_login_already_authenticated_without_refresh_forces_fallback(self):
        from app.pingfed.sso import _http_login

        cookies = [_Cookie("auth_tokens", '{"access_token":"session abc"}')]
        session = _FakeSession([
            _Resp(text="http://dex/login", url="https://service/config/dex_login"),
            _Resp(text="ok", url="https://service/home"),
        ], cookies=cookies)

        assert _http_login("https://service", "u", "p", session=session) is None

    def test_http_login_pfed_path_calls_submit_and_follow_then_returns_tokens(self, monkeypatch):
        from app.pingfed import sso

        session = _FakeSession([
            _Resp(text="http://dex/login", url="https://service/config/dex_login"),
            _Resp(text="pf", url="https://pfedprod.example/login"),
        ], cookies=[_Cookie("auth_tokens", '{"access_token":"a2","refresh_token":"r2"}')])

        monkeypatch.setattr(sso, "submit_credentials", lambda *args, **kwargs: _Resp(text="submitted", url="https://pfedprod.example/next"))
        monkeypatch.setattr(sso, "follow_auto_submit_forms", lambda *args, **kwargs: _Resp(text="done", url="https://service/home"))
        monkeypatch.setattr(sso, "has_meta_refresh", lambda _html: False)

        result = sso._http_login("https://service", "u", "p", session=session)
        assert result == {"access_token": "a2", "refresh_token": "r2"}

    def test_http_login_pfed_path_missing_refresh_forces_browser_fallback(self, monkeypatch):
        from app.pingfed import sso

        session = _FakeSession([
            _Resp(text="http://dex/login", url="https://service/config/dex_login"),
            _Resp(text="pf", url="https://pfedprod.example/login"),
        ], cookies=[_Cookie("auth_tokens", '{"access_token":"session z"}')])

        monkeypatch.setattr(sso, "submit_credentials", lambda *args, **kwargs: _Resp(text="submitted", url="https://pfedprod.example/next"))
        monkeypatch.setattr(sso, "follow_auto_submit_forms", lambda *args, **kwargs: _Resp(text="done", url="https://service/home"))
        monkeypatch.setattr(sso, "has_meta_refresh", lambda _html: False)

        assert sso._http_login("https://service", "u", "p", session=session) is None


class TestBrowserLogin:
    @pytest.mark.asyncio
    async def test_browser_login_success_returns_tokens_and_closes_resources(self, monkeypatch):
        from app.pingfed import sso

        elements = {
            'button[data-test="sso-login-btn"]': _Elem(visible=True),
            "#username1": _Elem(visible=True),
            "#password": _Elem(visible=True),
            "a.ping-button": _Elem(visible=True),
        }
        page = _Page(elements)
        context = _Context(page, [{"name": "auth_tokens", "value": '{"access_token":"a1","refresh_token":"r1"}'}])
        browser = _Browser(context)
        pw = _Playwright(_Chromium(browser))

        playwright_pkg = types.ModuleType("playwright")
        module = types.ModuleType("playwright.async_api")
        module.async_playwright = _APFactory(pw)
        monkeypatch.setitem(sys.modules, "playwright", playwright_pkg)
        monkeypatch.setitem(sys.modules, "playwright.async_api", module)

        monkeypatch.setattr(sso.asyncio, "sleep", AsyncMock())

        result = await sso._browser_login("https://intl.logs.prod.walmart.com", "user", "pass")

        assert result == {"access_token": "a1", "refresh_token": "r1"}
        assert browser.closed is True
        assert pw.stopped is True

    @pytest.mark.asyncio
    async def test_browser_login_returns_none_when_cookie_missing(self, monkeypatch):
        from app.pingfed import sso

        elements = {
            'button[data-test="sso-login-btn"]': _Elem(visible=True),
            "#username1": _Elem(visible=True),
            "#password": _Elem(visible=True),
            "a.ping-button": _Elem(visible=True),
        }
        page = _Page(elements, raise_wait_for_url=True)
        context = _Context(page, [])
        browser = _Browser(context)
        pw = _Playwright(_Chromium(browser))

        playwright_pkg = types.ModuleType("playwright")
        module = types.ModuleType("playwright.async_api")
        module.async_playwright = _APFactory(pw)
        monkeypatch.setitem(sys.modules, "playwright", playwright_pkg)
        monkeypatch.setitem(sys.modules, "playwright.async_api", module)

        monkeypatch.setattr(sso.asyncio, "sleep", AsyncMock())

        result = await sso._browser_login("https://intl.logs.prod.walmart.com", "user", "pass")

        assert result is None
        assert browser.closed is True
        assert pw.stopped is True


class TestLoginPublicApi:
    @pytest.mark.asyncio
    async def test_login_uses_http_path_first(self, monkeypatch):
        from app.pingfed import sso

        captured = {}

        def _http(_base_url, username, _password):
            captured["username"] = username
            return {"access_token": "a1", "refresh_token": "r1"}

        monkeypatch.setattr(sso, "_http_login", _http)

        result = await sso.login("https://service", "john123", "p")

        assert result == {"access_token": "a1", "refresh_token": "r1"}
        assert captured["username"].endswith("@homeoffice.wal-mart.com")

    @pytest.mark.asyncio
    async def test_login_falls_back_on_needs_credentials(self, monkeypatch):
        from app.pingfed import sso
        from app.pingfed._pfed import NeedsCredentials

        def _http(*_args, **_kwargs):
            raise NeedsCredentials("need creds")

        async def _browser(*_args, **_kwargs):
            return {"access_token": "a2", "refresh_token": "r2"}

        monkeypatch.setattr(sso, "_http_login", _http)
        monkeypatch.setattr(sso, "_browser_login", _browser)

        result = await sso.login("https://service", "john123", "p")

        assert result == {"access_token": "a2", "refresh_token": "r2"}

    @pytest.mark.asyncio
    async def test_login_falls_back_on_http_exception(self, monkeypatch):
        from app.pingfed import sso

        def _http(*_args, **_kwargs):
            raise RuntimeError("network error")

        async def _browser(*_args, **_kwargs):
            return {"access_token": "a3", "refresh_token": "r3"}

        monkeypatch.setattr(sso, "_http_login", _http)
        monkeypatch.setattr(sso, "_browser_login", _browser)

        result = await sso.login("https://service", "john123", "p")

        assert result == {"access_token": "a3", "refresh_token": "r3"}

    @pytest.mark.asyncio
    async def test_login_returns_none_when_browser_times_out(self, monkeypatch):
        from app.pingfed import sso

        monkeypatch.setattr(sso, "_http_login", lambda *_a, **_kw: None)

        async def _wait_for(*_args, **_kwargs):
            raise asyncio.TimeoutError

        monkeypatch.setattr(sso.asyncio, "wait_for", _wait_for)

        result = await sso.login("https://service", "john123", "p")

        assert result is None


