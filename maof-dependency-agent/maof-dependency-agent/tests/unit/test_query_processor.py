"""Unit tests for src/services/query_processor.py"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import time

from src.services.query_processor import QueryProcessor
from src.models.query import ToolPayload, ToolResult


class TestQueryProcessor:
    """Tests for QueryProcessor class."""

    @pytest.mark.asyncio
    async def test_process_query_success(self):
        """Test successful query processing."""
        mock_agent_result = {
            "app_name": "payment-service",
            "namespace": "production",
            "dependencies": [{"name": "dep1"}],
            "upstream_dependencies": [{"name": "up1"}],
            "downstream_dependencies": [],
            "total_count": 1,
            "source_breakdown": {"upstream_count": 1},
            "available_apps": None,
            "messages": ["Found 1 dependency"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.query_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await QueryProcessor.process_query(
                "get deps for payment-service in production",
                "session-123",
                []
            )
            
            assert isinstance(payload, ToolPayload)
            assert payload.tool_name == "get_app_dependencies"
            assert payload.app_name == "payment-service"
            assert payload.namespace == "production"
            
            assert len(tool_results) == 1
            assert tool_results[0].success is True
            assert tool_results[0].data["appName"] == "payment-service"
            assert tool_results[0].data["dependencies"] == [{"name": "dep1"}]

    @pytest.mark.asyncio
    async def test_process_query_failure(self):
        """Test failed query processing."""
        mock_agent_result = {
            "app_name": None,
            "namespace": None,
            "dependencies": [],
            "error": "Could not extract parameters",
            "success": False,
        }
        
        with patch("src.services.query_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await QueryProcessor.process_query(
                "invalid query",
                "session-456",
                []
            )
            
            assert tool_results[0].success is False
            assert tool_results[0].error == "Could not extract parameters"
            assert tool_results[0].data is None

    @pytest.mark.asyncio
    async def test_process_query_exception(self):
        """Test query processing when exception is raised."""
        with patch("src.services.query_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(side_effect=Exception("Unexpected error"))
            
            payload, tool_results = await QueryProcessor.process_query(
                "test query",
                "session-error",
                []
            )
            
            assert payload.tool_name == "get_app_dependencies"
            assert payload.app_name is None
            assert len(tool_results) == 1
            assert tool_results[0].success is False
            assert "Unexpected error" in tool_results[0].error

    @pytest.mark.asyncio
    async def test_process_query_with_conversation_history(self):
        """Test query processing with conversation history."""
        mock_agent_result = {
            "app_name": "my-app",
            "namespace": "prod",
            "dependencies": [],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": [],
            "available_apps": None,
            "upstream_dependencies": None,
            "downstream_dependencies": None,
        }
        
        conversation_history = [
            {"role": "user", "content": "get apps in prod"},
            {"role": "assistant", "content": "Found 10 apps"},
        ]
        
        with patch("src.services.query_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            await QueryProcessor.process_query(
                "get deps for my-app",
                "session-789",
                conversation_history
            )
            
            # Verify conversation history was passed
            mock_agent.process_query.assert_called_once_with(
                "get deps for my-app",
                "session-789",
                query_type="wcnp",
                conversation_history=conversation_history
            )

    @pytest.mark.asyncio
    async def test_process_query_execution_time_tracked(self):
        """Test that execution time is tracked."""
        mock_agent_result = {
            "app_name": "app",
            "namespace": "ns",
            "dependencies": [],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": [],
            "available_apps": None,
            "upstream_dependencies": None,
            "downstream_dependencies": None,
        }
        
        with patch("src.services.query_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            _, tool_results = await QueryProcessor.process_query(
                "test",
                "session",
                None
            )
            
            assert tool_results[0].execution_time_ms is not None
            assert tool_results[0].execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_process_query_with_available_apps(self):
        """Test query processing with available apps returned."""
        mock_agent_result = {
            "app_name": None,
            "namespace": "prod",
            "dependencies": [],
            "available_apps": ["app1", "app2", "app3"],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": ["Found 3 apps"],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
        }
        
        with patch("src.services.query_processor.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await QueryProcessor.process_query(
                "get apps in prod",
                "session",
                None
            )
            
            assert payload.namespace == "prod"
            assert tool_results[0].data["available_apps"] == ["app1", "app2", "app3"]
