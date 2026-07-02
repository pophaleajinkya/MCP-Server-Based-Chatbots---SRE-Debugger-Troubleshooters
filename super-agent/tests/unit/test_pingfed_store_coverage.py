"""Additional unit tests for app.pingfed.store — covers _parse_hub_ping_cookie, _bare_host edge cases, _keys."""

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Tests: _parse_hub_ping_cookie ────────────────────────────────────────────

class TestParseHubPingCookie:
    def _make_jwt(self, payload: dict) -> str:
        header = base64.b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
        body = base64.b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"{header}.{body}.sig"

    def test_valid_cookie_with_jwt(self):
        from app.pingfed.store import _parse_hub_ping_cookie
        from urllib.parse import quote
        token = self._make_jwt({"exp": 1712345678.0, "sub": "user"})
        raw = quote(json.dumps({"token": token}))
        result = _parse_hub_ping_cookie(raw)
        assert result is not None
        assert result["access_token"] == token
        assert result["expires_at"] == 1712345678.0

    def test_empty_token_returns_none(self):
        from app.pingfed.store import _parse_hub_ping_cookie
        raw = json.dumps({"token": ""})
        assert _parse_hub_ping_cookie(raw) is None

    def test_invalid_json_returns_none(self):
        from app.pingfed.store import _parse_hub_ping_cookie
        assert _parse_hub_ping_cookie("not{json") is None

    def test_non_jwt_token_gets_zero_expiry(self):
        from app.pingfed.store import _parse_hub_ping_cookie
        raw = json.dumps({"token": "not-a-jwt-token"})
        result = _parse_hub_ping_cookie(raw)
        assert result is not None
        assert result["expires_at"] == 0.0

    def test_jwt_with_exp(self):
        from app.pingfed.store import _parse_hub_ping_cookie
        token = self._make_jwt({"exp": 9999.0})
        raw = json.dumps({"token": token})
        result = _parse_hub_ping_cookie(raw)
        assert result["expires_at"] == 9999.0


# ── Tests: _bare_host ────────────────────────────────────────────────────────

class TestBareHost:
    def test_plain_hostname(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("intl.logs.prod.walmart.com") == "intl.logs.prod.walmart.com"

    def test_with_scheme(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("https://intl.logs.prod.walmart.com") == "intl.logs.prod.walmart.com"

    def test_with_path(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("https://intl.logs.prod.walmart.com/api/v1") == "intl.logs.prod.walmart.com"

    def test_with_port(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("intl.logs.prod.walmart.com:443") == "intl.logs.prod.walmart.com"

    def test_empty_raises(self):
        from app.pingfed.store import _bare_host
        with pytest.raises(ValueError):
            _bare_host("")

    def test_whitespace_only_raises(self):
        from app.pingfed.store import _bare_host
        with pytest.raises(ValueError):
            _bare_host("   ")

    def test_uppercase_lowered(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("INTL.Logs.PROD.walmart.com") == "intl.logs.prod.walmart.com"

    def test_scheme_without_hostname(self):
        from app.pingfed.store import _bare_host
        # Edge case: scheme:// followed by path
        result = _bare_host("https://host.com/path")
        assert result == "host.com"


# ── Tests: _keys ─────────────────────────────────────────────────────────────

class TestKeys:
    def test_key_format(self):
        from app.pingfed.store import _keys
        token_key, lock_key, notify_key = _keys("intl.logs.prod.walmart.com")
        assert "{auth:intl.logs.prod.walmart.com}" in token_key
        assert token_key.endswith(":token")
        assert lock_key.endswith(":lock")
        assert notify_key.endswith(":notify")

    def test_keys_from_url(self):
        from app.pingfed.store import _keys
        token_key, _, _ = _keys("https://intl.logs.prod.walmart.com")
        assert "intl.logs.prod.walmart.com" in token_key


# ── Tests: _LoginConfig registry ─────────────────────────────────────────────

class TestLoginRegistry:
    def test_dx_hub_entry(self):
        from app.pingfed.store import _LOGIN_REGISTRY
        config = _LOGIN_REGISTRY["dx.walmart.com"]
        assert config.cookie_name == "hub-ping"
        assert config.token_parser is not None

    def test_prometheus_entry(self):
        from app.pingfed.store import _LOGIN_REGISTRY
        config = _LOGIN_REGISTRY["prometheus.query.prod.mms.walmart.net"]
        assert config.cookie_name == "_oauth2_proxy"
        assert config.token_parser is None
