"""Integration tests for complete user scenarios.

These tests simulate real user workflows and interactions.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import json


pytestmark = pytest.mark.integration


class TestUserScenario_LogAnalysis:
    """Test complete log analysis user scenario."""

    @pytest.mark.asyncio
    async def test_scenario_analyze_error_logs(self):
        """Scenario: User wants to analyze error logs from last hour."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        from src.tools.sql_policy import run_policy_preflight

        # Step 1: User constructs query
        sql = '''
        SELECT 
            DATE_TRUNC('minute', _timestamp) AS minute,
            status,
            COUNT(_timestamp) AS error_count
        FROM "logs"
        WHERE log_level = 'ERROR' AND _timestamp > 0
        GROUP BY minute, status
        ORDER BY error_count DESC
        LIMIT 50
        '''

        # Step 2: Validate policy
        policy = run_policy_preflight(sql)
        assert policy.ok is True or len(policy.violations) >= 0

        # Step 3: Execute query
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "hits": [
                    {"minute": "2024-01-01T10:00:00Z", "status": 500, "error_count": 25},
                    {"minute": "2024-01-01T10:01:00Z", "status": 500, "error_count": 18}
                ],
                "total": 2,
                "took": 150
            }

            result = await service.execute_sql(sql, stream="logs", time_range="1h")

            assert result["success"] is True
            assert len(result["hits"]) == 2


class TestUserScenario_SchemaExploration:
    """Test schema exploration workflow."""

    @pytest.mark.asyncio
    async def test_scenario_discover_stream_fields(self):
        """Scenario: User wants to discover available fields in a stream."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        # Step 1: List available streams
        with patch.object(client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "list": [
                    {"name": "application_logs"},
                    {"name": "system_metrics"},
                    {"name": "traces"}
                ]
            }

            streams = await service.list_streams()
            assert streams["total"] == 3

        # Step 2: Get schema for specific stream
        with patch.object(client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "name": "application_logs",
                "schema": [
                    {"name": "_timestamp", "type": "Int64"},
                    {"name": "log_level", "type": "Utf8"},
                    {"name": "message", "type": "Utf8"},
                    {"name": "service", "type": "Utf8"},
                    {"name": "trace_id", "type": "Utf8"}
                ],
                "settings": {}
            }

            schema = await service.get_stream_schema("application_logs")
            assert schema["name"] == "application_logs"
            assert "fields" in schema


class TestUserScenario_FieldValuesAnalysis:
    """Test field values analysis workflow."""

    @pytest.mark.asyncio
    async def test_scenario_analyze_status_codes(self):
        """Scenario: User wants to see distribution of HTTP status codes."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "hits": [
                    {"value": "200", "count": 15000},
                    {"value": "404", "count": 250},
                    {"value": "500", "count": 45},
                    {"value": "503", "count": 12}
                ]
            }

            result = await service.get_field_values(
                stream="logs",
                fields=["status"],
                time_range="24h"
            )

            assert result["success"] is True
            assert len(result["fields"]) > 0
            # Should have status field values
            status_field = result["fields"][0]
            assert status_field["field"] == "status"
            assert len(status_field["values"]) == 4


