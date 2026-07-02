"""Tests for configuration module."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_default_settings():
    """Settings should have sane defaults without any env vars."""
    with patch.dict(os.environ, {}, clear=True):
        from src.config import Settings
        s = Settings()
        assert s.valid8_base_url == "https://intl-valid8-qa.walmart.com"
        assert s.valid8_api_key == ""
        assert s.valid8_timeout == 60.0
        assert s.valid8_verify_ssl is True
        assert s.log_level == "INFO"


def test_ssl_bool_parsing():
    """VALID8_VERIFY_SSL should accept various string representations."""
    with patch.dict(os.environ, {"VALID8_VERIFY_SSL": "false"}, clear=True):
        from src.config import Settings
        s = Settings()
        assert s.valid8_verify_ssl is False

    with patch.dict(os.environ, {"VALID8_VERIFY_SSL": "true"}, clear=True):
        from src.config import Settings
        s = Settings()
        assert s.valid8_verify_ssl is True


def test_custom_base_url():
    with patch.dict(
        os.environ,
        {"VALID8_BASE_URL": "https://valid8.dev.walmart.com"},
        clear=True,
    ):
        from src.config import Settings
        s = Settings()
        assert s.valid8_base_url == "https://valid8.dev.walmart.com"


def test_custom_timeout():
    with patch.dict(os.environ, {"VALID8_TIMEOUT": "120"}, clear=True):
        from src.config import Settings
        s = Settings()
        assert s.valid8_timeout == 120.0


def test_api_key_from_env():
    with patch.dict(os.environ, {"VALID8_API_KEY": "my-secret-key"}, clear=True):
        from src.config import Settings
        s = Settings()
        assert s.valid8_api_key == "my-secret-key"
