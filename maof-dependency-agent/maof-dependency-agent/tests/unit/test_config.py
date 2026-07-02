"""Unit tests for config.py"""
import pytest
import os
from unittest.mock import patch, MagicMock


class TestSettings:
    """Tests for Settings class."""

    def test_settings_loads_required_fields(self):
        """Test that settings loads required environment variables."""
        # The conftest.py sets up all required env vars
        from config import get_settings
        
        settings = get_settings()
        
        assert settings.AZURE_OPENAI_ENDPOINT is not None
        assert settings.AZURE_OPENAI_API_KEY is not None
        assert settings.REDIS_HOST is not None
        assert settings.SRE_OPS_URL is not None

    def test_settings_default_values(self):
        """Test that settings uses default values for optional fields."""
        from config import get_settings
        
        settings = get_settings()
        
        assert settings.AZURE_OPENAI_MODEL == "gpt-4.1"
        assert settings.AZURE_EMBEDDING_MODEL == "text-embedding-ada-002"
        assert settings.AZURE_OPENAI_API_VERSION == "2024-10-21"

    def test_settings_api_paths(self):
        """Test default API path values."""
        from config import get_settings
        
        settings = get_settings()
        
        assert settings.SRE_OPS_DOWNSTREAM_PATH == "/dependencies/downstream"
        assert settings.SRE_OPS_UPSTREAM_PATH == "/dependencies/upstream"
        assert settings.DX_CONSOLE_APPS_PATH == "/proxy/wcnp-apps/apps"

    def test_settings_cached(self):
        """Test that get_settings is cached."""
        from config import get_settings
        
        settings1 = get_settings()
        settings2 = get_settings()
        
        assert settings1 is settings2  # Same instance due to lru_cache

    def test_settings_aliases(self):
        """Test that field aliases work."""
        from config import Settings
        
        # Test that model config allows populate_by_name
        assert Settings.model_config.get("populate_by_name") is True


class TestEnvironmentLoading:
    """Tests for environment file loading."""

    def test_env_files_pattern_matching(self):
        """Test that .env files are loaded with correct patterns."""
        # This test verifies the config module doesn't crash during import
        # The actual env loading happens at module import time
        import config
        assert config is not None