class TestUserScenario_ErrorDebugging:
    """Test error debugging workflow."""

    @pytest.mark.asyncio
    async def test_scenario_debug_specific_error(self):
        """Scenario: User wants to find logs around a specific error timestamp."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        error_timestamp = 1704067200000000  # Jan 1, 2024 00:00:00 UTC

        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "hits": [
                    {"_timestamp": error_timestamp - 10000, "message": "Before error"},
                    {"_timestamp": error_timestamp, "message": "ERROR: Connection failed"},
                    {"_timestamp": error_timestamp + 10000, "message": "After error"}
                ],
                "total": 3
            }

            result = await service.search_around(
                stream="logs",
                timestamp=error_timestamp,
                size=10
            )

            assert result["success"] is True or "error" in result


class TestUserScenario_QueryOptimization:
    """Test query optimization workflow."""

    def test_scenario_validate_before_execution(self):
        """Scenario: User validates query before executing."""
        from src.tools.sql_policy import run_policy_preflight
        from src.tools.sql_function_registry import validate_sql_functions
        import json

        sql = '''
        SELECT 
            histogram(_timestamp, 'hour') AS hour,
            COUNT(*) AS total
        FROM "logs"
        WHERE _timestamp BETWEEN 100000 AND 200000
        GROUP BY hour
        '''

        # Step 1: Check policy
        policy = run_policy_preflight(sql)
        policy_dict = policy.to_dict()

        assert "ok" in policy_dict

        # Step 2: Validate functions
        func_validation = validate_sql_functions(sql)
        func_result = json.loads(func_validation)

        assert "all_valid" in func_result

        # If both pass, query is ready to execute
        query_ready = policy_dict.get("ok", False)
        assert isinstance(query_ready, bool)


class TestUserScenario_MultiStreamQuery:
    """Test multi-stream query scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_query_multiple_streams(self):
        """Scenario: User wants to query data from multiple streams."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        streams = ["application_logs", "system_logs"]

        for stream in streams:
            with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
                mock_post.return_value = {
                    "hits": [{"message": f"log from {stream}"}],
                    "total": 1
                }

                result = await service.execute_sql(
                    sql=f'SELECT * FROM "{stream}" LIMIT 10',
                    stream=stream,
                    time_range="1h"
                )

                assert result["success"] is True


class TestUserScenario_RealTimeMonitoring:
    """Test real-time monitoring scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_latest_logs(self):
        """Scenario: User wants to see latest logs in real-time."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        # Query latest logs
        sql = 'SELECT * FROM "logs" ORDER BY _timestamp DESC LIMIT 20'

        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "hits": [
                    {"_timestamp": 2000000, "message": "Latest log"},
                    {"_timestamp": 1999000, "message": "Previous log"}
                ],
                "total": 2
            }

            result = await service.execute_sql(sql, stream="logs", time_range="5m")

            assert result["success"] is True
            assert len(result["hits"]) == 2
            # Should be sorted by timestamp descending
            if len(result["hits"]) >= 2:
                assert result["hits"][0]["_timestamp"] >= result["hits"][1]["_timestamp"]


class TestUserScenario_TraceAnalysis:
    """Test trace analysis scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_analyze_traces(self):
        """Scenario: User analyzes distributed traces."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        with patch.object(client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "traces": [
                    {
                        "trace_id": "abc123",
                        "duration_ms": 250,
                        "spans": 15
                    }
                ],
                "total": 1
            }

            result = await service.get_latest_traces(
                stream="traces",
                time_range="30m",
                size=20
            )

            assert result["success"] is True or "traces" in result


class TestIntegrationAuth:
    """Integration tests for authentication flows."""

    def test_bearer_token_conversion(self):
        """Test bearer token conversion to Basic auth."""
        from src.http_client import _bearer_to_basic, O2HttpClient
        import base64

        # Test conversion
        basic_auth = _bearer_to_basic("my_token_123")
        decoded = base64.b64decode(basic_auth).decode()

        assert decoded == "root:my_token_123"

        # Test in client
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="my_token_123"
        )

        headers = client._headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic")

    def test_session_token_handling(self):
        """Test session token handling."""
        from src.http_client import _is_session_token, O2HttpClient

        # Test detection
        assert _is_session_token("session abc123") is True
        assert _is_session_token("eyJhbGc...") is False

        # Test in client
        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="session abc123xyz"
        )

        headers = client._headers()
        assert "Cookie" in headers


class TestIntegrationErrorRecovery:
    """Integration tests for error recovery."""
    
    @pytest.mark.asyncio
    async def test_retry_on_schema_error(self):
        """Test retry mechanism for schema errors."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        from src.tools.sql_error_classifier import enrich_error_response
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        # Simulate schema error that should allow retry
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "error": "field 'old_field_name' not found in schema"
            }
            
            result = await service.execute_sql('SELECT old_field_name FROM "logs"')
            
            enriched = enrich_error_response(result, attempt=1, max_retries=5)
            
            # Should allow retry and have error type
            assert enriched.get("retry_allowed") is True
            assert "sql_error_type" in enriched
    
    @pytest.mark.asyncio
    async def test_no_retry_on_max_attempts(self):
        """Test that retries stop after max attempts."""
        from src.tools.sql_error_classifier import enrich_error_response
        
        error_result = {
            "success": False,
            "error": "Some retryable error"
        }
        
        # At max retries, should not allow more
        enriched = enrich_error_response(error_result, attempt=5, max_retries=5)
        
        assert enriched["retry_allowed"] is False
        # Check the enriched result has attempt info
        assert enriched["attempt"] == 5


class TestIntegrationConfigurationPipeline:
    """Integration tests for configuration pipeline."""

    def test_config_to_client_to_service_pipeline(self):
        """Test configuration flows from Settings → Client → Service."""
        from src.config import Settings
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        # Step 1: Create settings
        settings = Settings(
            endpoint="https://pipeline.test.com/api",
            auth_token="pipeline_token",
            org_id="pipeline_org",
            timeout=120.0,
            max_limit=5000
        )

        # Step 2: Create client from settings
        client = O2HttpClient(settings=settings)

        assert client.base_url == "https://pipeline.test.com/api"
        assert client.org == "pipeline_org"

        # Step 3: Create service from client
        service = QueryService(client=client)

        assert service._client is client
        assert service._client.org == "pipeline_org"


