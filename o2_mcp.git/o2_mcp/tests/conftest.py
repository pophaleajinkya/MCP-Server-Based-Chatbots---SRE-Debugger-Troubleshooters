"""Pytest configuration and shared fixtures."""
import pytest
import sys
from unittest.mock import Mock, MagicMock


# Mock fastmcp globally before any tests import it
def pytest_configure(config):
    """Configure pytest and mock external dependencies."""
    # Mock fastmcp module and its submodules
    fastmcp_mock = MagicMock()
    fastmcp_mock.FastMCP = MagicMock()
    fastmcp_mock.server = MagicMock()
    fastmcp_mock.server.providers = MagicMock()
    fastmcp_mock.server.providers.LocalProvider = MagicMock()

    sys.modules['fastmcp'] = fastmcp_mock
    sys.modules['fastmcp.server'] = fastmcp_mock.server
    sys.modules['fastmcp.server.providers'] = fastmcp_mock.server.providers

    # Register custom markers
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (deselect with '-m \"not integration\"')"
    )


@pytest.fixture
def mock_settings():
    """Provide a mock settings object."""
    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.endpoint = "https://test.example.com/api"
    settings.auth_token = "test_token"
    settings.org_id = "test_org"
    settings.timeout = 60.0
    settings.ssl_verify = False
    settings.max_limit = 10000
    settings.default_limit = 1000
    settings.default_time_range = "1h"
    settings.schema_field_threshold = 30
    settings.enable_sql_validation = True
    settings.enable_vrl_validation = True
    settings.enable_sql_ast = True
    settings.max_retries = 5
    settings.log_level = "INFO"
    return settings


@pytest.fixture
def mock_http_client():
    """Provide a mock O2HttpClient."""
    from unittest.mock import MagicMock, AsyncMock
    client = MagicMock()
    client.org = "test_org"
    client.base_url = "https://test.example.com/api"
    client.parse_time_range = MagicMock(return_value=(1000000, 2000000))
    client.now_us = MagicMock(return_value=2000000)
    client.get = AsyncMock(return_value={})
    client.post = AsyncMock(return_value={})
    client.put = AsyncMock(return_value={})
    client.delete = AsyncMock(return_value={})
    return client

