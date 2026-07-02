"""Unit tests for app.pingfed._pfed — HTML form parsing and HTTP submission helpers."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.pingfed._pfed import (
    NeedsCredentials,
    _FormParser,
    follow_auto_submit_forms,
    has_auto_submit_form,
    has_meta_refresh,
    is_pfed_login_form,
    parse_form,
    submit_credentials,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class _Resp:
    """Lightweight stand-in for requests.Response."""

    def __init__(self, *, text: str, url: str, status_code: int = 200):
        self.text = text
        self.url = url
        self.status_code = status_code


class _FakeSession:
    """Records calls and returns canned responses."""

    def __init__(self, get_responses=None, post_responses=None):
        self._gets = list(get_responses or [])
        self._posts = list(post_responses or [])
        self.cookies = MagicMock()

    def get(self, url, **kwargs):
        if not self._gets:
            raise AssertionError("No GET responses left")
        return self._gets.pop(0)

    def post(self, url, **kwargs):
        if not self._posts:
            raise AssertionError("No POST responses left")
        return self._posts.pop(0)


# ── _FormParser ───────────────────────────────────────────────────────────────


class TestFormParser:

    def test_parses_action_and_method(self):
        parser = _FormParser()
        parser.feed('<form action="/submit" method="get"><input name="x" value="1"></form>')
        assert parser.action == "/submit"
        assert parser.method == "GET"
        assert parser.fields == {"x": "1"}

    def test_defaults_method_to_post(self):
        parser = _FormParser()
        parser.feed('<form action="/a"></form>')
        assert parser.method == "POST"

    def test_collects_multiple_inputs(self):
        parser = _FormParser()
        parser.feed(
            '<form action="/a">'
            '<input name="a" value="1">'
            '<input name="b" value="2">'
            '<input name="c" value="3">'
            '</form>'
        )
        assert parser.fields == {"a": "1", "b": "2", "c": "3"}

    def test_input_without_value_defaults_to_empty(self):
        parser = _FormParser()
        parser.feed('<form action="/a"><input name="q"></form>')
        assert parser.fields == {"q": ""}

    def test_input_without_name_is_ignored(self):
        parser = _FormParser()
        parser.feed('<form action="/a"><input value="orphan"></form>')
        assert parser.fields == {}


# ── parse_form ────────────────────────────────────────────────────────────────


class TestParseForm:

    def test_basic_form(self):
        html = '<form action="/login" method="post"><input name="user" value="me"></form>'
        action, method, fields = parse_form(html)
        assert action == "/login"
        assert method == "POST"
        assert fields == {"user": "me"}

    def test_resolves_relative_action_with_base_url(self):
        html = '<form action="/callback"><input name="t" value="v"></form>'
        action, _, _ = parse_form(html, base_url="https://example.com/path")
        assert action == "https://example.com/callback"

    def test_absolute_action_with_base_url(self):
        html = '<form action="https://other.com/post"><input name="a" value="b"></form>'
        action, _, _ = parse_form(html, base_url="https://example.com")
        assert action == "https://other.com/post"

    def test_no_form_returns_none_action(self):
        action, method, fields = parse_form("<html><body>No form</body></html>")
        assert action is None
        assert method == "POST"
        assert fields == {}

    def test_empty_html(self):
        action, method, fields = parse_form("")
        assert action is None
        assert fields == {}

    def test_no_base_url_skips_resolution(self):
        html = '<form action="/relative"><input name="k" value="v"></form>'
        action, _, _ = parse_form(html)
        assert action == "/relative"

    def test_base_url_ignored_when_action_is_none(self):
        html = "<form><input name='x' value='1'></form>"
        action, _, _ = parse_form(html, base_url="https://base.com")
        assert action is None


# ── has_meta_refresh ──────────────────────────────────────────────────────────


class TestHasMetaRefresh:

    def test_present(self):
        assert has_meta_refresh('<meta http-equiv="refresh" content="0;url=/">')

    def test_present_single_quotes(self):
        assert has_meta_refresh("<meta http-equiv='refresh' content='0'>")

    def test_absent(self):
        assert not has_meta_refresh("<html><body>hello</body></html>")

    def test_case_insensitive(self):
        assert has_meta_refresh('<META HTTP-EQUIV="Refresh" content="0">')

    def test_no_quotes_around_refresh(self):
        assert has_meta_refresh("<meta http-equiv=refresh content=0>")

    def test_empty_html(self):
        assert not has_meta_refresh("")


# ── has_auto_submit_form ──────────────────────────────────────────────────────


class TestHasAutoSubmitForm:

    def test_onload(self):
        assert has_auto_submit_form('<form><body onload="submit()"></body></form>')

    def test_saml_request(self):
        assert has_auto_submit_form('<form><input name="SAMLRequest" value="abc"></form>')

    def test_saml_response(self):
        assert has_auto_submit_form('<form><input name="SAMLResponse" value="xyz"></form>')

    def test_wresult(self):
        assert has_auto_submit_form('<form><input name="wresult" value="data"></form>')

    def test_document_forms_submit(self):
        html = '<form action="/x"><script>document.forms[0].submit()</script></form>'
        assert has_auto_submit_form(html)

    def test_no_form_tag(self):
        assert not has_auto_submit_form('<body onload="submit()">No form tag</body>')

    def test_empty_html(self):
        assert not has_auto_submit_form("")

    def test_form_without_auto_submit_markers(self):
        assert not has_auto_submit_form('<form action="/a"><input name="x"></form>')


# ── is_pfed_login_form ────────────────────────────────────────────────────────


class TestIsPfedLoginForm:

    def test_pf_username_present(self):
        assert is_pfed_login_form('<input name="pf.username">')

    def test_pf_pass_present(self):
        assert is_pfed_login_form('<input name="pf.pass">')

    def test_both_present(self):
        assert is_pfed_login_form('<input name="pf.username"><input name="pf.pass">')

    def test_neither_present(self):
        assert not is_pfed_login_form('<input name="username"><input name="password">')

    def test_case_insensitive(self):
        assert is_pfed_login_form('<input name="PF.USERNAME">')

    def test_empty_html(self):
        assert not is_pfed_login_form("")


# ── submit_credentials ────────────────────────────────────────────────────────


class TestSubmitCredentials:

    def test_happy_path_with_form(self):
        """When the GET response contains a parseable form, submit_credentials
        fills in pf.username / pf.pass and POSTs to the form action."""
        form_html = (
            '<form action="https://pfed.example/submit" method="post">'
            '<input name="pf.adapterId" value="AdpFormUPN">'
            '<input name="pf.cancel" value="">'
            "</form>"
        )
        get_resp = _Resp(text=form_html, url="https://pfed.example/login")
        post_resp = _Resp(text="ok", url="https://app.example/home")

        session = _FakeSession(get_responses=[get_resp], post_responses=[post_resp])
        result = submit_credentials(session, "https://pfed.example/login", "u", "p")
        assert result.url == "https://app.example/home"

    def test_fallback_direct_post_when_no_form_action(self):
        """When the HTML has no <form> tag, falls back to a direct POST."""
        get_resp = _Resp(text="<html>no form</html>", url="https://pfed.example/login")
        post_resp = _Resp(text="fallback ok", url="https://pfed.example/result")

        session = _FakeSession(get_responses=[get_resp], post_responses=[post_resp])
        result = submit_credentials(session, "https://pfed.example/login", "u", "p")
        assert result.url == "https://pfed.example/result"

    def test_meta_refresh_triggers_second_get(self):
        """When the initial GET has a meta refresh, a second GET is issued."""
        refresh_html = '<meta http-equiv="refresh" content="0;url=/">'
        form_html = (
            '<form action="https://pfed.example/real">'
            '<input name="token" value="abc">'
            "</form>"
        )
        first = _Resp(text=refresh_html, url="https://pfed.example/login")
        second = _Resp(text=form_html, url="https://pfed.example/login")
        post_resp = _Resp(text="done", url="https://app.example/home")

        session = _FakeSession(get_responses=[first, second], post_responses=[post_resp])
        result = submit_credentials(session, "https://pfed.example/login", "u", "p")
        assert result.url == "https://app.example/home"

    def test_sets_pfed_cookies(self):
        """Verifies that pf.chosenBU and pf.chosenDomain cookies are set."""
        get_resp = _Resp(text="<html></html>", url="https://pfed.example/login")
        post_resp = _Resp(text="ok", url="https://pfed.example/result")

        session = _FakeSession(get_responses=[get_resp], post_responses=[post_resp])
        submit_credentials(session, "https://pfed.example/login", "u", "p")

        session.cookies.set.assert_any_call("pf.chosenBU", "ho", domain="pfed.example")
        session.cookies.set.assert_any_call("pf.chosenDomain", "US", domain="pfed.example")

    def test_adapter_id_injected_when_missing(self):
        """When form lacks pf.adapterId, it is injected as PFED_ADAPTER_ID."""
        form_html = (
            '<form action="https://pfed.example/submit">'
            '<input name="token" value="t">'
            "</form>"
        )
        get_resp = _Resp(text=form_html, url="https://pfed.example/login")

        posted_data = {}

        class CapturingSession(_FakeSession):
            def post(self, url, **kwargs):
                posted_data.update(kwargs.get("data", {}))
                return _Resp(text="ok", url=url)

        session = CapturingSession(get_responses=[get_resp])
        submit_credentials(session, "https://pfed.example/login", "u", "p")
        assert posted_data["pf.adapterId"] == "AdpFormUPN"


# ── follow_auto_submit_forms ─────────────────────────────────────────────────


class TestFollowAutoSubmitForms:

    def test_auto_submit_chain(self):
        """Follows a chain of auto-submit SAML forms."""
        saml_html = (
            '<form action="https://sp.example/acs" method="post">'
            '<input name="SAMLResponse" value="abc">'
            "</form>"
        )
        final_html = "<html><body>Welcome</body></html>"

        first = _Resp(text=saml_html, url="https://idp.example/sso")
        second = _Resp(text=final_html, url="https://sp.example/home")

        session = _FakeSession(post_responses=[second])
        result = follow_auto_submit_forms(session, first)
        assert result.url == "https://sp.example/home"

    def test_max_hops_limits_iterations(self):
        """Stops after max_hops even if forms keep coming."""
        saml_html = (
            '<form action="https://loop.example/next" method="post">'
            '<input name="SAMLResponse" value="loop">'
            "</form>"
        )
        responses = [_Resp(text=saml_html, url="https://loop.example/next") for _ in range(10)]
        session = _FakeSession(post_responses=responses)

        initial = _Resp(text=saml_html, url="https://loop.example/start")
        result = follow_auto_submit_forms(session, initial, max_hops=3)
        # After 3 hops we should still be in the loop, not all 10
        assert result.url == "https://loop.example/next"

    def test_breaks_on_login_form(self):
        """Stops when it encounters a PingFed login form (pf.username)."""
        login_html = (
            '<form action="/login"><body onload="x">'
            '<input name="SAMLResponse" value="x">'
            '<input name="pf.username" value="">'
            "</body></form>"
        )
        initial = _Resp(text=login_html, url="https://pfed.example/login")
        session = _FakeSession()
        result = follow_auto_submit_forms(session, initial)
        assert result.url == "https://pfed.example/login"

    def test_breaks_on_non_200(self):
        """Stops when the response status is not 200 or 401."""
        initial = _Resp(text="error", url="https://example.com/err", status_code=500)
        session = _FakeSession()
        result = follow_auto_submit_forms(session, initial)
        assert result.status_code == 500

    def test_allows_401_to_continue(self):
        """401 is allowed (PingFed may return 401 mid-chain)."""
        saml_401 = (
            '<form action="https://sp.example/acs" method="post">'
            '<input name="SAMLResponse" value="x">'
            "</form>"
        )
        final = "<html>done</html>"
        initial = _Resp(text=saml_401, url="https://idp.example", status_code=401)
        post_resp = _Resp(text=final, url="https://sp.example/home")

        session = _FakeSession(post_responses=[post_resp])
        result = follow_auto_submit_forms(session, initial)
        assert result.url == "https://sp.example/home"

    def test_get_method(self):
        """Uses GET when form method is GET."""
        html = (
            '<form action="https://sp.example/get" method="get">'
            '<input name="SAMLResponse" value="abc">'
            "</form>"
        )
        final = "<html>done</html>"
        initial = _Resp(text=html, url="https://idp.example")
        get_resp = _Resp(text=final, url="https://sp.example/get?SAMLResponse=abc")

        session = _FakeSession(get_responses=[get_resp])
        result = follow_auto_submit_forms(session, initial)
        assert result.url.startswith("https://sp.example/get")

    def test_meta_refresh_without_auto_submit_triggers_get(self):
        """When only meta refresh is present (no auto-submit markers), issues GET."""
        refresh_html = '<meta http-equiv="refresh" content="0;url=/next">'
        final_html = "<html>final</html>"

        initial = _Resp(text=refresh_html, url="https://example.com/redirect")
        get_resp = _Resp(text=final_html, url="https://example.com/next")

        session = _FakeSession(get_responses=[get_resp])
        result = follow_auto_submit_forms(session, initial)
        assert result.url == "https://example.com/next"

    def test_breaks_when_no_action_or_fields(self):
        """Stops when parse_form returns no action or no fields."""
        html = '<form><body onload="x"><input name="SAMLResponse" value="y"></body></form>'
        # form has no action attribute
        initial = _Resp(text=html, url="https://example.com/stuck")
        session = _FakeSession()
        result = follow_auto_submit_forms(session, initial)
        assert result.url == "https://example.com/stuck"

    def test_no_auto_submit_returns_immediately(self):
        """Plain HTML with no auto-submit markers returns unchanged."""
        initial = _Resp(text="<html>plain</html>", url="https://example.com/plain")
        session = _FakeSession()
        result = follow_auto_submit_forms(session, initial)
        assert result is initial


# ── NeedsCredentials exception ────────────────────────────────────────────────


class TestNeedsCredentials:

    def test_is_exception(self):
        exc = NeedsCredentials("test")
        assert isinstance(exc, Exception)
        assert str(exc) == "test"
