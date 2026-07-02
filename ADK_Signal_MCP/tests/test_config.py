"""Tests for Signal MCP configuration."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_default_settings():
    from src.config import Settings
    s = Settings()
    assert s.signal_base_url == "https://signal-api.walmart.com"
    assert s.signal_timeout == 60.0
    assert s.signal_verify_ssl is True
    assert s.log_level == "INFO"


def test_settings_from_env():
    with patch.dict("os.environ", {
        "SIGNAL_BASE_URL": "https://custom.walmart.com",
        "SIGNAL_TIMEOUT": "30",
        "SIGNAL_VERIFY_SSL": "false",
        "SIGNAL_LOG_LEVEL": "DEBUG",
    }):
        from src.config import Settings
        s = Settings()
        assert s.signal_base_url == "https://custom.walmart.com"
        assert s.signal_timeout == 30.0
        assert s.signal_verify_ssl is False
        assert s.log_level == "DEBUG"


def test_verify_ssl_parse_bool():
    from src.config import Settings
    with patch.dict("os.environ", {"SIGNAL_VERIFY_SSL": "0"}):
        s = Settings()
        assert s.signal_verify_ssl is False

    with patch.dict("os.environ", {"SIGNAL_VERIFY_SSL": "true"}):
        s = Settings()
        assert s.signal_verify_ssl is True
