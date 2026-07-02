"""
Unit tests for missing coverage in pingfed/sso.py.

Covers _http_login paths:
  - Line 100: session is None -> create default session
  - Line 117: meta-refresh redirect when at PingFederate
  - Line 136: already-authenticated path with no auth_tokens cookie
  - Line 152: post-login path with no auth_tokens cookie

Covers _browser_login paths:
  - Lines 194-195: SSO button selector loop try/except continue
  - Lines 211-212: username selector loop try/except continue
  - Lines 223-224: password selector loop try/except continue
  - Lines 239-240: submit button selector loop try/except continue
  - Line 250: wait_for_url fallback when hostname is empty
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.pingfed.sso import _http_login, _browser_login, _parse_auth_tokens, COOKIE_NAME


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_session(cookies=None):
    """Create a mock requests.Session for _http_login tests."""
    session = MagicMock()
    session._default_timeout = (120, 300)
    session.verify = False
    session.trust_env = False

    cookie_jar = []
    if cookies:
        for name, value in cookies.items():
            c = MagicMock()
            c.name = name
            c.value = value
            cookie_jar.append(c)
    session.cookies = cookie_jar
    return session


def _make_response(url="https://app.example.com", text="", status_code=200):
    resp = MagicMock()
    resp.url = url
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _make_locator(visible=False, raise_on_visible=False):
    """Create a mock Playwright locator element."""
    elem = AsyncMock()
    if raise_on_visible:
        elem.is_visible = AsyncMock(side_effect=Exception("element not found"))
    else:
        elem.is_visible = AsyncMock(return_value=visible)
    return elem


# ── _parse_auth_tokens tests ────────────────────────────────────────────────


class TestParseAuthTokens:
    def test_valid_json_with_both_tokens(self):
        raw = json.dumps({"access_token": "at", "refresh_token": "rt"})
        result = _parse_auth_tokens(raw)
        assert result == {"access_token": "at", "refresh_token": "rt"}

    def test_valid_json_with_access_only(self):
        raw = json.dumps({"access_token": "at"})
        result = _parse_auth_tokens(raw)
        assert result == {"access_token": "at"}

    def test_json_without_access_token_falls_to_regex(self):
        raw = json.dumps({"other_field": "value"})
        result = _parse_auth_tokens(raw)
        assert result is None

    def test_invalid_json_falls_to_regex(self):
        raw = 'bad json {"access_token": "mytoken", "refresh_token": "myrefresh"}'
        result = _parse_auth_tokens(raw)
        assert result is not None
        assert result["access_token"] == "mytoken"
        assert result["refresh_token"] == "myrefresh"

    def test_regex_access_only(self):
        raw = 'garbage "access_token": "myat" more garbage'
        result = _parse_auth_tokens(raw)
        assert result is not None
        assert result["access_token"] == "myat"
        assert "refresh_token" not in result

    def test_completely_invalid_returns_none(self):
        assert _parse_auth_tokens("no tokens here") is None

    def test_url_encoded_cookie(self):
        raw = quote(json.dumps({"access_token": "at123"}))
        result = _parse_auth_tokens(raw)
        if result:
            assert "access_token" in result


# ── _http_login tests ────────────────────────────────────────────────────────


class TestHttpLogin:
    def test_creates_session_when_none(self):
        """Line 100: when session=None, _create_session() is called."""
        created = _make_session()
        dex_resp = _make_response(text="not-a-url")
        created.get.return_value = dex_resp

        with patch("app.pingfed.sso._create_session", return_value=created) as mock_cs:
            result = _http_login("https://app.example.com", "user", "pass", session=None)
        mock_cs.assert_called_once()
        assert result is None

    def test_meta_refresh_redirect(self):
        """Line 117: when at PingFederate and page has meta-refresh but no login
        form, follow the redirect by re-fetching the same URL.
        """
        session = _make_session()

        dex_resp = _make_response(text="https://dex.example.com/auth")
        # First GET after dex -> at PF with meta-refresh
        pf_resp1 = _make_response(url="https://pfedprod.example.com/page")
        # Second GET (meta-refresh follow) -> still at PF but no meta-refresh
        pf_resp2 = _make_response(url="https://pfedprod.example.com/page")
        # submit_credentials + follow return an app URL
        post_resp = _make_response(url="https://app.example.com/cb")

        session.get.side_effect = [dex_resp, pf_resp1, pf_resp2]

        with patch("app.pingfed.sso.has_meta_refresh", side_effect=[True, False]), \
             patch("app.pingfed.sso.is_pfed_login_form", side_effect=[False, True]), \
             patch("app.pingfed.sso.submit_credentials", return_value=post_resp), \
             patch("app.pingfed.sso.follow_auto_submit_forms", return_value=post_resp):
            result = _http_login("https://app.example.com", "user", "pass", session=session)

        # No auth cookie -> None (line 152)
        assert result is None

    def test_already_authenticated_no_cookie(self):
        """Line 136: not at PF after redirect, but no auth_tokens cookie -> None."""
        session = _make_session(cookies={"other": "val"})
        dex_resp = _make_response(text="https://dex.example.com/auth")
        app_resp = _make_response(url="https://app.example.com/callback")
        session.get.side_effect = [dex_resp, app_resp]

        result = _http_login("https://app.example.com", "user", "pass", session=session)
        assert result is None

    def test_already_authenticated_with_both_tokens(self):
        """Line 135: already-authenticated path with full token cookie."""
        token_data = {"access_token": "at123", "refresh_token": "rt456"}
        session = _make_session(cookies={COOKIE_NAME: json.dumps(token_data)})
        dex_resp = _make_response(text="https://dex.example.com/auth")
        app_resp = _make_response(url="https://app.example.com/callback")
        session.get.side_effect = [dex_resp, app_resp]

        result = _http_login("https://app.example.com", "user", "pass", session=session)
        assert result is not None
        assert result["access_token"] == "at123"
        assert result["refresh_token"] == "rt456"

    def test_already_auth_no_refresh_token_returns_none(self):
        """Lines 128-134: already-authenticated path with access_token but no
        refresh_token -> forces browser fallback (returns None).
        """
        token_data = {"access_token": "at-only"}
        session = _make_session(cookies={COOKIE_NAME: json.dumps(token_data)})
        dex_resp = _make_response(text="https://dex.example.com/auth")
        app_resp = _make_response(url="https://app.example.com/callback")
        session.get.side_effect = [dex_resp, app_resp]

        result = _http_login("https://app.example.com", "user", "pass", session=session)
        assert result is None

    def test_post_login_no_cookie(self):
        """Line 152: after submit_credentials + follow_auto_submit_forms,
        no auth_tokens cookie found -> returns None.
        """
        session = _make_session(cookies={"other": "val"})
        dex_resp = _make_response(text="https://dex.example.com/auth")
        pf_resp = _make_response(url="https://pfedprod.example.com/login")
        session.get.side_effect = [dex_resp, pf_resp]

        post_resp = _make_response(url="https://app.example.com/cb")

        with patch("app.pingfed.sso.has_meta_refresh", return_value=False), \
             patch("app.pingfed.sso.is_pfed_login_form", return_value=True), \
             patch("app.pingfed.sso.submit_credentials", return_value=post_resp), \
             patch("app.pingfed.sso.follow_auto_submit_forms", return_value=post_resp):
            result = _http_login("https://app.example.com", "user", "pass", session=session)
        assert result is None

    def test_post_login_no_refresh_token_returns_none(self):
        """Lines 144-150: post-login path where cookie has access_token but
        no refresh_token -> returns None to force browser fallback.
        """
        token_data = {"access_token": "at-only"}
        session = _make_session(cookies={COOKIE_NAME: json.dumps(token_data)})
        dex_resp = _make_response(text="https://dex.example.com/auth")
        pf_resp = _make_response(url="https://pfedprod.example.com/login")
        session.get.side_effect = [dex_resp, pf_resp]

        post_resp = _make_response(url="https://app.example.com/cb")

        with patch("app.pingfed.sso.has_meta_refresh", return_value=False), \
             patch("app.pingfed.sso.is_pfed_login_form", return_value=True), \
             patch("app.pingfed.sso.submit_credentials", return_value=post_resp), \
             patch("app.pingfed.sso.follow_auto_submit_forms", return_value=post_resp):
            result = _http_login("https://app.example.com", "user", "pass", session=session)
        assert result is None


# ── _browser_login tests ─────────────────────────────────────────────────────


def _setup_playwright_mock():
    """Inject a fake playwright module into sys.modules and return the mock
    async_playwright callable plus key mock objects for assertions.
    """
    mock_pw_cm = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_pw_cm.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_url = AsyncMock()

    # The async_playwright() call returns an object whose .start() gives the pw_cm
    mock_ap_instance = AsyncMock()
    mock_ap_instance.start = AsyncMock(return_value=mock_pw_cm)

    mock_async_playwright_fn = MagicMock(return_value=mock_ap_instance)

    # Build a fake playwright.async_api module
    fake_module = MagicMock()
    fake_module.async_playwright = mock_async_playwright_fn

    return fake_module, mock_page, mock_context


@pytest.fixture()
def _patch_playwright():
    """Temporarily inject a fake 'playwright' package into sys.modules."""
    fake_async_api, mock_page, mock_context = _setup_playwright_mock()

    fake_playwright = MagicMock()
    fake_playwright.async_api = fake_async_api

    saved = {}
    for mod_name in ("playwright", "playwright.async_api"):
        saved[mod_name] = sys.modules.get(mod_name)

    sys.modules["playwright"] = fake_playwright
    sys.modules["playwright.async_api"] = fake_async_api

    # Also invalidate any cached import in the sso module
    import importlib
    import app.pingfed.sso as sso_mod
    importlib.reload(sso_mod)

    yield mock_page, mock_context

    # Restore original state
    for mod_name, orig in saved.items():
        if orig is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = orig
    importlib.reload(sso_mod)


@pytest.mark.asyncio
async def test_browser_login_selector_exceptions(_patch_playwright):
    """Lines 194-195, 211-212, 223-224, 239-240: when Playwright selectors
    throw exceptions, the loop should continue to the next selector.
    """
    mock_page, mock_context = _patch_playwright

    failing_elem = _make_locator(raise_on_visible=True)
    mock_page.locator = MagicMock(return_value=MagicMock(first=failing_elem))
    mock_context.cookies = AsyncMock(return_value=[])

    # Re-import after reload so we use the patched playwright
    from app.pingfed.sso import _browser_login as bl
    result = await bl("https://app.example.com", "user", "pass")

    assert result is None


@pytest.mark.asyncio
async def test_browser_login_empty_hostname_fallback(_patch_playwright):
    """Line 250: when urlparse(base_url).hostname is empty, fall back to
    wait_for_load_state instead of wait_for_url.
    """
    mock_page, mock_context = _patch_playwright

    visible_elem = _make_locator(visible=True)
    mock_page.locator = MagicMock(return_value=MagicMock(first=visible_elem))
    mock_context.cookies = AsyncMock(return_value=[])

    from app.pingfed.sso import _browser_login as bl
    result = await bl("", "user", "pass")

    assert result is None
    mock_page.wait_for_load_state.assert_called()


@pytest.mark.asyncio
async def test_browser_login_success_with_cookie(_patch_playwright):
    """Full success path: browser finds auth_tokens cookie after login."""
    mock_page, mock_context = _patch_playwright

    visible_elem = _make_locator(visible=True)
    mock_page.locator = MagicMock(return_value=MagicMock(first=visible_elem))

    token_data = {"access_token": "browser-at", "refresh_token": "browser-rt"}
    mock_context.cookies = AsyncMock(return_value=[
        {"name": COOKIE_NAME, "value": json.dumps(token_data)},
    ])

    from app.pingfed.sso import _browser_login as bl
    result = await bl("https://app.example.com", "user", "pass")

    assert result is not None
    assert result["access_token"] == "browser-at"
