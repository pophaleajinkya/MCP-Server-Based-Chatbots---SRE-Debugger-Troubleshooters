"""Unit tests for src/models/query.py"""
import pytest
from pydantic import ValidationError
from src.models.query import QueryRequest, ToolPayload, ToolResult, QueryResponse


class TestQueryRequest:
    """Tests for QueryRequest model."""

    def test_create_valid_request(self):
        """Test creating a valid QueryRequest."""
        request = QueryRequest(
            session_id="test-session-123",
            query="get dependencies for payment-service in production"
        )
        assert request.session_id == "test-session-123"
        assert request.query == "get dependencies for payment-service in production"

    def test_required_session_id(self):
        """Test that session_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query="test query")
        assert "session_id" in str(exc_info.value)

    def test_required_query(self):
        """Test that query is required."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(session_id="test-123")
        assert "query" in str(exc_info.value)

    def test_model_serialization(self):
        """Test model serialization."""
        request = QueryRequest(
            session_id="session-456",
            query="test"
        )
        model_dict = request.model_dump()
        assert model_dict["session_id"] == "session-456"
        assert model_dict["query"] == "test"


class TestToolPayload:
    """Tests for ToolPayload model."""

    def test_create_tool_payload_minimal(self):
        """Test creating ToolPayload with minimal fields."""
        payload = ToolPayload(toolName="get_app_dependencies")
        assert payload.tool_name == "get_app_dependencies"
        assert payload.app_name is None
        assert payload.namespace is None
        assert payload.parameters == {}

    def test_create_tool_payload_full(self):
        """Test creating ToolPayload with all fields."""
        payload = ToolPayload(
            toolName="get_app_dependencies",
            appName="payment-service",
            namespace="production",
            parameters={"direction": "upstream"}
        )
        assert payload.tool_name == "get_app_dependencies"
        assert payload.app_name == "payment-service"
        assert payload.namespace == "production"
        assert payload.parameters == {"direction": "upstream"}

    def test_tool_name_alias(self):
        """Test that toolName alias works."""
        payload = ToolPayload(tool_name="test_tool")
        model_dict = payload.model_dump(by_alias=True)
        assert model_dict["toolName"] == "test_tool"

    def test_app_name_alias(self):
        """Test that appName alias works."""
        payload = ToolPayload(toolName="test", app_name="my-app")
        model_dict = payload.model_dump(by_alias=True)
        assert model_dict["appName"] == "my-app"

    def test_parameters_default_factory(self):
        """Test that parameters defaults to empty dict."""
        payload = ToolPayload(toolName="test")
        assert payload.parameters == {}
        assert isinstance(payload.parameters, dict)


class TestToolResult:
    """Tests for ToolResult model."""

    def test_create_success_result(self):
        """Test creating a successful ToolResult."""
        result = ToolResult(
            toolName="get_app_dependencies",
            success=True,
            data={"dependencies": []},
            error=None,
            executionTimeMs=150.5
        )
        assert result.tool_name == "get_app_dependencies"
        assert result.success is True
        assert result.data == {"dependencies": []}
        assert result.error is None
        assert result.execution_time_ms == 150.5

    def test_create_error_result(self):
        """Test creating an error ToolResult."""
        result = ToolResult(
            toolName="get_app_dependencies",
            success=False,
            data=None,
            error="Connection timeout",
            executionTimeMs=5000.0
        )
        assert result.success is False
        assert result.error == "Connection timeout"

    def test_required_fields(self):
        """Test that tool_name and success are required."""
        with pytest.raises(ValidationError):
            ToolResult()

    def test_execution_time_alias(self):
        """Test executionTimeMs alias."""
        result = ToolResult(
            tool_name="test",
            success=True,
            execution_time_ms=100.0
        )
        model_dict = result.model_dump(by_alias=True)
        assert model_dict["executionTimeMs"] == 100.0

    def test_optional_fields_default_to_none(self):
        """Test that optional fields default to None."""
        result = ToolResult(toolName="test", success=True)
        assert result.data is None
        assert result.error is None
        assert result.execution_time_ms is None


class TestQueryResponse:
    """Tests for QueryResponse model."""

    def test_create_full_response(self):
        """Test creating a full QueryResponse."""
        payload = ToolPayload(
            toolName="get_app_dependencies",
            appName="my-app",
            namespace="prod"
        )
        tool_result = ToolResult(
            toolName="get_app_dependencies",
            success=True,
            data={"dependencies": []},
            executionTimeMs=100.0
        )
        response = QueryResponse(
            sessionId="session-123",
            query="test query",
            extractedPayload=payload,
            toolResults=[tool_result],
            success=True
        )
        assert response.session_id == "session-123"
        assert response.query == "test query"
        assert response.extracted_payload.tool_name == "get_app_dependencies"
        assert len(response.tool_results) == 1
        assert response.success is True

    def test_session_id_alias(self):
        """Test sessionId alias."""
        payload = ToolPayload(toolName="test")
        response = QueryResponse(
            session_id="test-session",
            query="test",
            extracted_payload=payload,
            tool_results=[],
            success=True
        )
        model_dict = response.model_dump(by_alias=True)
        assert model_dict["sessionId"] == "test-session"

    def test_multiple_tool_results(self):
        """Test response with multiple tool results."""
        payload = ToolPayload(toolName="test")
        results = [
            ToolResult(toolName="tool1", success=True),
            ToolResult(toolName="tool2", success=True),
            ToolResult(toolName="tool3", success=False, error="failed")
        ]
        response = QueryResponse(
            sessionId="session-789",
            query="multi-tool query",
            extractedPayload=payload,
            toolResults=results,
            success=False
        )
        assert len(response.tool_results) == 3

    def test_extracted_payload_alias(self):
        """Test extractedPayload alias."""
        payload = ToolPayload(toolName="test")
        response = QueryResponse(
            sessionId="test",
            query="test",
            extractedPayload=payload,
            toolResults=[],
            success=True
        )
        model_dict = response.model_dump(by_alias=True)
        assert "extractedPayload" in model_dict
