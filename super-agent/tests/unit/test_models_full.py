"""
Comprehensive unit tests for app.models.schemas — all Pydantic models.
Covers validation, defaults, edge cases, serialization, and boundary values.
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.models.schemas import (
    HealthResponse,
    MCPServerInfo,
    QueryRequest,
    QueryResponse,
)


class TestQueryRequest:

    def test_minimal_valid(self):
        r = QueryRequest(query="test query")
        assert r.query == "test query"

    def test_auto_generates_session_id(self):
        r = QueryRequest(query="hello")
        assert r.session_id is not None
        # Should be a valid UUID
        uuid.UUID(r.session_id)

    def test_custom_session_id(self):
        r = QueryRequest(query="q", session_id="my-session")
        assert r.session_id == "my-session"

    def test_user_id_optional(self):
        r = QueryRequest(query="q")
        assert r.user_id is None

    def test_user_id_provided(self):
        r = QueryRequest(query="q", user_id="alice@walmart.com")
        assert r.user_id == "alice@walmart.com"

    def test_query_min_length(self):
        """Query must be at least 1 character."""
        with pytest.raises(Exception):  # ValidationError
            QueryRequest(query="")

    def test_query_whitespace_only(self):
        """Whitespace-only queries should be valid (1+ chars)."""
        r = QueryRequest(query=" ")
        assert r.query == " "

    def test_unicode_query(self):
        r = QueryRequest(query="Hola, mundo! 你好世界")
        assert "你好世界" in r.query

    def test_multiline_query(self):
        r = QueryRequest(query="line 1\nline 2\nline 3")
        assert "\n" in r.query

    def test_json_roundtrip(self):
        r = QueryRequest(query="test", session_id="s1", user_id="u1")
        data = r.model_dump()
        r2 = QueryRequest(**data)
        assert r2.query == r.query
        assert r2.session_id == r.session_id
        assert r2.user_id == r.user_id


class TestQueryResponse:

    def test_minimal(self):
        r = QueryResponse(response="answer", session_id="s1")
        assert r.response == "answer"
        assert r.session_id == "s1"

    def test_empty_response_allowed(self):
        r = QueryResponse(response="", session_id="s")
        assert r.response == ""

    def test_json_serialization(self):
        r = QueryResponse(response="hello", session_id="s1")
        data = r.model_dump()
        assert data["response"] == "hello"
        assert data["session_id"] == "s1"


class TestMCPServerInfo:

    def test_construction(self):
        info = MCPServerInfo(name="health-mcp", url="http://localhost:8999/mcp/")
        assert info.name == "health-mcp"
        assert info.url == "http://localhost:8999/mcp/"

    def test_serialization(self):
        info = MCPServerInfo(name="test", url="http://test")
        data = info.model_dump()
        assert isinstance(data, dict)
        assert "name" in data
        assert "url" in data


class TestHealthResponse:

    def test_full_construction(self):
        r = HealthResponse(
            status="ok",
            version="2.0.0",
            active_llm="claude",
            llm_endpoint="https://gateway.example.com",
            mcp_servers=[MCPServerInfo(name="a", url="http://a")],
            mcp_tools=["tool_1", "tool_2"],
        )
        assert r.status == "ok"
        assert r.version == "2.0.0"
        assert len(r.mcp_servers) == 1
        assert len(r.mcp_tools) == 2

    def test_empty_servers_and_tools(self):
        r = HealthResponse(
            status="ok",
            version="1.0",
            active_llm="openai",
            llm_endpoint="",
            mcp_servers=[],
            mcp_tools=[],
        )
        assert r.mcp_servers == []
        assert r.mcp_tools == []

    def test_serialization(self):
        r = HealthResponse(
            status="ok",
            version="1.0",
            active_llm="claude",
            llm_endpoint="http://test",
            mcp_servers=[],
            mcp_tools=["t1"],
        )
        data = r.model_dump()
        assert data["status"] == "ok"
        assert isinstance(data["mcp_tools"], list)

    def test_json_dumps(self):
        r = HealthResponse(
            status="ok",
            version="1.0",
            active_llm="claude",
            llm_endpoint="",
            mcp_servers=[MCPServerInfo(name="x", url="http://x")],
            mcp_tools=[],
        )
        j = r.model_dump_json()
        parsed = json.loads(j)
        assert parsed["status"] == "ok"
        assert len(parsed["mcp_servers"]) == 1

    def test_multiple_mcp_servers(self):
        servers = [
            MCPServerInfo(name="health", url="http://health"),
            MCPServerInfo(name="dep", url="http://dep"),
            MCPServerInfo(name="incident", url="http://incident"),
        ]
        r = HealthResponse(
            status="ok", version="2.0", active_llm="claude",
            llm_endpoint="", mcp_servers=servers, mcp_tools=["a", "b", "c"],
        )
        assert len(r.mcp_servers) == 3
