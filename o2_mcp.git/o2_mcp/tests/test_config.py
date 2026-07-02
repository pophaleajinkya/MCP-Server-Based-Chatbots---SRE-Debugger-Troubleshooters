"""Tests for src/config.py — Settings fields, computed properties, defaults."""
import base64
import os
import pytest
from unittest.mock import patch

from src.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings(**overrides) -> Settings:
    """Create a Settings instance without reading .env or environment."""
    defaults = {
        "endpoint": "",
        "auth_token": "",
        "org_id": "default",
        "timeout": 60.0,
        "ssl_verify": False,
        "max_limit": 10_000,
        "default_limit": 1_000,
        "default_time_range": "1h",
        "schema_field_threshold": 30,
        "enable_sql_validation": True,
        "enable_vrl_validation": True,
        "enable_sql_ast": True,
        "max_retries": 5,
        "log_level": "INFO",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestSettingsDefaults:

    def test_default_org_id(self):
        s = make_settings()
        assert s.org_id == "default"

    def test_default_timeout(self):
        s = make_settings()
        assert s.timeout == 60.0

    def test_default_ssl_verify_false(self):
        s = make_settings()
        assert s.ssl_verify is False

    def test_default_max_limit(self):
        s = make_settings()
        assert s.max_limit == 10_000

    def test_default_default_limit(self):
        s = make_settings()
        assert s.default_limit == 1_000

    def test_default_time_range(self):
        s = make_settings()
        assert s.default_time_range == "1h"

    def test_default_schema_threshold(self):
        s = make_settings()
        assert s.schema_field_threshold == 30

    def test_default_max_retries(self):
        s = make_settings()
        assert s.max_retries == 5

    def test_default_log_level(self):
        s = make_settings()
        assert s.log_level == "INFO"

    def test_feature_flags_default_true(self):
        s = make_settings()
        assert s.enable_sql_validation is True
        assert s.enable_vrl_validation is True
        assert s.enable_sql_ast is True


# ---------------------------------------------------------------------------
# is_configured()
# ---------------------------------------------------------------------------

class TestIsConfigured:

    def test_not_configured_when_empty(self):
        s = make_settings()
        assert s.is_configured() is False

    def test_not_configured_with_only_endpoint(self):
        s = make_settings(endpoint="https://example.com/api")
        assert s.is_configured() is False

    def test_not_configured_with_only_token(self):
        s = make_settings(auth_token="sometoken")
        assert s.is_configured() is False

    def test_configured_with_both(self):
        s = make_settings(endpoint="https://example.com/api", auth_token="token123")
        assert s.is_configured() is True

    def test_not_configured_with_empty_strings(self):
        s = make_settings(endpoint="", auth_token="")
        assert s.is_configured() is False


# ---------------------------------------------------------------------------
# auth_header (computed)
# ---------------------------------------------------------------------------

class TestAuthHeader:

    def test_empty_when_no_token(self):
        s = make_settings()
        assert s.auth_header == ""

    def test_basic_prefix_with_token(self):
        s = make_settings(auth_token="abc123")
        assert s.auth_header == "Basic abc123"

    def test_token_included_verbatim(self):
        token = "dXNlcjpwYXNz"
        s = make_settings(auth_token=token)
        assert token in s.auth_header


# ---------------------------------------------------------------------------
# base_url (computed)
# ---------------------------------------------------------------------------

class TestBaseUrl:

    def test_empty_when_no_endpoint(self):
        s = make_settings()
        assert s.base_url == ""

    def test_strips_trailing_slash(self):
        s = make_settings(endpoint="https://example.com/api/")
        assert not s.base_url.endswith("/")
        assert s.base_url == "https://example.com/api"

    def test_no_trailing_slash_unchanged(self):
        s = make_settings(endpoint="https://example.com/api")
        assert s.base_url == "https://example.com/api"

    def test_multiple_trailing_slashes_stripped(self):
        s = make_settings(endpoint="https://example.com/api///")
        assert not s.base_url.endswith("/")


# ---------------------------------------------------------------------------
# get_auth_headers()
# ---------------------------------------------------------------------------

class TestGetAuthHeaders:

    def test_returns_dict(self):
        s = make_settings()
        headers = s.get_auth_headers()
        assert isinstance(headers, dict)

    def test_contains_content_type(self):
        s = make_settings()
        headers = s.get_auth_headers()
        assert "Content-Type" in headers
        assert headers["Content-Type"] == "application/json"

    def test_contains_authorization(self):
        s = make_settings(auth_token="tok123")
        headers = s.get_auth_headers()
        assert "Authorization" in headers
        assert "Basic tok123" == headers["Authorization"]

    def test_empty_auth_header_when_no_token(self):
        s = make_settings()
        headers = s.get_auth_headers()
        assert headers.get("Authorization") == ""


# ---------------------------------------------------------------------------
# encode_basic_auth()
# ---------------------------------------------------------------------------

class TestEncodeBasicAuth:

    def test_encodes_correctly(self):
        s = make_settings()
        encoded = s.encode_basic_auth("user", "password")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user:password"

    def test_special_characters_in_password(self):
        s = make_settings()
        encoded = s.encode_basic_auth("user", "p@$$w0rd!#")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user:p@$$w0rd!#"

    def test_empty_password(self):
        s = make_settings()
        encoded = s.encode_basic_auth("user", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user:"

    def test_empty_username(self):
        s = make_settings()
        encoded = s.encode_basic_auth("", "password")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == ":password"

    def test_colon_in_password(self):
        """Password may contain colons — only split on first colon."""
        s = make_settings()
        encoded = s.encode_basic_auth("root", "token:with:colons")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "root:token:with:colons"

    def test_returns_string(self):
        s = make_settings()
        result = s.encode_basic_auth("u", "p")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# max_retries boundary
# ---------------------------------------------------------------------------

class TestMaxRetries:

    def test_default_is_5(self):
        s = make_settings()
        assert s.max_retries == 5

    def test_custom_value(self):
        s = make_settings(max_retries=3)
        assert s.max_retries == 3

    def test_max_retries_1(self):
        s = make_settings(max_retries=1)
        assert s.max_retries == 1

    def test_max_retries_10(self):
        s = make_settings(max_retries=10)
        assert s.max_retries == 10
