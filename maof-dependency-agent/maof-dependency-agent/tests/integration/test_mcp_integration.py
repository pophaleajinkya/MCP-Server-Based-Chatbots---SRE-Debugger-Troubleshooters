"""Integration tests for the MCP endpoint (POST /mcp/).

Strategy:
  - Use the session-scoped `mcp_client` (Starlette TestClient) which starts
    the FastAPI lifespan (and thus mcp.session_manager) exactly once per
    pytest session — no async event loop conflicts, no cross-task anyio issues
  - Send real JSON-RPC 2.0 requests and verify the response
  - Tests are synchronous: TestClient drives the async ASGI app via
    anyio's blocking portal

All 15 expected tools:
  WCNP (3):     list_apps_in_namespace
                fetch_wcnp_upstream_dependencies
                fetch_wcnp_downstream_dependencies
  OneOps (2):   fetch_oneops_upstream_dependencies
                fetch_oneops_downstream_dependencies
  Managed (4):  fetch_cassandra_upstream_dependencies
                fetch_meghacache_upstream_dependencies
                fetch_cosmos_upstream_dependencies
                fetch_sqlserver_upstream_dependencies
  Graph (6):    get_wcnp_dependency_graph
                get_oneops_dependency_graph
                get_cassandra_dependency_graph
                get_meghacache_dependency_graph
                get_cosmos_dependency_graph
                get_sqlserver_dependency_graph
"""
import json
import pytest
from unittest.mock import AsyncMock, patch


# ─── shared helpers ───────────────────────────────────────────────────────────

EXPECTED_TOOLS = {
    # WCNP
    "list_apps_in_namespace",
    "fetch_wcnp_upstream_dependencies",
    "fetch_wcnp_downstream_dependencies",
    # OneOps
    "fetch_oneops_upstream_dependencies",
    "fetch_oneops_downstream_dependencies",
    # Managed services
    "fetch_cassandra_upstream_dependencies",
    "fetch_meghacache_upstream_dependencies",
    "fetch_cosmos_upstream_dependencies",
    "fetch_sqlserver_upstream_dependencies",
    # Graph / Mermaid diagram tools
    "get_wcnp_dependency_graph",
    "get_oneops_dependency_graph",
    "get_cassandra_dependency_graph",
    "get_meghacache_dependency_graph",
    "get_cosmos_dependency_graph",
    "get_sqlserver_dependency_graph",
}

_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def _parse_mcp_response(response) -> dict:
    """Parse JSON or SSE MCP response into a plain dict."""
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
        raise AssertionError(f"No data event found in SSE body:\n{text}")
    return response.json()


# ─── POST /mcp/ — endpoint reachability ──────────────────────────────────────

