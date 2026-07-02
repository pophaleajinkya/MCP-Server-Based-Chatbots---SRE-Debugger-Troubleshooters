"""Unit tests for app/routers/mcp_proxy.py.

Covers every branch in the mcp_proxy endpoint:
  - tools/list        — iterates pool sessions and collects tools
  - tools/call        — dispatches to pool.call_tool
  - tools/call        — missing tool name → 400
  - resources/read    — reads URI from first session that responds
  - resources/read    — missing URI → 400
  - resources/read    — resource not found in any session → 404
  - resources/list    — lists from first session that responds
  - resources/list    — all sessions fail → empty list 200
  - prompts/list      — lists from first session that responds
  - prompts/list      — all sessions fail → empty list 200
  - prompts/get       — dispatches to pool.call_prompt
  - unsupported method → 400
  - invalid JSON body → 400
  - unexpected exception → 502
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(tools=None, rpc_result=None, rpc_raises=None, name="s1"):
    """Build a mock MCPSession-like object."""
    session = MagicMock()
    session._name = name
    session.tools = tools or []
    if rpc_raises:
        session._rpc = AsyncMock(side_effect=rpc_raises)
    else:
        session._rpc = AsyncMock(return_value=rpc_result or {})
    return session


def _make_pool(sessions=None, call_tool_result="tool result", call_prompt_result="prompt result"):
    """Build a mock MCPPool-like object."""
    pool = MagicMock()
    pool._sessions = sessions or []
    pool.call_tool = AsyncMock(return_value=call_tool_result)
    pool.call_prompt = AsyncMock(return_value=call_prompt_result)
    return pool


def _build_app(pool):
    """Build a minimal FastAPI app with the mcp_proxy router and injected pool."""
    from app.routers.mcp_proxy import router

    app = FastAPI()
    app.include_router(router)
    app.state.mcp_pool = pool
    return app


# ── tools/list ────────────────────────────────────────────────────────────────

class TestToolsList:
    def test_tools_list_empty_pool(self):
        pool = _make_pool(sessions=[])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "tools/list", "params": {}})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"tools": []}}

    def test_tools_list_single_session_with_tools(self):
        tools = [{"name": "check_health"}, {"name": "get_metrics"}]
        session = _make_session(tools=tools)
        pool = _make_pool(sessions=[session])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "tools/list", "params": {}})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["result"]["tools"]) == 2
        assert data["result"]["tools"][0]["name"] == "check_health"

    def test_tools_list_multiple_sessions_merged(self):
        s1 = _make_session(tools=[{"name": "tool_a"}], name="s1")
        s2 = _make_session(tools=[{"name": "tool_b"}, {"name": "tool_c"}], name="s2")
        pool = _make_pool(sessions=[s1, s2])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "tool_a" in names
        assert "tool_b" in names
        assert "tool_c" in names

    def test_tools_list_no_params_field(self):
        """params is optional — method alone is enough."""
        pool = _make_pool(sessions=[])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 200


# ── tools/call ────────────────────────────────────────────────────────────────

class TestToolsCall:
    def test_tools_call_success(self):
        pool = _make_pool(call_tool_result="healthy: true")
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "check_health", "arguments": {"namespace": "intl-sre"}},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["content"][0]["text"] == "healthy: true"
        assert data["result"]["content"][0]["type"] == "text"

    def test_tools_call_missing_tool_name_returns_400(self):
        pool = _make_pool()
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"arguments": {}},  # name omitted
        })
        assert resp.status_code == 400
        assert "Missing tool name" in resp.json()["error"]

    def test_tools_call_empty_tool_name_returns_400(self):
        pool = _make_pool()
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "", "arguments": {}},
        })
        assert resp.status_code == 400

    def test_tools_call_no_arguments_defaults_to_empty(self):
        """arguments is optional; should default to {} if absent."""
        pool = _make_pool(call_tool_result="ok")
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "my_tool"},
        })
        assert resp.status_code == 200
        pool.call_tool.assert_called_once_with("my_tool", {})

    def test_tools_call_logs_and_calls_pool(self):
        pool = _make_pool(call_tool_result="result text")
        client = TestClient(_build_app(pool))
        client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "some_tool", "arguments": {"k": "v"}},
        })
        pool.call_tool.assert_called_once_with("some_tool", {"k": "v"})


# ── resources/read ────────────────────────────────────────────────────────────

class TestResourcesRead:
    def test_resources_read_success_first_session(self):
        rpc_resp = {"result": {"contents": [{"text": "guide content"}]}}
        session = _make_session(rpc_result=rpc_resp)
        pool = _make_pool(sessions=[session])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "wcnp://agent-guide"},
        })
        assert resp.status_code == 200
        assert resp.json() == {"result": {"contents": [{"text": "guide content"}]}}

    def test_resources_read_missing_uri_returns_400(self):
        pool = _make_pool(sessions=[_make_session()])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {},
        })
        assert resp.status_code == 400
        assert "Missing resource URI" in resp.json()["error"]

    def test_resources_read_empty_uri_returns_400(self):
        pool = _make_pool(sessions=[_make_session()])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": ""},
        })
        assert resp.status_code == 400

    def test_resources_read_not_found_when_all_sessions_fail(self):
        s1 = _make_session(rpc_raises=RuntimeError("not found"), name="s1")
        s2 = _make_session(rpc_raises=RuntimeError("not found"), name="s2")
        pool = _make_pool(sessions=[s1, s2])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "unknown://resource"},
        })
        assert resp.status_code == 404
        assert "Resource not found" in resp.json()["error"]

    def test_resources_read_skips_failing_sessions_and_uses_second(self):
        """First session raises, second session responds OK."""
        s1 = _make_session(rpc_raises=RuntimeError("timeout"), name="s1")
        rpc_resp = {"result": {"contents": [{"text": "found"}]}}
        s2 = _make_session(rpc_result=rpc_resp, name="s2")
        pool = _make_pool(sessions=[s1, s2])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "some://uri"},
        })
        assert resp.status_code == 200

    def test_resources_read_no_sessions_returns_404(self):
        pool = _make_pool(sessions=[])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "any://uri"},
        })
        assert resp.status_code == 404


# ── resources/list ────────────────────────────────────────────────────────────

class TestResourcesList:
    def test_resources_list_success(self):
        rpc_resp = {"result": {"resources": [{"uri": "wcnp://guide", "name": "Guide"}]}}
        session = _make_session(rpc_result=rpc_resp)
        pool = _make_pool(sessions=[session])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "resources/list", "params": {}})
        assert resp.status_code == 200
        assert len(resp.json()["result"]["resources"]) == 1

    def test_resources_list_all_sessions_fail_returns_empty(self):
        s1 = _make_session(rpc_raises=RuntimeError("error"), name="s1")
        pool = _make_pool(sessions=[s1])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"resources": []}}

    def test_resources_list_no_sessions_returns_empty(self):
        pool = _make_pool(sessions=[])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"resources": []}}

    def test_resources_list_uses_first_successful_session(self):
        s1 = _make_session(rpc_raises=RuntimeError("offline"), name="s1")
        rpc_resp = {"result": {"resources": [{"uri": "r://1"}]}}
        s2 = _make_session(rpc_result=rpc_resp, name="s2")
        pool = _make_pool(sessions=[s1, s2])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert len(resp.json()["result"]["resources"]) == 1


# ── prompts/list ──────────────────────────────────────────────────────────────

class TestPromptsList:
    def test_prompts_list_success(self):
        rpc_resp = {"result": {"prompts": [{"name": "rca-investigate"}]}}
        session = _make_session(rpc_result=rpc_resp)
        pool = _make_pool(sessions=[session])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "prompts/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["prompts"][0]["name"] == "rca-investigate"

    def test_prompts_list_all_fail_returns_empty(self):
        s1 = _make_session(rpc_raises=RuntimeError("not supported"), name="s1")
        pool = _make_pool(sessions=[s1])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "prompts/list"})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"prompts": []}}

    def test_prompts_list_no_sessions_returns_empty(self):
        pool = _make_pool(sessions=[])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "prompts/list"})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"prompts": []}}

    def test_prompts_list_skips_failing_and_uses_next(self):
        s1 = _make_session(rpc_raises=RuntimeError("err"), name="s1")
        rpc_resp = {"result": {"prompts": [{"name": "p1"}]}}
        s2 = _make_session(rpc_result=rpc_resp, name="s2")
        pool = _make_pool(sessions=[s1, s2])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "prompts/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["prompts"][0]["name"] == "p1"


# ── prompts/get ───────────────────────────────────────────────────────────────

class TestPromptsGet:
    def test_prompts_get_success(self):
        pool = _make_pool(call_prompt_result="RCA investigation instructions...")
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "rca-investigate", "arguments": {"namespace": "intl-sre"}},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["content"][0]["text"] == "RCA investigation instructions..."
        assert data["result"]["content"][0]["type"] == "text"

    def test_prompts_get_calls_pool_with_name_and_arguments(self):
        pool = _make_pool(call_prompt_result="result")
        client = TestClient(_build_app(pool))
        client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "my-prompt", "arguments": {"a": "b"}},
        })
        pool.call_prompt.assert_called_once_with("my-prompt", {"a": "b"})

    def test_prompts_get_no_arguments_defaults_to_empty(self):
        pool = _make_pool(call_prompt_result="result")
        client = TestClient(_build_app(pool))
        client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "my-prompt"},
        })
        pool.call_prompt.assert_called_once_with("my-prompt", {})


# ── Error paths ───────────────────────────────────────────────────────────────

class TestErrorPaths:
    def test_invalid_json_returns_400(self):
        pool = _make_pool()
        client = TestClient(_build_app(pool))
        resp = client.post(
            "/mcp-proxy",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]

    def test_unsupported_method_returns_400(self):
        pool = _make_pool()
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": "unknown/method"})
        assert resp.status_code == 400
        assert "Unsupported method" in resp.json()["error"]

    def test_empty_method_returns_400(self):
        pool = _make_pool()
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"method": ""})
        assert resp.status_code == 400

    def test_tools_call_pool_exception_returns_502(self):
        pool = _make_pool()
        pool.call_tool = AsyncMock(side_effect=RuntimeError("pool crashed"))
        client = TestClient(_build_app(pool), raise_server_exceptions=False)
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "bad_tool"},
        })
        assert resp.status_code == 502
        assert "Internal proxy error" in resp.json()["error"]

    def test_prompts_get_exception_returns_502(self):
        pool = _make_pool()
        pool.call_prompt = AsyncMock(side_effect=RuntimeError("prompt exploded"))
        client = TestClient(_build_app(pool), raise_server_exceptions=False)
        resp = client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "broken-prompt"},
        })
        assert resp.status_code == 502

    def test_server_name_field_is_parsed_but_not_required(self):
        """serverName is optional; its presence should not cause errors."""
        pool = _make_pool(sessions=[])
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={
            "method": "tools/list",
            "serverName": "my-server",
        })
        assert resp.status_code == 200

    def test_missing_method_defaults_to_empty_string(self):
        """A body with no 'method' key defaults to '' → 400 Unsupported."""
        pool = _make_pool()
        client = TestClient(_build_app(pool))
        resp = client.post("/mcp-proxy", json={"params": {}})
        assert resp.status_code == 400
