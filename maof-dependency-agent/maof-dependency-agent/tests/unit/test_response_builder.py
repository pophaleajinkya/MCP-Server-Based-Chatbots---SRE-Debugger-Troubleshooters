"""Unit tests for src/services/response_builder.py"""
import pytest
from unittest.mock import MagicMock

from src.services.response_builder import create_error_response, build_data_payload
from src.models.query import QueryRequest, ToolResult
from src.models.agent_response import AgentResponse


class TestCreateErrorResponse:
    """Tests for create_error_response function."""

    def test_create_error_response(self):
        """Test creating an error response."""
        request = QueryRequest(
            session_id="session-123",
            query="invalid query"
        )
        error_msg = "Failed to parse query parameters"
        
        response = create_error_response(request, error_msg)
        
        assert isinstance(response, AgentResponse)
        assert response.status == "error"
        assert response.query == "invalid query"
        assert response.data is None
        assert response.error == "Failed to parse query parameters"

    def test_create_error_response_empty_error(self):
        """Test creating an error response with empty error message."""
        request = QueryRequest(
            session_id="session-456",
            query="test query"
        )
        
        response = create_error_response(request, "")
        
        assert response.status == "error"
        assert response.error == ""

    def test_create_error_response_long_error_message(self):
        """Test creating an error response with long error message."""
        request = QueryRequest(
            session_id="session-789",
            query="query"
        )
        long_error = "Error: " + "x" * 1000
        
        response = create_error_response(request, long_error)
        
        assert len(response.error) > 1000


class TestBuildDataPayload:
    """Tests for build_data_payload function."""

    def test_build_payload_not_success(self):
        """Test that failed request returns None."""
        result = build_data_payload(False, [])
        assert result is None

    def test_build_payload_no_tool_results(self):
        """Test that empty tool results returns None."""
        result = build_data_payload(True, [])
        assert result is None

    def test_build_payload_with_dependencies(self):
        """Test building payload with dependencies."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [
                {"name": "dep1", "direction": "upstream"},
                {"name": "dep2", "direction": "downstream"},
            ],
            "total_count": 2,
            "sourceBreakdown": {"upstream_count": 1, "downstream_count": 1}
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert result is not None
        assert "dependencies" in result
        assert len(result["dependencies"]) == 2
        assert result["totalCount"] == 2
        assert result["sourceBreakdown"] == {"upstream_count": 1, "downstream_count": 1}

    def test_build_payload_empty_dependencies(self):
        """Test building payload with empty dependencies list."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [],
            "sourceBreakdown": {}
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert result is not None
        assert result["dependencies"] == []
        assert result["totalCount"] == 0

    def test_build_payload_with_none_dependencies(self):
        """Test building payload when dependencies is None."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": None,
            "sourceBreakdown": None
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert result is not None
        assert result["dependencies"] == []
        assert result["sourceBreakdown"] == {}

    def test_build_payload_with_upstream_dependencies(self):
        """Test building payload with upstream_dependencies key."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [{"name": "dep"}],
            "upstream_dependencies": [{"name": "up-dep"}],
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert "upstreamDependencies" in result
        assert result["upstreamDependencies"] == [{"name": "up-dep"}]

    def test_build_payload_with_downstream_dependencies(self):
        """Test building payload with downstream_dependencies key."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [{"name": "dep"}],
            "downstream_dependencies": [{"name": "down-dep"}],
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert "downstreamDependencies" in result
        assert result["downstreamDependencies"] == [{"name": "down-dep"}]

    def test_build_payload_with_direction(self):
        """Test building payload with direction field."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [],
            "direction": "upstream"
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert "direction" in result
        assert result["direction"] == "upstream"

    def test_build_payload_with_available_apps(self):
        """Test building payload with available_apps."""
        tool_result = MagicMock()
        tool_result.data = {
            "available_apps": ["app1", "app2", "app3"]
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert "availableApps" in result
        assert result["availableApps"] == ["app1", "app2", "app3"]
        assert result["totalApps"] == 3

    def test_build_payload_empty_available_apps(self):
        """Test that empty available_apps is not included."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [{"name": "dep"}],
            "available_apps": []
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert "availableApps" not in result

    def test_build_payload_with_app_and_namespace(self):
        """Test building payload with appName and namespace."""
        tool_result = MagicMock()
        tool_result.data = {
            "dependencies": [],
            "appName": "my-app",
            "namespace": "production"
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert result["appName"] == "my-app"
        assert result["namespace"] == "production"

    def test_build_payload_no_relevant_data(self):
        """Test building payload with no relevant keys returns None."""
        tool_result = MagicMock()
        tool_result.data = {
            "some_other_key": "value"
        }
        
        result = build_data_payload(True, [tool_result])
        
        assert result is None

    def test_build_payload_none_data(self):
        """Test building payload when data is None."""
        tool_result = MagicMock()
        tool_result.data = None
        
        result = build_data_payload(True, [tool_result])
        
        assert result is None

    def test_build_payload_uses_first_tool_result(self):
        """Test that only first tool result is used."""
        tool_result1 = MagicMock()
        tool_result1.data = {"dependencies": [{"name": "from-first"}]}
        
        tool_result2 = MagicMock()
        tool_result2.data = {"dependencies": [{"name": "from-second"}]}
        
        result = build_data_payload(True, [tool_result1, tool_result2])
        
        assert result["dependencies"][0]["name"] == "from-first"
