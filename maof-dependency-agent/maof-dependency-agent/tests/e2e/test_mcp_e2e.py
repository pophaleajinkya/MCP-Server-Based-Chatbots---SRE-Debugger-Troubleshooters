"""End-to-end tests for MCP tool calls via POST /mcp/.

Strategy:
  - Use the session-scoped `mcp_client` (Starlette TestClient) which starts
    the FastAPI lifespan (and thus mcp.session_manager) exactly once per
    pytest session — no async event loop conflicts, no cross-task anyio issues
  - Mock only the leaf-level service functions (SRE-OPS, DX Console)
  - Assert on the complete response structure returned through the MCP wire format
  - All tests are synchronous: TestClient drives the async ASGI app via
    anyio's blocking portal

Scenarios covered:
  1. WCNP upstream tool call       → correct deps returned through MCP wire
  2. WCNP downstream tool call     → correct deps returned through MCP wire
  3. WCNP list apps                → app list returned through MCP wire
  4. OneOps upstream tool call     → correct deps returned through MCP wire
  5. OneOps downstream tool call   → correct deps returned through MCP wire
  6. Cassandra upstream tool       → correct deps returned through MCP wire
  7. Cosmos DB upstream tool       → correct deps returned through MCP wire
  8. Service error propagation     → error status in tool result, NOT HTTP 500
  9. Prompt get: trace_wcnp_app    → correct interpolated prompt text
 10. Prompt get: trace_oneops_app  → correct interpolated prompt text
 11. Old tool names not registered → regression guard
"""
import json
import pytest
from unittest.mock import AsyncMock, patch


# ─── shared helpers ───────────────────────────────────────────────────────────

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
        raise AssertionError(f"No data event in SSE body:\n{text}")
    return response.json()


def _tool_call(tool_name: str, arguments: dict) -> dict:
    return _rpc("tools/call", {"name": tool_name, "arguments": arguments})


def _make_deps(count: int = 2, direction: str = "upstream") -> list:
    return [
        {"app_name": f"svc-{i}", "namespace": "test-ns", "tier": "T1", "direction": direction}
        for i in range(count)
    ]


# ─── WCNP upstream E2E ────────────────────────────────────────────────────────

class TestMcpWcnpUpstreamToolCall:
    """Full E2E call to fetch_wcnp_upstream_dependencies via MCP wire format."""

    def test_returns_upstream_dependencies(self, mcp_client):
        upstream = _make_deps(3, "upstream")
        breakdown = {"upstream_count": 3, "downstream_count": 0, "total": 3}

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=(upstream, [], breakdown)),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "iro-prod", "namespace": "item-assembler-async"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "success"
        assert tool_result["direction"] == "upstream"
        assert tool_result["app_name"] == "iro-prod"
        assert tool_result["namespace"] == "item-assembler-async"
        assert tool_result["total_count"] == 3
        assert len(tool_result["dependencies"]) == 3

    def test_error_in_service_returns_error_status_not_http_500(self, mcp_client):
        """When underlying service fails, MCP returns HTTP 200 with error in content."""
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=RuntimeError("SRE-OPS down")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "iro-prod", "namespace": "item-assembler-async"},
                ),
                headers=_MCP_HEADERS,
            )

        # MCP wraps tool errors in content — HTTP status stays 200
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "error"
        assert "SRE-OPS down" in tool_result["error"]


# ─── WCNP downstream E2E ──────────────────────────────────────────────────────

