"""Additional unit tests for app.config — covers pingfed_url_list and a2a_agents_config_key."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestPingfedUrlList:
    def test_comma_separated_urls(self, env_vars, monkeypatch):
        monkeypatch.setenv("PINGFED_URLS", "https://a.com, https://b.com, https://c.com")
        from app.config import Settings
        s = Settings()
        assert s.pingfed_url_list == ["https://a.com", "https://b.com", "https://c.com"]

    def test_single_url_in_pingfed_urls(self, env_vars, monkeypatch):
        monkeypatch.setenv("PINGFED_URLS", "https://a.com")
        from app.config import Settings
        s = Settings()
        assert s.pingfed_url_list == ["https://a.com"]

    def test_empty_pingfed_urls_falls_back(self, env_vars, monkeypatch):
        monkeypatch.setenv("PINGFED_URLS", "")
        monkeypatch.setenv("PINGFED_BASE_URL", "https://fallback.com")
        from app.config import Settings
        s = Settings()
        assert s.pingfed_url_list == ["https://fallback.com"]

    def test_whitespace_only_pingfed_urls_falls_back(self, env_vars, monkeypatch):
        monkeypatch.setenv("PINGFED_URLS", "   ")
        monkeypatch.setenv("PINGFED_BASE_URL", "https://fallback.com")
        from app.config import Settings
        s = Settings()
        assert s.pingfed_url_list == ["https://fallback.com"]

    def test_urls_with_empty_entries_filtered(self, env_vars, monkeypatch):
        monkeypatch.setenv("PINGFED_URLS", "https://a.com,,  , https://b.com")
        from app.config import Settings
        s = Settings()
        assert s.pingfed_url_list == ["https://a.com", "https://b.com"]


class TestA2aAgentsConfigKey:
    def test_config_key_format(self, env_vars, monkeypatch):
        monkeypatch.setenv("AGENT_ENV", "stage")
        monkeypatch.setenv("AGENT_GROUP", "sre")
        from app.config import Settings
        s = Settings()
        assert s.a2a_agents_config_key == "super_agent:config:a2a_agents:stage:sre:config"

    def test_config_key_different_env(self, env_vars, monkeypatch):
        monkeypatch.setenv("AGENT_ENV", "prod")
        monkeypatch.setenv("AGENT_GROUP", "platform")
        from app.config import Settings
        s = Settings()
        assert s.a2a_agents_config_key == "super_agent:config:a2a_agents:prod:platform:config"
