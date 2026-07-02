"""Basic integration tests for component interactions.

These tests focus on how different components work together.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestHTTPClientIntegration:
    """Integration tests for HTTP client."""
    
    @pytest.mark.asyncio
    async def test_client_with_bearer_token(self):
        """Test HTTP client with bearer token authentication."""
        from src.http_client import O2HttpClient
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="test_token_123"
        )
        
        headers = client._headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic")
    
    @pytest.mark.asyncio
    async def test_client_with_session_token(self):
        """Test HTTP client with session token."""
        from src.http_client import O2HttpClient
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="session abc123xyz"
        )
        
        headers = client._headers()
        assert "Cookie" in headers


class TestQueryServiceIntegration:
    """Integration tests for QueryService."""
    
    @pytest.mark.asyncio
    async def test_service_with_http_client(self):
        """Test QueryService integration with HTTP client."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        
        service = QueryService(client=client)
        
        assert service._client is client
        assert service._client.base_url == "https://test.com/api"
    
    @pytest.mark.asyncio
    async def test_service_execute_sql(self):
        """Test SQL execution through service."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "hits": [{"_timestamp": 123, "message": "test"}],
                "total": 1
            }
            
            result = await service.execute_sql(
                sql='SELECT * FROM "logs" LIMIT 1',
                stream="logs"
            )
            
            assert result["success"] is True
            assert "hits" in result


class TestConfigIntegration:
    """Integration tests for configuration."""
    
    def test_settings_loads(self):
        """Test settings loading."""
        from src.config import get_settings
        
        settings = get_settings()
        
        assert settings is not None
        assert hasattr(settings, 'endpoint')
        assert hasattr(settings, 'timeout')
    
    def test_settings_to_client(self):
        """Test creating client from settings."""
        from src.config import Settings
        from src.http_client import O2HttpClient
        
        settings = Settings(
            endpoint="https://test.com/api",
            auth_token="test_token",
            timeout=60.0
        )
        
        client = O2HttpClient(settings=settings)
        
        assert client.base_url == "https://test.com/api"


class TestSQLPolicyIntegration:
    """Integration tests for SQL policy."""
    
    def test_policy_validation(self):
        """Test SQL policy validation."""
        from src.tools.sql_policy import run_policy_preflight
        
        sql = 'SELECT _timestamp, status FROM "logs" WHERE _timestamp > 123456 LIMIT 100'
        
        result = run_policy_preflight(sql)
        
        assert hasattr(result, 'ok')
        assert hasattr(result, 'violations')


class TestFunctionRegistryIntegration:
    """Integration tests for function registry."""
    
    def test_registry_loads(self):
        """Test function registry loads."""
        from src.tools.sql_function_registry import preload_registry, get_registry_functions
        
        preload_registry()
        functions = get_registry_functions()
        
        assert isinstance(functions, frozenset)
        assert len(functions) > 0


class TestRulesEngineIntegration:
    """Integration tests for rules engine."""
    
    def test_rules_engine_loads(self):
        """Test rules engine loads default rules."""
        from src.tools.rules import RulesEngine
        
        engine = RulesEngine()
        rules = engine.get_rules("sql")
        
        assert isinstance(rules, dict)
        assert "global" in rules


class TestProviderIntegration:
    """Integration tests for provider layer."""
    
    @pytest.mark.asyncio
    async def test_build_service_helper(self):
        """Test build_service helper function."""
        from src.providers._shared import build_service
        
        service = build_service(
            endpoint="https://test.com/api",
            bearer_token="test_token",
            organization="test_org"
        )
        
        assert service is not None
        assert hasattr(service, 'execute_sql')
        assert hasattr(service, 'list_streams')