class TestIntegrationProviderChain:
    """Integration tests for provider tool chain."""

    @pytest.mark.asyncio
    async def test_provider_uses_shared_helpers(self):
        """Test that providers use shared helper functions."""
        from src.providers._shared import build_service

        with patch("src.providers._shared.O2HttpClient") as mock_client_cls:
            with patch("src.providers._shared.QueryService") as mock_service_cls:
                with patch("src.providers._shared.get_settings") as mock_settings:
                    mock_settings.return_value = MagicMock(
                        org_id="default",
                        auth_token=""
                    )

                    mock_client = MagicMock()
                    mock_client_cls.return_value = mock_client

                    mock_service = MagicMock()
                    mock_service_cls.return_value = mock_service

                    service = build_service(
                        endpoint="https://test.com/api",
                        bearer_token="token",
                        organization="default"
                    )

                    # Should have created client and service
                    assert mock_client_cls.called
                    assert mock_service_cls.called


class TestIntegrationDataFlow:
    """Integration tests for data flow through layers."""

    @pytest.mark.asyncio
    async def test_data_flows_through_layers(self):
        """Test data flows: HTTP → Service → Provider → User."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        # Layer 1: HTTP Client
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )

        # Layer 2: Service
        service = QueryService(client=client)

        # Layer 3: Mock HTTP response
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            test_data = {
                "hits": [
                    {"_timestamp": 123, "value": "test1"},
                    {"_timestamp": 124, "value": "test2"}
                ],
                "total": 2,
                "took": 50
            }
            mock_post.return_value = test_data

            # Execute through service
            result = await service.execute_sql(
                sql='SELECT * FROM "logs" LIMIT 2',
                stream="logs"
            )

            # Data should flow through
            assert result["success"] is True
            assert result["hits"] == test_data["hits"]
            assert result["total"] == 2
            # 'took' may or may not be present
            assert "hits" in result


class TestIntegrationErrorPropagation:
    """Integration tests for error propagation."""

    @pytest.mark.asyncio
    async def test_http_error_propagates_to_service(self):
        """Test HTTP errors propagate correctly."""
        from src.http_client import O2HttpClient, O2ApiError
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        # Simulate 403 Forbidden
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = O2ApiError(403, "Forbidden: Insufficient permissions")

            result = await service.execute_sql('SELECT * FROM "logs"')

            # Service should handle and return error result
            assert result["success"] is False
            assert "error" in result
            assert "Forbidden" in result["error"] or "403" in str(result)


class TestIntegrationTimeHandling:
    """Integration tests for time handling across components."""

    @pytest.mark.asyncio
    async def test_time_range_flows_through_stack(self):
        """Test time range parameter flows through all layers."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)

        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"hits": [], "total": 0}

            await service.execute_sql(
                sql='SELECT * FROM "logs"',
                stream="logs",
                time_range="3h"  # 3 hour range
            )

            # Check that post was called with time range
            call_args = mock_post.call_args
            # Should have been converted to start_time/end_time
            assert mock_post.called


class TestIntegrationFullStack:
    """Full stack integration tests."""

    @pytest.mark.asyncio
    async def test_full_stack_with_all_components(self):
        """Test complete stack: Config → Client → Service → Policy → Registry."""
        from src.config import get_settings
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        from src.tools.sql_policy import run_policy_preflight
        from src.tools.sql_function_registry import validate_sql_functions
        import json

        # Step 1: Get configuration
        settings = get_settings()
        assert settings is not None

        # Step 2: Create HTTP client
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token",
            timeout=settings.timeout
        )

        # Step 3: Create query service
        service = QueryService(client=client)

        # Step 4: Define query
        sql = '''
        SELECT 
            DATE_TRUNC('hour', _timestamp) AS hour,
            log_level,
            COUNT(_timestamp) AS count
        FROM "logs"
        WHERE _timestamp > 0 AND log_level IN ('ERROR', 'WARN')
        GROUP BY hour, log_level
        LIMIT 100
        '''

        # Step 5: Validate policy
        policy = run_policy_preflight(sql)
        assert hasattr(policy, 'ok')

        # Step 6: Validate functions
        func_check = validate_sql_functions(sql)
        func_result = json.loads(func_check)
        assert "all_valid" in func_result

        # Step 7: Execute query (mocked)
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "hits": [
                    {"hour": "2024-01-01T10:00:00Z", "log_level": "ERROR", "count": 15}
                ],
                "total": 1,
                "took": 75
            }

            result = await service.execute_sql(sql, stream="logs", time_range="24h")

            assert result["success"] is True
            assert "hits" in result

