"""Additional unit tests for app.exceptions — covers mcp_connection_error_handler."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.exceptions import (
    MCPConnectionError,
    mcp_connection_error_handler,
    AgentBaseError,
    MCPToolError,
)


class TestMCPConnectionErrorHandler:
    @pytest.mark.asyncio
    async def test_returns_503(self):
        request = MagicMock()
        exc = MCPConnectionError("health-mcp server is unreachable")
        resp = await mcp_connection_error_handler(request, exc)
        assert resp.status_code == 503
        import json
        body = json.loads(resp.body)
        assert body["error"] == "mcp_connection_error"
        assert "health-mcp" in body["detail"]


class TestExceptionHierarchy:
    def test_mcp_connection_error_is_agent_base(self):
        assert issubclass(MCPConnectionError, AgentBaseError)

    def test_mcp_tool_error_is_agent_base(self):
        assert issubclass(MCPToolError, AgentBaseError)
