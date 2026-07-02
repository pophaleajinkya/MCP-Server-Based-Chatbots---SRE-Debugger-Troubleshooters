"""Unit tests for app.exceptions — exception hierarchy and handlers."""

import json
import pytest
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


class TestExceptionHierarchy:
    """Test the custom exception class hierarchy."""

    def test_agent_base_error(self):
        from app.exceptions import AgentBaseError
        exc = AgentBaseError("base error")
        assert str(exc) == "base error"
        assert isinstance(exc, Exception)

    def test_mcp_connection_error_is_agent_base(self):
        from app.exceptions import MCPConnectionError, AgentBaseError
        exc = MCPConnectionError("connection failed")
        assert isinstance(exc, AgentBaseError)
        assert isinstance(exc, Exception)
        assert str(exc) == "connection failed"

    def test_mcp_tool_error_is_agent_base(self):
        from app.exceptions import MCPToolError, AgentBaseError
        exc = MCPToolError("tool failed")
        assert isinstance(exc, AgentBaseError)
        assert isinstance(exc, Exception)
        assert str(exc) == "tool failed"

    def test_llm_error_attributes(self):
        from app.exceptions import LLMError, AgentBaseError
        exc = LLMError(status_code=429, detail="Rate limited")
        assert isinstance(exc, AgentBaseError)
        assert isinstance(exc, Exception)
        assert exc.status_code == 429
        assert exc.detail == "Rate limited"
        assert str(exc) == "Rate limited"

    def test_llm_error_different_codes(self):
        from app.exceptions import LLMError
        for code in (400, 401, 403, 500, 502, 503, 504):
            exc = LLMError(status_code=code, detail=f"error {code}")
            assert exc.status_code == code

    def test_agent_error_is_agent_base(self):
        from app.exceptions import AgentError, AgentBaseError
        exc = AgentError("loop crashed")
        assert isinstance(exc, AgentBaseError)
        assert isinstance(exc, Exception)
        assert str(exc) == "loop crashed"

    def test_exception_hierarchy_mcp_not_llm(self):
        """MCPConnectionError should NOT be an LLMError."""
        from app.exceptions import MCPConnectionError, LLMError
        exc = MCPConnectionError("conn fail")
        assert not isinstance(exc, LLMError)

    def test_exception_hierarchy_agent_not_llm(self):
        """AgentError should NOT be an LLMError."""
        from app.exceptions import AgentError, LLMError
        exc = AgentError("agent fail")
        assert not isinstance(exc, LLMError)

    def test_all_exceptions_can_be_raised_and_caught(self):
        """All custom exceptions should be raiseable and catchable."""
        from app.exceptions import (
            AgentBaseError, MCPConnectionError, MCPToolError,
            LLMError, AgentError
        )
        exceptions_to_test = [
            MCPConnectionError("mcp conn"),
            MCPToolError("mcp tool"),
            AgentError("agent err"),
        ]
        for exc in exceptions_to_test:
            with pytest.raises(AgentBaseError):
                raise exc

        with pytest.raises(AgentBaseError):
            raise LLMError(status_code=500, detail="llm err")


class TestExceptionHandlers:
    """Test the FastAPI exception handler functions."""

    @pytest.mark.asyncio
    async def test_llm_error_handler_returns_502(self):
        from app.exceptions import LLMError, llm_error_handler
        exc = LLMError(status_code=503, detail="Gateway timeout")
        request = MagicMock(spec=Request)
        response = await llm_error_handler(request, exc)

        assert response.status_code == 502
        body = json.loads(response.body)
        assert body["error"] == "llm_error"
        assert body["detail"] == "Gateway timeout"
        assert body["llm_status_code"] == 503

    @pytest.mark.asyncio
    async def test_llm_error_handler_various_upstream_codes(self):
        from app.exceptions import LLMError, llm_error_handler
        request = MagicMock(spec=Request)
        for code in (400, 429, 500, 503):
            exc = LLMError(status_code=code, detail=f"error {code}")
            response = await llm_error_handler(request, exc)
            assert response.status_code == 502
            body = json.loads(response.body)
            assert body["llm_status_code"] == code

    @pytest.mark.asyncio
    async def test_agent_error_handler_returns_500(self):
        from app.exceptions import AgentError, agent_error_handler
        exc = AgentError("Something went wrong")
        request = MagicMock(spec=Request)
        response = await agent_error_handler(request, exc)

        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"] == "agent_error"
        assert body["detail"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_agent_error_handler_message_preserved(self):
        from app.exceptions import AgentError, agent_error_handler
        msg = "Agentic loop hit max rounds without resolution"
        exc = AgentError(msg)
        request = MagicMock(spec=Request)
        response = await agent_error_handler(request, exc)
        body = json.loads(response.body)
        assert body["detail"] == msg

    def test_llm_error_handler_registered_in_app(self):
        """LLMError handler should produce 502 when raised in a route."""
        from app.exceptions import LLMError, llm_error_handler

        test_app = FastAPI()
        test_app.add_exception_handler(LLMError, llm_error_handler)

        @test_app.get("/fail")
        async def fail():
            raise LLMError(status_code=500, detail="upstream fail")

        test_client = TestClient(test_app, raise_server_exceptions=False)
        resp = test_client.get("/fail")
        assert resp.status_code == 502
        assert resp.json()["error"] == "llm_error"
        assert resp.json()["llm_status_code"] == 500

    def test_agent_error_handler_registered_in_app(self):
        """AgentError handler should produce 500 when raised in a route."""
        from app.exceptions import AgentError, agent_error_handler

        test_app = FastAPI()
        test_app.add_exception_handler(AgentError, agent_error_handler)

        @test_app.get("/fail")
        async def fail():
            raise AgentError("agent loop failed")

        test_client = TestClient(test_app, raise_server_exceptions=False)
        resp = test_client.get("/fail")
        assert resp.status_code == 500
        assert resp.json()["error"] == "agent_error"
        assert resp.json()["detail"] == "agent loop failed"

    def test_llm_error_response_structure(self):
        """LLMError response must always contain error, detail, llm_status_code."""
        from app.exceptions import LLMError, llm_error_handler

        test_app = FastAPI()
        test_app.add_exception_handler(LLMError, llm_error_handler)

        @test_app.post("/query")
        async def query_endpoint():
            raise LLMError(status_code=429, detail="Too many requests")

        test_client = TestClient(test_app, raise_server_exceptions=False)
        resp = test_client.post("/query")
        data = resp.json()
        assert "error" in data
        assert "detail" in data
        assert "llm_status_code" in data
        assert data["error"] == "llm_error"
        assert data["llm_status_code"] == 429