class TestMcpEndpointReachability:
    """Verify the /mcp/ endpoint accepts JSON-RPC 2.0 requests."""

    def test_initialize_returns_200(self, mcp_client):
        """MCP initialize must return HTTP 200."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-client", "version": "1.0"},
            }),
            headers=_MCP_HEADERS,
        )
        assert response.status_code == 200

    def test_invalid_json_returns_4xx(self, mcp_client):
        """Malformed JSON body must return a 4xx error."""
        response = mcp_client.post(
            "/mcp/",
            content=b"not-json",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code >= 400


# ─── tools/list ───────────────────────────────────────────────────────────────

class TestMcpToolsList:
    """Verify MCP server exposes exactly the expected set of tools."""

    def test_tools_list_returns_9_tools(self, mcp_client):
        """MCP server must expose exactly 15 tools (9 core + 6 graph/Mermaid tools)."""
        response = mcp_client.post("/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS)
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        assert len(data["result"]["tools"]) == 15

    def test_tools_list_contains_all_expected_tool_names(self, mcp_client):
        """Every expected tool name must be present in the tools/list response."""
        response = mcp_client.post("/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS)
        data = _parse_mcp_response(response)
        tool_names = {t["name"] for t in data["result"]["tools"]}
        assert tool_names == EXPECTED_TOOLS

    def test_each_tool_has_name_and_description(self, mcp_client):
        """Every tool must have a non-empty name and description."""
        response = mcp_client.post("/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS)
        data = _parse_mcp_response(response)
        for tool in data["result"]["tools"]:
            assert tool.get("name"), f"Tool missing name: {tool}"
            assert tool.get("description"), f"Tool '{tool['name']}' missing description"

    def test_wcnp_tools_are_registered(self, mcp_client):
        """All 3 WCNP tools must be in the tools list."""
        wcnp_tools = {
            "list_apps_in_namespace",
            "fetch_wcnp_upstream_dependencies",
            "fetch_wcnp_downstream_dependencies",
        }
        response = mcp_client.post("/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS)
        data = _parse_mcp_response(response)
        registered = {t["name"] for t in data["result"]["tools"]}
        assert wcnp_tools.issubset(registered)

    def test_managed_service_tools_are_registered(self, mcp_client):
        """All 4 managed service tools must be in the tools list."""
        managed_tools = {
            "fetch_cassandra_upstream_dependencies",
            "fetch_meghacache_upstream_dependencies",
            "fetch_cosmos_upstream_dependencies",
            "fetch_sqlserver_upstream_dependencies",
        }
        response = mcp_client.post("/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS)
        data = _parse_mcp_response(response)
        registered = {t["name"] for t in data["result"]["tools"]}
        assert managed_tools.issubset(registered)


# ─── resources/list ──────────────────────────────────────────────────────────

class TestMcpResourcesList:
    """Verify MCP server exposes the agent-guide resource."""

    def test_resources_list_contains_agent_guide(self, mcp_client):
        """The dependency://agent-guide resource must be registered."""
        response = mcp_client.post(
            "/mcp/", json=_rpc("resources/list"), headers=_MCP_HEADERS
        )
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        uris = [r["uri"] for r in data["result"]["resources"]]
        assert "dependency://agent-guide" in uris

    def test_agent_guide_resource_readable(self, mcp_client):
        """Reading dependency://agent-guide must return non-empty markdown content."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("resources/read", {"uri": "dependency://agent-guide"}),
            headers=_MCP_HEADERS,
        )
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        contents = data["result"]["contents"]
        assert len(contents) > 0
        text_content = contents[0].get("text", "")
        assert len(text_content) > 100
        assert "WCNP" in text_content or "Kubernetes" in text_content


# ─── prompts/list ─────────────────────────────────────────────────────────────

class TestMcpPromptsList:
    """Verify MCP server exposes exactly the expected prompts."""

    def test_prompts_list_contains_trace_wcnp_app(self, mcp_client):
        """trace_wcnp_app prompt must be registered."""
        response = mcp_client.post(
            "/mcp/", json=_rpc("prompts/list"), headers=_MCP_HEADERS
        )
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        prompt_names = {p["name"] for p in data["result"]["prompts"]}
        assert "trace_wcnp_app" in prompt_names

    def test_prompts_list_contains_trace_oneops_app(self, mcp_client):
        """trace_oneops_app prompt must be registered."""
        response = mcp_client.post(
            "/mcp/", json=_rpc("prompts/list"), headers=_MCP_HEADERS
        )
        data = _parse_mcp_response(response)
        prompt_names = {p["name"] for p in data["result"]["prompts"]}
        assert "trace_oneops_app" in prompt_names

    def test_prompts_list_count_is_exactly_two(self, mcp_client):
        """Exactly 2 prompts must be registered (no trace_managed_service)."""
        response = mcp_client.post(
            "/mcp/", json=_rpc("prompts/list"), headers=_MCP_HEADERS
        )
        data = _parse_mcp_response(response)
        assert len(data["result"]["prompts"]) == 2

    def test_trace_managed_service_prompt_not_registered(self, mcp_client):
        """trace_managed_service must NOT be registered (was intentionally removed)."""
        response = mcp_client.post(
            "/mcp/", json=_rpc("prompts/list"), headers=_MCP_HEADERS
        )
        data = _parse_mcp_response(response)
        prompt_names = {p["name"] for p in data["result"]["prompts"]}
        assert "trace_managed_service" not in prompt_names


# ─── MCP server configuration ─────────────────────────────────────────────────

class TestMcpServerConfiguration:
    """Verify the MCP server is configured as expected."""

    def test_mcp_endpoint_is_at_slash_mcp_slash(self, mcp_client):
        """MCP endpoint must be at /mcp/ (not /mcp/mcp/ or /mcp)."""
        response = mcp_client.post(
            "/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS
        )
        assert response.status_code == 200

    def test_no_session_id_required(self, mcp_client):
        """With stateless_http=True, requests without Mcp-Session-Id must work."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("tools/list"),
            headers={
                "Accept": "application/json, text/event-stream",
                # Deliberately omitting Mcp-Session-Id header
            },
        )
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        assert "error" not in data or "session" not in str(data.get("error", "")).lower()
