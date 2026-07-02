"""
Comprehensive unit tests for app.exceptions — all exception types and handlers.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.exceptions import (
    AgentBaseError,
    AgentError,
    LLMError,
    MCPConnectionError,
    MCPToolError,
    agent_error_handler,
    llm_error_handler,
    mcp_connection_error_handler,
)


class TestExceptionHierarchy:

    def test_agent_base_error_is_base(self):
        assert issubclass(AgentBaseError, Exception)

    def test_mcp_connection_error_inherits(self):
        assert issubclass(MCPConnectionError, AgentBaseError)

    def test_mcp_tool_error_inherits(self):
        assert issubclass(MCPToolError, AgentBaseError)

    def test_llm_error_inherits(self):
        assert issubclass(LLMError, AgentBaseError)

    def test_agent_error_inherits(self):
        assert issubclass(AgentError, AgentBaseError)


class TestExceptionInstantiation:

    def test_agent_base_error(self):
        e = AgentBaseError("test")
        assert str(e) == "test"

    def test_mcp_connection_error(self):
        e = MCPConnectionError("server down")
        assert "server down" in str(e)

    def test_mcp_tool_error(self):
        e = MCPToolError("tool failed")
        assert "tool failed" in str(e)

    def test_llm_error_basic(self):
        e = LLMError(status_code=400, detail="bad request")
        assert "bad request" in str(e)
        assert e.status_code == 400

    def test_llm_error_with_status_code(self):
        e = LLMError(502, "timeout")
        assert e.status_code == 502
        assert e.detail == "timeout"

    def test_llm_error_with_detail(self):
        e = LLMError(429, "rate limited by gateway")
        assert e.detail == "rate limited by gateway"

    def test_agent_error(self):
        e = AgentError("loop failed")
        assert "loop failed" in str(e)


class TestExceptionCatching:

    def test_catch_mcp_connection_as_base(self):
        with pytest.raises(AgentBaseError):
            raise MCPConnectionError("down")

    def test_catch_llm_as_base(self):
        with pytest.raises(AgentBaseError):
            raise LLMError(504, "timeout")

    def test_catch_agent_as_base(self):
        with pytest.raises(AgentBaseError):
            raise AgentError("failed")

    def test_catch_mcp_tool_as_base(self):
        with pytest.raises(AgentBaseError):
            raise MCPToolError("tool err")


class TestLlmErrorHandler:

    @pytest.mark.asyncio
    async def test_returns_502(self):
        request = MagicMock()
        exc = LLMError(502, "gateway error")
        response = await llm_error_handler(request, exc)
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_json_body(self):
        import json
        request = MagicMock()
        exc = LLMError(504, "timeout")
        response = await llm_error_handler(request, exc)
        body = json.loads(response.body.decode())
        assert body["error"] == "llm_error"
        assert body["detail"] == "timeout"
        assert body["llm_status_code"] == 504


class TestAgentErrorHandler:

    @pytest.mark.asyncio
    async def test_returns_500(self):
        request = MagicMock()
        exc = AgentError("loop failure")
        response = await agent_error_handler(request, exc)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_json_body(self):
        import json
        request = MagicMock()
        exc = AgentError("crash")
        response = await agent_error_handler(request, exc)
        body = json.loads(response.body.decode())
        assert "error" in body


class TestMcpConnectionErrorHandler:

    @pytest.mark.asyncio
    async def test_returns_503(self):
        request = MagicMock()
        exc = MCPConnectionError("server unreachable")
        response = await mcp_connection_error_handler(request, exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_json_body(self):
        import json
        request = MagicMock()
        exc = MCPConnectionError("network failure")
        response = await mcp_connection_error_handler(request, exc)
        body = json.loads(response.body.decode())
        assert body["error"] == "mcp_connection_error"
        assert "network failure" in body["detail"]
