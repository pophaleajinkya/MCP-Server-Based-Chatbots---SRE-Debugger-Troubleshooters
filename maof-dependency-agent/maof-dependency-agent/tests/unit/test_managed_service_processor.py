"""Unit tests for src/services/managed_service_processor.py"""
import pytest
from unittest.mock import AsyncMock, patch

from src.services.managed_service_processor import ManagedServiceQueryProcessor
from src.models.query import ToolPayload, ToolResult


class TestManagedServiceQueryProcessor:
    """Tests for ManagedServiceQueryProcessor class."""

    @pytest.mark.asyncio
    async def test_process_query_cassandra_success(self):
        """Test successful Cassandra managed service query."""
        mock_agent_result = {
            "service_type": "cassandra",
            "assembly": "mx-rms",
            "platform": "rmsag2",
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "dependencies": [{"name": "cassandra-dep"}],
            "total_count": 1,
            "source_breakdown": {"upstream_count": 1},
            "messages": ["Found 1 upstream dependency for cassandra"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await ManagedServiceQueryProcessor.process_query(
                "cassandra deps assembly=mx-rms platform=rmsag2",
                "session-123",
                []
            )
            
            assert payload.tool_name == "get_managed_service_dependencies"
            assert payload.app_name == "cassandra"  # service_type
            assert payload.namespace == "mx-rms"  # assembly
            assert payload.parameters["serviceType"] == "cassandra"
            
            assert tool_results[0].success is True
            assert tool_results[0].data["serviceType"] == "cassandra"

    @pytest.mark.asyncio
    async def test_process_query_cosmos_success(self):
        """Test successful Cosmos managed service query."""
        mock_agent_result = {
            "service_type": "cosmos",
            "assembly": None,
            "platform": None,
            "resource_group": "my-rg",
            "subscription_id": "sub-123",
            "database_name": "orders-db",
            "dependencies": [{"name": "cosmos-dep"}],
            "total_count": 1,
            "source_breakdown": {"upstream_count": 1},
            "messages": ["Found 1 upstream dependency for cosmos"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await ManagedServiceQueryProcessor.process_query(
                "cosmos deps resourceGroup=my-rg subscriptionId=sub-123 databaseName=orders-db",
                "session-456",
                []
            )
            
            assert payload.namespace == "my-rg"  # resource_group
            assert payload.parameters["resourceGroup"] == "my-rg"
            assert payload.parameters["subscriptionId"] == "sub-123"
            assert payload.parameters["databaseName"] == "orders-db"
            
            assert tool_results[0].data["resourceGroup"] == "my-rg"

    @pytest.mark.asyncio
    async def test_process_query_failure_missing_params(self):
        """Test failed managed service query with missing parameters."""
        mock_agent_result = {
            "service_type": "cassandra",
            "assembly": None,
            "platform": None,
            "error": "Missing required parameters: assembly, platform",
            "success": False,
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await ManagedServiceQueryProcessor.process_query(
                "cassandra deps",
                "session-789",
                []
            )
            
            assert tool_results[0].success is False
            assert "Missing required parameters" in tool_results[0].error

    @pytest.mark.asyncio
    async def test_process_query_exception(self):
        """Test managed service query when exception is raised."""
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(side_effect=Exception("Service error"))
            
            payload, tool_results = await ManagedServiceQueryProcessor.process_query(
                "test",
                "session-error",
                []
            )
            
            assert payload.tool_name == "get_managed_service_dependencies"
            assert payload.app_name is None
            assert tool_results[0].success is False
            assert "Service error" in tool_results[0].error

    @pytest.mark.asyncio
    async def test_process_query_calls_agent_with_correct_type(self):
        """Test that agent is called with query_type='managed_service'."""
        mock_agent_result = {
            "service_type": "meghacache",
            "assembly": "asm",
            "platform": "plat",
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "dependencies": [],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": [],
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            await ManagedServiceQueryProcessor.process_query(
                "meghacache deps",
                "session",
                None
            )
            
            mock_agent.process_query.assert_called_once_with(
                "meghacache deps",
                "session",
                query_type="managed_service",
                conversation_history=None
            )

    @pytest.mark.asyncio
    async def test_process_query_execution_time_tracked(self):
        """Test that execution time is tracked."""
        mock_agent_result = {
            "service_type": "sqlserver",
            "assembly": None,
            "platform": None,
            "resource_group": "rg",
            "subscription_id": "sub",
            "database_name": "db",
            "dependencies": [],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": [],
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            _, tool_results = await ManagedServiceQueryProcessor.process_query(
                "sqlserver deps",
                "session",
                None
            )
            
            assert tool_results[0].execution_time_ms is not None
            assert tool_results[0].execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_process_query_sqlserver(self):
        """Test SQL Server managed service query."""
        mock_agent_result = {
            "service_type": "sqlserver",
            "assembly": None,
            "platform": None,
            "resource_group": "prod-rg",
            "subscription_id": "abc-456",
            "database_name": "inventory-db",
            "dependencies": [{"name": "sql-dep1"}, {"name": "sql-dep2"}],
            "total_count": 2,
            "source_breakdown": {"upstream_count": 2},
            "messages": ["Found 2 dependencies"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await ManagedServiceQueryProcessor.process_query(
                "sqlserver deps resource_group prod-rg subscription abc-456 database inventory-db",
                "session",
                []
            )
            
            assert payload.parameters["serviceType"] == "sqlserver"
            assert tool_results[0].data["totalCount"] == 2

    @pytest.mark.asyncio
    async def test_process_query_meghacache(self):
        """Test MeghaCache managed service query."""
        mock_agent_result = {
            "service_type": "meghacache",
            "assembly": "payments-prod",
            "platform": "pay-platform",
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "dependencies": [],
            "total_count": 0,
            "source_breakdown": {},
            "messages": ["No dependencies found"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.managed_service_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await ManagedServiceQueryProcessor.process_query(
                "meghacache deps assembly payments-prod platform pay-platform",
                "session",
                []
            )
            
            assert payload.parameters["serviceType"] == "meghacache"
            assert tool_results[0].success is True
