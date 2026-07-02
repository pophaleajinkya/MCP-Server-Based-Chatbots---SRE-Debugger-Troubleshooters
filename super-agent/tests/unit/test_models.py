"""Unit tests for app.models — Pydantic schemas."""

import pytest
from pydantic import ValidationError


# ── schemas.py ────────────────────────────────────────────────────────────────

class TestQueryRequest:
    """Test QueryRequest validation."""

    def test_valid_query(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(query="Check health of namespace intl-sre", session_id="sess-1")
        assert req.query == "Check health of namespace intl-sre"
        assert req.session_id == "sess-1"

    def test_query_with_session_id(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(query="test", session_id="abc-123")
        assert req.session_id == "abc-123"

    def test_empty_query_rejected(self):
        from app.models.schemas import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(query="")

    def test_query_too_long_rejected(self):
        from app.models.schemas import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(query="x" * 4097)

    def test_query_max_length_accepted(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(query="x" * 4096, session_id="s")
        assert len(req.query) == 4096

    def test_query_min_length_one_char(self):
        from app.models.schemas import QueryRequest
        req = QueryRequest(query="?", session_id="s")
        assert req.query == "?"

    def test_model_config_example(self):
        from app.models.schemas import QueryRequest
        schema = QueryRequest.model_json_schema()
        assert "query" in str(schema)

    def test_session_id_auto_generated_when_omitted(self):
        """session_id is optional — a UUID is auto-generated when omitted."""
        import uuid
        from app.models.schemas import QueryRequest
        req = QueryRequest(query="test query")  # session_id intentionally omitted
        # A valid UUID4 string must be present (format: 8-4-4-4-12 hex chars)
        assert req.session_id is not None
        assert len(req.session_id) == 36
        # Verify it parses as a valid UUID
        parsed = uuid.UUID(req.session_id)
        assert str(parsed) == req.session_id

    def test_session_id_custom_string(self):
        from app.models.schemas import QueryRequest
        sid = "my-custom-session-id-12345"
        req = QueryRequest(query="test", session_id=sid)
        assert req.session_id == sid


class TestQueryResponse:
    """Test QueryResponse serialisation."""

    def test_valid_response(self):
        from app.models.schemas import QueryResponse
        resp = QueryResponse(response="All pods healthy", session_id="sess-1")
        assert resp.response == "All pods healthy"
        assert resp.session_id == "sess-1"

    def test_response_serialisation(self):
        from app.models.schemas import QueryResponse
        resp = QueryResponse(response="ok", session_id="s1")
        data = resp.model_dump()
        assert data == {"response": "ok", "session_id": "s1"}

    def test_response_required_fields(self):
        from app.models.schemas import QueryResponse
        with pytest.raises(ValidationError):
            QueryResponse(response="ok")  # missing session_id

    def test_response_empty_string_accepted(self):
        from app.models.schemas import QueryResponse
        # Empty response string is valid (agent may return empty)
        resp = QueryResponse(response="", session_id="s1")
        assert resp.response == ""

    def test_response_has_three_fields(self):
        """QueryResponse schema must expose response and session_id."""
        from app.models.schemas import QueryResponse
        resp = QueryResponse(response="ok", session_id="s1")
        data = resp.model_dump()
        assert set(data.keys()) == {"response", "session_id"}


class TestMCPServerInfo:
    """Test MCPServerInfo model."""

    def test_mcp_server_info(self):
        from app.models.schemas import MCPServerInfo
        info = MCPServerInfo(name="test-mcp", url="http://localhost:9000/mcp")
        assert info.name == "test-mcp"
        assert info.url == "http://localhost:9000/mcp"

    def test_mcp_server_info_serialisation(self):
        from app.models.schemas import MCPServerInfo
        info = MCPServerInfo(name="svc", url="http://svc:8999/mcp")
        data = info.model_dump()
        assert data == {"name": "svc", "url": "http://svc:8999/mcp"}

    def test_mcp_server_info_required_fields(self):
        from app.models.schemas import MCPServerInfo
        with pytest.raises(ValidationError):
            MCPServerInfo(name="only-name")  # missing url


class TestHealthResponse:
    """Test HealthResponse model."""

    def test_health_response_full(self):
        from app.models.schemas import HealthResponse, MCPServerInfo
        resp = HealthResponse(
            status="ok",
            version="2.0.0",
            active_llm="openai",
            llm_endpoint="https://llm.test.com",
            mcp_servers=[MCPServerInfo(name="s1", url="http://s1")],
            mcp_tools=["check_health", "get_metrics"],
        )
        assert resp.status == "ok"
        assert resp.version == "2.0.0"
        assert resp.active_llm == "openai"
        assert len(resp.mcp_servers) == 1
        assert len(resp.mcp_tools) == 2

    def test_health_response_no_servers(self):
        from app.models.schemas import HealthResponse
        resp = HealthResponse(
            status="ok",
            version="2.0.0",
            active_llm="claude",
            llm_endpoint="https://claude.test.com",
            mcp_servers=[],
            mcp_tools=[],
        )
        assert resp.mcp_servers == []
        assert resp.mcp_tools == []

    def test_health_response_serialisation(self):
        from app.models.schemas import HealthResponse, MCPServerInfo
        resp = HealthResponse(
            status="ok",
            version="1.0",
            active_llm="openai",
            llm_endpoint="https://ep.test",
            mcp_servers=[MCPServerInfo(name="s1", url="http://s1")],
            mcp_tools=["tool_a"],
        )
        data = resp.model_dump()
        assert data["status"] == "ok"
        assert data["mcp_tools"] == ["tool_a"]

