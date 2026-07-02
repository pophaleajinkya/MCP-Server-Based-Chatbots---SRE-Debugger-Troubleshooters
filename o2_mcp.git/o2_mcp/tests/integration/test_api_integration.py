"""API integration tests.

Tests for API endpoint interactions and data flow.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestSQLExecutionAPI:
    """Integration tests for SQL execution API."""
    
    @pytest.mark.asyncio
    async def test_execute_sql_api_flow(self):
        """Test complete SQL execution API flow."""
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
                    {"_timestamp": 1000, "status": 200, "count": 5}
                ],
                "total": 1
            }
            
            result = await service.execute_sql(
                sql='SELECT status, COUNT(*) as count FROM "logs" GROUP BY status',
                stream="logs",
                time_range="1h"
            )
            
            assert result["success"] is True
            assert len(result["hits"]) == 1
            assert result["hits"][0]["status"] == 200


class TestStreamAPI:
    """Integration tests for stream API."""
    
    @pytest.mark.asyncio
    async def test_list_streams_api(self):
        """Test list streams API."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        with patch.object(client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "list": [
                    {"name": "logs"},
                    {"name": "metrics"}
                ]
            }
            
            result = await service.list_streams()
            
            assert result["success"] is True
            assert result["total"] == 2
    
    @pytest.mark.asyncio
    async def test_get_stream_schema_api(self):
        """Test get stream schema API."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        with patch.object(client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "name": "logs",
                "schema": [
                    {"name": "_timestamp", "type": "Int64"},
                    {"name": "message", "type": "Utf8"}
                ],
                "settings": {}
            }
            
            result = await service.get_stream_schema("logs")
            
            assert result["name"] == "logs"
            assert "fields" in result
            assert len(result["fields"]) == 2


class TestFieldValuesAPI:
    """Integration tests for field values API."""
    
    @pytest.mark.asyncio
    async def test_get_field_values_api(self):
        """Test get field values API."""
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
                    {"value": "200", "count": 100},
                    {"value": "404", "count": 20}
                ]
            }
            
            result = await service.get_field_values(
                stream="logs",
                fields=["status"],
                time_range="1h"
            )
            
            assert result["success"] is True
            assert "fields" in result


class TestErrorHandlingAPI:
    """Integration tests for error handling in API."""
    
    @pytest.mark.asyncio
    async def test_api_error_handling(self):
        """Test API error handling."""
        from src.http_client import O2HttpClient, O2ApiError
        from src.services.query_service import QueryService
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = O2ApiError(403, "Forbidden")
            
            result = await service.execute_sql('SELECT * FROM "logs"')
            
            assert result["success"] is False
            assert "error" in result
    
    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test connection error handling."""
        from src.http_client import O2HttpClient, O2ConnectionError
        from src.services.query_service import QueryService
        import httpx
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = O2ConnectionError("Connection timeout")
            
            result = await service.execute_sql('SELECT * FROM "logs"')
            
            assert result["success"] is False
            assert "error" in result


class TestDataFlowAPI:
    """Integration tests for data flow through API layers."""
    
    @pytest.mark.asyncio
    async def test_data_transformation_flow(self):
        """Test data transformation through API layers."""
        from src.http_client import O2HttpClient
        from src.services.query_service import QueryService
        
        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="test_token"
        )
        service = QueryService(client=client)
        
        with patch.object(client, 'post', new_callable=AsyncMock) as mock_post:
            raw_response = {
                "hits": [
                    {"_timestamp": 1704067200000000, "level": "ERROR", "msg": "Test error"}
                ],
                "total": 1,
                "took": 25
            }
            mock_post.return_value = raw_response
            
            result = await service.execute_sql(
                sql='SELECT * FROM "logs" WHERE level = \'ERROR\'',
                stream="logs"
            )
            
            # Service should wrap response
            assert result["success"] is True
            assert result["hits"] == raw_response["hits"]
            assert result["total"] == 1


class TestTimeRangeAPI:
    """Integration tests for time range handling."""
    
    @pytest.mark.asyncio
    async def test_time_range_conversion(self):
        """Test time range conversion in API."""
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
                time_range="2h"
            )
            
            # Verify post was called (time range should be converted)
            assert mock_post.called
            call_kwargs = mock_post.call_args[1]
            # Time range should be in the request
            assert "json" in call_kwargs

