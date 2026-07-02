"""Unit tests for src/services/oneops_service.py (OneOpsQueryProcessor)"""
import pytest
from unittest.mock import AsyncMock, patch

from src.services.oneops_service import OneOpsQueryProcessor
from src.models.query import ToolPayload, ToolResult


class TestOneOpsQueryProcessor:
    """Tests for OneOpsQueryProcessor class."""

    @pytest.mark.asyncio
    async def test_process_query_success(self):
        """Test successful OneOps query processing."""
        mock_agent_result = {
            "org": "mexicoecomm",
            "platform": "rmsag2",
            "assembly": "mx-rms",
            "direction": "upstream",
            "dependencies": [{"name": "dep1", "direction": "upstream"}],
            "upstream_dependencies": [{"name": "dep1"}],
            "downstream_dependencies": [],
            "total_count": 1,
            "source_breakdown": {"upstream_count": 1, "downstream_count": 0},
            "messages": ["Found 1 upstream dependency"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.oneops_service.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await OneOpsQueryProcessor.process_query(
                "upstream deps for org=mexicoecomm platform=rmsag2 assembly=mx-rms",
                "session-123",
                []
            )
            
            assert isinstance(payload, ToolPayload)
            assert payload.tool_name == "get_oneops_dependencies"
            assert payload.app_name == "rmsag2"  # platform
            assert payload.namespace == "mx-rms"  # assembly
            assert payload.parameters["org"] == "mexicoecomm"
            
            assert len(tool_results) == 1
            assert tool_results[0].success is True
            assert tool_results[0].data["org"] == "mexicoecomm"
            assert tool_results[0].data["platform"] == "rmsag2"
            assert tool_results[0].data["assembly"] == "mx-rms"

    @pytest.mark.asyncio
    async def test_process_query_failure(self):
        """Test failed OneOps query processing."""
        mock_agent_result = {
            "org": None,
            "platform": None,
            "assembly": None,
            "error": "Missing OneOps parameters",
            "success": False,
        }
        
        with patch("src.services.oneops_service.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await OneOpsQueryProcessor.process_query(
                "invalid oneops query",
                "session-456",
                []
            )
            
            assert tool_results[0].success is False
            assert tool_results[0].error == "Missing OneOps parameters"

    @pytest.mark.asyncio
    async def test_process_query_exception(self):
        """Test OneOps query processing when exception is raised."""
        with patch("src.services.oneops_service.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(side_effect=Exception("Agent error"))
            
            payload, tool_results = await OneOpsQueryProcessor.process_query(
                "test query",
                "session-error",
                []
            )
            
            assert payload.tool_name == "get_oneops_dependencies"
            assert payload.app_name is None
            assert tool_results[0].success is False
            assert "Agent error" in tool_results[0].error

    @pytest.mark.asyncio
    async def test_process_query_calls_agent_with_correct_type(self):
        """Test that agent is called with query_type='oneops'."""
        mock_agent_result = {
            "org": "org",
            "platform": "plat",
            "assembly": "asm",
            "dependencies": [],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": [],
            "direction": None,
            "upstream_dependencies": None,
            "downstream_dependencies": None,
        }
        
        with patch("src.services.oneops_service.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            await OneOpsQueryProcessor.process_query(
                "test",
                "session",
                None
            )
            
            mock_agent.process_query.assert_called_once_with(
                "test",
                "session",
                query_type="oneops",
                conversation_history=None
            )

    @pytest.mark.asyncio
    async def test_process_query_execution_time_tracked(self):
        """Test that execution time is tracked."""
        mock_agent_result = {
            "org": "org",
            "platform": "plat",
            "assembly": "asm",
            "dependencies": [],
            "success": True,
            "error": None,
            "total_count": 0,
            "source_breakdown": {},
            "messages": [],
            "direction": None,
            "upstream_dependencies": None,
            "downstream_dependencies": None,
        }
        
        with patch("src.services.oneops_service.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            _, tool_results = await OneOpsQueryProcessor.process_query(
                "test",
                "session",
                None
            )
            
            assert tool_results[0].execution_time_ms is not None
            assert tool_results[0].execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_process_query_with_direction(self):
        """Test OneOps query with direction parameter."""
        mock_agent_result = {
            "org": "walmart",
            "platform": "payment",
            "assembly": "pay-prod",
            "direction": "downstream",
            "dependencies": [{"name": "dep1"}, {"name": "dep2"}],
            "upstream_dependencies": None,
            "downstream_dependencies": [{"name": "dep1"}, {"name": "dep2"}],
            "total_count": 2,
            "source_breakdown": {"downstream_count": 2},
            "messages": ["Found 2 downstream"],
            "error": None,
            "success": True,
        }
        
        with patch("src.services.oneops_service.dependency_agent") as mock_agent:
            mock_agent.process_query = AsyncMock(return_value=mock_agent_result)
            
            payload, tool_results = await OneOpsQueryProcessor.process_query(
                "downstream deps for oneops",
                "session",
                []
            )
            
            assert payload.parameters["direction"] == "downstream"
            assert tool_results[0].data["direction"] == "downstream"
