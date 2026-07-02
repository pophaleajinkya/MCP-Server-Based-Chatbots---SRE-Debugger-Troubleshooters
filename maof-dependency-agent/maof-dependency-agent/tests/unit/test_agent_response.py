"""Unit tests for src/models/agent_response.py"""
import pytest
from pydantic import ValidationError
from src.models.agent_response import AgentResponse


class TestAgentResponse:
    """Tests for AgentResponse model."""

    def test_create_success_response(self):
        """Test creating a successful AgentResponse."""
        response = AgentResponse(
            status="success",
            query="get dependencies for my-app in production",
            data={"dependencies": [{"name": "dep1"}]},
            error=None
        )
        assert response.status == "success"
        assert response.query == "get dependencies for my-app in production"
        assert response.data == {"dependencies": [{"name": "dep1"}]}
        assert response.error is None

    def test_create_error_response(self):
        """Test creating an error AgentResponse."""
        response = AgentResponse(
            status="error",
            query="invalid query",
            data=None,
            error="Failed to parse query"
        )
        assert response.status == "error"
        assert response.query == "invalid query"
        assert response.data is None
        assert response.error == "Failed to parse query"

    def test_required_fields_missing_status(self):
        """Test that status field is required."""
        with pytest.raises(ValidationError) as exc_info:
            AgentResponse(query="test query")
        assert "status" in str(exc_info.value)

    def test_required_fields_missing_query(self):
        """Test that query field is required."""
        with pytest.raises(ValidationError) as exc_info:
            AgentResponse(status="success")
        assert "query" in str(exc_info.value)

    def test_optional_fields_default_to_none(self):
        """Test that optional fields default to None."""
        response = AgentResponse(
            status="success",
            query="test"
        )
        assert response.data is None
        assert response.error is None

    def test_model_serialization(self):
        """Test model serialization to dict."""
        response = AgentResponse(
            status="success",
            query="test query",
            data={"key": "value"},
            error=None
        )
        model_dict = response.model_dump()
        assert model_dict["status"] == "success"
        assert model_dict["query"] == "test query"
        assert model_dict["data"] == {"key": "value"}
        assert model_dict["error"] is None

    def test_model_json_serialization(self):
        """Test model JSON serialization."""
        response = AgentResponse(
            status="success",
            query="test query",
            data={"dependencies": []},
            error=None
        )
        json_str = response.model_dump_json()
        assert "success" in json_str
        assert "test query" in json_str

    def test_complex_data_payload(self):
        """Test with complex nested data payload."""
        complex_data = {
            "dependencies": [
                {
                    "name": "payment-service",
                    "namespace": "payments-prod",
                    "direction": "upstream",
                    "tier": "Tier 1"
                },
                {
                    "name": "user-api",
                    "namespace": "users-prod",
                    "direction": "downstream",
                    "tier": "Tier 2"
                }
            ],
            "totalCount": 2,
            "sourceBreakdown": {
                "upstream_count": 1,
                "downstream_count": 1,
                "total": 2
            }
        }
        response = AgentResponse(
            status="success",
            query="get all dependencies",
            data=complex_data,
            error=None
        )
        assert response.data["totalCount"] == 2
        assert len(response.data["dependencies"]) == 2

    def test_empty_data_dict(self):
        """Test with empty data dictionary."""
        response = AgentResponse(
            status="success",
            query="test",
            data={},
            error=None
        )
        assert response.data == {}

    def test_populate_by_name_config(self):
        """Test that populate_by_name is enabled in model config."""
        assert AgentResponse.model_config.get("populate_by_name") is True