class TestMcpWcnpDownstreamToolCall:
    """Full E2E call to fetch_wcnp_downstream_dependencies via MCP wire format."""

    def test_returns_downstream_dependencies(self, mcp_client):
        downstream = _make_deps(2, "downstream")
        breakdown = {"upstream_count": 0, "downstream_count": 2, "total": 2}

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=([], downstream, breakdown)),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_downstream_dependencies",
                    {"app_name": "iro-prod", "namespace": "item-assembler-async"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "success"
        assert tool_result["direction"] == "downstream"
        assert tool_result["total_count"] == 2


# ─── WCNP list apps E2E ───────────────────────────────────────────────────────

class TestMcpListAppsInNamespace:
    """Full E2E call to list_apps_in_namespace via MCP wire format."""

    def test_returns_app_list_for_namespace(self, mcp_client):
        expected = {"apps": ["app-a", "app-b", "app-c"], "namespace": "iro-async"}

        with patch(
            "src.mcp_server.tools.wcnp.get_apps_for_namespace",
            new=AsyncMock(return_value=expected),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call("list_apps_in_namespace", {"namespace": "iro-async"}),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result == expected


# ─── OneOps upstream E2E ──────────────────────────────────────────────────────

class TestMcpOneopsUpstreamToolCall:
    """Full E2E call to fetch_oneops_upstream_dependencies via MCP wire format."""

    def test_returns_upstream_dependencies(self, mcp_client):
        upstream = _make_deps(2, "upstream")

        with patch(
            "src.mcp_server.tools.oneops._svc_upstream",
            new=AsyncMock(return_value=upstream),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_oneops_upstream_dependencies",
                    {"org": "mexicoecomm", "platform": "rmsag2", "assembly": "mx-rms"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "success"
        assert tool_result["direction"] == "upstream"
        assert tool_result["org"] == "mexicoecomm"
        assert tool_result["platform"] == "rmsag2"
        assert tool_result["assembly"] == "mx-rms"
        assert tool_result["total_count"] == 2


# ─── OneOps downstream E2E ───────────────────────────────────────────────────

class TestMcpOneopsDownstreamToolCall:
    """Full E2E call to fetch_oneops_downstream_dependencies via MCP wire format."""

    def test_returns_downstream_dependencies(self, mcp_client):
        downstream = _make_deps(1, "downstream")

        with patch(
            "src.mcp_server.tools.oneops._svc_downstream",
            new=AsyncMock(return_value=downstream),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_oneops_downstream_dependencies",
                    {"org": "mexicoecomm", "platform": "rmsag2", "assembly": "mx-rms"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "success"
        assert tool_result["direction"] == "downstream"
        assert tool_result["total_count"] == 1


# ─── Cassandra upstream E2E ───────────────────────────────────────────────────

class TestMcpCassandraUpstreamToolCall:
    """Full E2E call to fetch_cassandra_upstream_dependencies via MCP wire format."""

    def test_returns_upstream_dependencies(self, mcp_client):
        deps = _make_deps(4, "upstream")

        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(return_value=deps),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_cassandra_upstream_dependencies",
                    {"assembly": "mx-rms", "platform": "rmsag2"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "success"
        assert tool_result["service_type"] == "cassandra"
        assert tool_result["direction"] == "upstream"
        assert tool_result["total_count"] == 4


# ─── Cosmos DB upstream E2E ──────────────────────────────────────────────────

class TestMcpCosmosUpstreamToolCall:
    """Full E2E call to fetch_cosmos_upstream_dependencies via MCP wire format."""

    def test_returns_upstream_dependencies(self, mcp_client):
        deps = _make_deps(2, "upstream")

        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(return_value=deps),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_cosmos_upstream_dependencies",
                    {
                        "resource_group": "my-rg",
                        "subscription_id": "sub-123",
                        "database_name": "orders-db",
                    },
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        content = data["result"]["content"]
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "success"
        assert tool_result["service_type"] == "cosmos"
        assert tool_result["direction"] == "upstream"


# ─── Prompts E2E ─────────────────────────────────────────────────────────────

class TestMcpPromptsGet:
    """Verify prompts/get returns correctly interpolated prompt text via MCP wire."""

    def test_trace_wcnp_app_prompt_interpolates_params(self, mcp_client):
        """prompts/get for trace_wcnp_app must embed app_name and namespace in the text."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("prompts/get", {
                "name": "trace_wcnp_app",
                "arguments": {"app_name": "payment-svc", "namespace": "payments-prod"},
            }),
            headers=_MCP_HEADERS,
        )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        messages = data["result"]["messages"]
        assert len(messages) > 0
        full_text = " ".join(
            m["content"]["text"] for m in messages
            if isinstance(m.get("content"), dict) and "text" in m["content"]
        )
        assert "payment-svc" in full_text
        assert "payments-prod" in full_text

    def test_trace_oneops_app_prompt_interpolates_params(self, mcp_client):
        """prompts/get for trace_oneops_app must embed org, platform, assembly in the text."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("prompts/get", {
                "name": "trace_oneops_app",
                "arguments": {
                    "org": "mexicoecomm",
                    "platform": "rmsag2",
                    "assembly": "mx-rms",
                },
            }),
            headers=_MCP_HEADERS,
        )

        assert response.status_code == 200
        data = _parse_mcp_response(response)
        messages = data["result"]["messages"]
        full_text = " ".join(
            m["content"]["text"] for m in messages
            if isinstance(m.get("content"), dict) and "text" in m["content"]
        )
        assert "mexicoecomm" in full_text
        assert "rmsag2" in full_text
        assert "mx-rms" in full_text


# ─── Tool registration contract ──────────────────────────────────────────────

class TestMcpToolRegistrationContract:
    """Regression guard: verify old tool names are gone and new names are present."""

    def test_no_old_direction_parameter_tools_exist(self, mcp_client):
        """
        The old fetch_wcnp_dependencies(direction=) and fetch_oneops_dependencies(direction=)
        tools must NOT be registered — they were replaced with explicit upstream/downstream tools.
        """
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("tools/list"),
            headers=_MCP_HEADERS,
        )
        data = _parse_mcp_response(response)
        tool_names = {t["name"] for t in data["result"]["tools"]}
        assert "fetch_wcnp_dependencies" not in tool_names
        assert "fetch_oneops_dependencies" not in tool_names

    def test_no_old_unsuffixed_managed_service_tools_exist(self, mcp_client):
        """
        Old fetch_cassandra_dependencies (without _upstream_) must not exist.
        All managed service tools must have _upstream_ in their name.
        """
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("tools/list"),
            headers=_MCP_HEADERS,
        )
        data = _parse_mcp_response(response)
        tool_names = {t["name"] for t in data["result"]["tools"]}
        old_names = {
            "fetch_cassandra_dependencies",
            "fetch_meghacache_dependencies",
            "fetch_cosmos_dependencies",
            "fetch_sqlserver_dependencies",
        }
        assert not old_names.intersection(tool_names), (
            f"Old tool names still registered: {old_names.intersection(tool_names)}"
        )

    def test_all_managed_tools_have_upstream_in_name(self, mcp_client):
        """Every managed service fetch tool name must contain '_upstream_'.
        Graph/Mermaid tools (get_*_dependency_graph) are excluded from this check
        as they return diagrams for both upstream and downstream combined.
        """
        managed_prefixes = {"cassandra", "meghacache", "cosmos", "sqlserver"}
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("tools/list"),
            headers=_MCP_HEADERS,
        )
        data = _parse_mcp_response(response)
        tool_names = {t["name"] for t in data["result"]["tools"]}
        # Only check fetch tools, not graph/Mermaid diagram tools
        fetch_tool_names = {n for n in tool_names if not n.endswith("_dependency_graph")}
        for prefix in managed_prefixes:
            matching = [n for n in fetch_tool_names if prefix in n]
            assert matching, f"No fetch tool found for managed service type: {prefix}"
            for name in matching:
                assert "_upstream_" in name, (
                    f"Managed service tool '{name}' must contain '_upstream_'"
                )
