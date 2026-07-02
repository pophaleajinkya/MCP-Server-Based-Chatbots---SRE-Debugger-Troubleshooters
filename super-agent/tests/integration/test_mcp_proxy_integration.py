"""Integration tests for src/app/routers/mcp_proxy.py.

Exercises the MCP proxy endpoint through the full HTTP stack with a mocked
MCP pool — no live MCP server connections required.

Coverage targets:
  - POST /mcp-proxy method=tools/list       -> returns all tools from pool
  - POST /mcp-proxy method=tools/call        -> calls tool and returns result
  - POST /mcp-proxy method=tools/call missing name -> 400
  - POST /mcp-proxy method=resources/read    -> proxies to session
  - POST /mcp-proxy method=resources/read missing uri -> 400
  - POST /mcp-proxy method=resources/list    -> returns resources
  - POST /mcp-proxy method=prompts/list      -> returns prompts
  - POST /mcp-proxy method=prompts/get       -> calls prompt
  - POST /mcp-proxy with unsupported method  -> 400
  - POST /mcp-proxy with invalid JSON        -> 400
  - POST /mcp-proxy with server error        -> 502
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# MCP pool mock builder
# ---------------------------------------------------------------------------

def _make_mcp_session(name: str, tools: list[dict] | None = None, guide: str = ""):
    """Build a mock MCPSession."""
    session = MagicMock()
    session._name = name
    session._url = f"http://{name}:8999/mcp"
    session.tools = tools or []
    session.guide = guide
    session.sid = f"sid-{name}"
    session._rpc = AsyncMock()
    return session


def _make_mcp_pool(sessions=None, call_tool_result="tool result", call_prompt_result="prompt result"):
    """Build a mock MCPPool with configurable sessions and call results."""
    pool = MagicMock()
    pool._sessions = sessions or []
    pool.call_tool = AsyncMock(return_value=call_tool_result)
    pool.call_prompt = AsyncMock(return_value=call_prompt_result)
    return pool


def _build_proxy_app(mcp_pool=None):
    """Create a FastAPI test app with the mcp_proxy router and mocked state."""
    from app.routers.mcp_proxy import router

    app = FastAPI()
    app.include_router(router)
    app.state.mcp_pool = mcp_pool or _make_mcp_pool()
    return app


# ===========================================================================
# Test: tools/list
# ===========================================================================

class TestToolsList:
    def test_tools_list_returns_all_tools_from_pool(self):
        """tools/list should aggregate tools from all MCP sessions."""
        tools_a = [{"name": "check_health", "description": "Check health"}]
        tools_b = [{"name": "get_metrics", "description": "Get metrics"}]
        session_a = _make_mcp_session("server-a", tools=tools_a)
        session_b = _make_mcp_session("server-b", tools=tools_b)
        pool = _make_mcp_pool(sessions=[session_a, session_b])

        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 200
        data = resp.json()
        tool_names = [t["name"] for t in data["result"]["tools"]]
        assert "check_health" in tool_names
        assert "get_metrics" in tool_names

    def test_tools_list_empty_sessions_returns_empty(self):
        """tools/list with no sessions returns an empty tools list."""
        pool = _make_mcp_pool(sessions=[])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["tools"] == []

    def test_tools_list_single_session_multiple_tools(self):
        """tools/list returns all tools from a single session."""
        tools = [
            {"name": "tool_a", "description": "A"},
            {"name": "tool_b", "description": "B"},
            {"name": "tool_c", "description": "C"},
        ]
        session = _make_mcp_session("server", tools=tools)
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert len(resp.json()["result"]["tools"]) == 3


# ===========================================================================
# Test: tools/call
# ===========================================================================

class TestToolsCall:
    def test_tools_call_invokes_pool_call_tool(self):
        """tools/call should invoke mcp_pool.call_tool with the correct args."""
        pool = _make_mcp_pool(call_tool_result="health OK")
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "check_health", "arguments": {"ns": "intl-sre"}},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["content"][0]["text"] == "health OK"
        pool.call_tool.assert_called_once_with("check_health", {"ns": "intl-sre"})

    def test_tools_call_missing_name_returns_400(self):
        """tools/call without a tool name should return 400."""
        pool = _make_mcp_pool()
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"arguments": {"ns": "sre"}},
        })
        assert resp.status_code == 400
        assert "Missing tool name" in resp.json()["error"]

    def test_tools_call_empty_name_returns_400(self):
        """tools/call with empty string name should return 400."""
        pool = _make_mcp_pool()
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "", "arguments": {}},
        })
        assert resp.status_code == 400

    def test_tools_call_default_empty_arguments(self):
        """tools/call with no arguments should default to empty dict."""
        pool = _make_mcp_pool(call_tool_result="result")
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "simple_tool"},
        })
        assert resp.status_code == 200
        pool.call_tool.assert_called_once_with("simple_tool", {})


# ===========================================================================
# Test: resources/read
# ===========================================================================

class TestResourcesRead:
    def test_resources_read_proxies_to_session(self):
        """resources/read should forward the request to the MCP session."""
        session = _make_mcp_session("server-a")
        session._rpc = AsyncMock(return_value={
            "result": {"contents": [{"uri": "wcnp://guide", "text": "guide content"}]},
        })
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "wcnp://guide"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "contents" in data["result"]

    def test_resources_read_missing_uri_returns_400(self):
        """resources/read without a URI should return 400."""
        pool = _make_mcp_pool(sessions=[_make_mcp_session("s")])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {},
        })
        assert resp.status_code == 400
        assert "Missing resource URI" in resp.json()["error"]

    def test_resources_read_empty_uri_returns_400(self):
        """resources/read with empty string URI should return 400."""
        pool = _make_mcp_pool(sessions=[_make_mcp_session("s")])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": ""},
        })
        assert resp.status_code == 400

    def test_resources_read_not_found_returns_404(self):
        """resources/read returns 404 when no session can serve the resource."""
        session = _make_mcp_session("server-a")
        session._rpc = AsyncMock(side_effect=Exception("not found"))
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "wcnp://nonexistent"},
        })
        assert resp.status_code == 404

    def test_resources_read_tries_multiple_sessions(self):
        """resources/read should try the next session if the first fails."""
        session_a = _make_mcp_session("server-a")
        session_a._rpc = AsyncMock(side_effect=Exception("unavailable"))

        session_b = _make_mcp_session("server-b")
        session_b._rpc = AsyncMock(return_value={
            "result": {"contents": [{"uri": "res://data", "text": "from b"}]},
        })

        pool = _make_mcp_pool(sessions=[session_a, session_b])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "res://data"},
        })
        assert resp.status_code == 200


# ===========================================================================
# Test: resources/list
# ===========================================================================

class TestResourcesList:
    def test_resources_list_returns_resources(self):
        """resources/list should return the resources from the MCP session."""
        session = _make_mcp_session("server-a")
        session._rpc = AsyncMock(return_value={
            "result": {"resources": [{"uri": "wcnp://guide", "name": "Guide"}]},
        })
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert "resources" in resp.json()["result"]

    def test_resources_list_all_sessions_fail_returns_empty(self):
        """resources/list returns empty when all sessions fail."""
        session = _make_mcp_session("server-a")
        session._rpc = AsyncMock(side_effect=Exception("down"))
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["resources"] == []

    def test_resources_list_no_sessions_returns_empty(self):
        """resources/list with no sessions returns empty resources."""
        pool = _make_mcp_pool(sessions=[])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["resources"] == []


# ===========================================================================
# Test: prompts/list
# ===========================================================================

class TestPromptsList:
    def test_prompts_list_returns_prompts(self):
        """prompts/list should return prompts from an MCP session."""
        session = _make_mcp_session("server-a")
        session._rpc = AsyncMock(return_value={
            "result": {"prompts": [{"name": "health-check", "description": "Run health check"}]},
        })
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "prompts/list"})
        assert resp.status_code == 200
        assert "prompts" in resp.json()["result"]

    def test_prompts_list_all_sessions_fail_returns_empty(self):
        """prompts/list returns empty when all sessions fail."""
        session = _make_mcp_session("server-a")
        session._rpc = AsyncMock(side_effect=Exception("down"))
        pool = _make_mcp_pool(sessions=[session])
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "prompts/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["prompts"] == []


# ===========================================================================
# Test: prompts/get
# ===========================================================================

class TestPromptsGet:
    def test_prompts_get_calls_pool_call_prompt(self):
        """prompts/get should invoke mcp_pool.call_prompt."""
        pool = _make_mcp_pool(call_prompt_result="Prompt response text")
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "health-check", "arguments": {"ns": "sre"}},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["content"][0]["text"] == "Prompt response text"
        pool.call_prompt.assert_called_once_with("health-check", {"ns": "sre"})

    def test_prompts_get_default_empty_arguments(self):
        """prompts/get with no arguments should default to empty dict."""
        pool = _make_mcp_pool(call_prompt_result="result")
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "my-prompt"},
        })
        assert resp.status_code == 200
        pool.call_prompt.assert_called_once_with("my-prompt", {})


# ===========================================================================
# Test: Unsupported method
# ===========================================================================

class TestUnsupportedMethod:
    def test_unsupported_method_returns_400(self):
        """An unsupported JSON-RPC method should return 400."""
        pool = _make_mcp_pool()
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "unknown/method"})
        assert resp.status_code == 400
        assert "Unsupported method" in resp.json()["error"]

    def test_empty_method_returns_400(self):
        """An empty method string should return 400."""
        pool = _make_mcp_pool()
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": ""})
        assert resp.status_code == 400

    def test_missing_method_returns_400(self):
        """A request body with no method key should return 400."""
        pool = _make_mcp_pool()
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"params": {}})
        assert resp.status_code == 400


# ===========================================================================
# Test: Invalid JSON
# ===========================================================================

class TestInvalidJSON:
    def test_invalid_json_body_returns_400(self):
        """A request with invalid JSON should return 400."""
        pool = _make_mcp_pool()
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post(
            "/mcp-proxy",
            content=b"not valid json {{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]


# ===========================================================================
# Test: Server error -> 502
# ===========================================================================

class TestServerError:
    def test_tools_call_server_error_returns_502(self):
        """When call_tool raises an exception, return 502."""
        pool = _make_mcp_pool()
        pool.call_tool = AsyncMock(side_effect=ConnectionError("MCP server down"))
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "check_health", "arguments": {}},
        })
        assert resp.status_code == 502
        assert "Internal proxy error" in resp.json()["error"]

    def test_prompts_get_server_error_returns_502(self):
        """When call_prompt raises an exception, return 502."""
        pool = _make_mcp_pool()
        pool.call_prompt = AsyncMock(side_effect=RuntimeError("unexpected error"))
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "broken-prompt"},
        })
        assert resp.status_code == 502
        assert "Internal proxy error" in resp.json()["error"]

    def test_tools_list_exception_returns_502(self):
        """If iterating sessions raises, return 502."""
        pool = _make_mcp_pool()
        # Make _sessions property raise on iteration
        pool._sessions = MagicMock()
        pool._sessions.__iter__ = MagicMock(side_effect=RuntimeError("pool broken"))
        app = _build_proxy_app(pool)
        client = TestClient(app)

        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 502
