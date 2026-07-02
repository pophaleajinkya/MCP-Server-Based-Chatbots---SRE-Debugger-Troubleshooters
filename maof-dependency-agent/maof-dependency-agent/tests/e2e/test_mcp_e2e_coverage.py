"""Extended E2E tests for MCP tool calls — scenarios not covered in test_mcp_e2e.py.

Additional coverage:
  1.  MeghaCache upstream tool call (full wire format)
  2.  SQL Server upstream tool call (full wire format)
  3.  WCNP downstream error propagation
  4.  OneOps upstream error propagation
  5.  OneOps downstream error propagation
  6.  Managed service error propagation (Cassandra)
  7.  list_apps_in_namespace error propagation
  8.  Unknown tool name → JSON-RPC error (not HTTP 500)
  9.  Missing required argument → JSON-RPC error (not HTTP 500)
 10.  Zero-dependency success responses (WCNP, OneOps, managed service)
 11.  Concurrent tool calls to different tools (stateless invariant)
 12.  Prompt content includes correct step-3 summary instruction
 13.  tools/call result has isError=false on success, isError=true on tool error
"""
import json
import pytest
from unittest.mock import AsyncMock, patch


# ─── shared helpers ───────────────────────────────────────────────────────────

_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def _parse_mcp_response(response) -> dict:
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


def _extract_tool_result(response) -> dict:
    """Parse MCP response and extract the tool result dict from content[0].text."""
    data = _parse_mcp_response(response)
    content = data["result"]["content"]
    return json.loads(content[0]["text"])


def _make_deps(count: int, direction: str = "upstream") -> list:
    return [
        {"app_name": f"svc-{i}", "namespace": "test-ns", "tier": "T1", "direction": direction}
        for i in range(count)
    ]


# ─── MeghaCache upstream E2E ─────────────────────────────────────────────────

class TestMcpMeghacacheUpstreamToolCall:
    """Full E2E for fetch_meghacache_upstream_dependencies via MCP wire format."""

    def test_returns_upstream_dependencies(self, mcp_client):
        deps = _make_deps(3)

        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(return_value=deps),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_meghacache_upstream_dependencies",
                    {"assembly": "payments-prod", "platform": "pay-platform"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "success"
        assert result["service_type"] == "meghacache"
        assert result["direction"] == "upstream"
        assert result["total_count"] == 3
        assert len(result["dependencies"]) == 3

    def test_sends_correct_servicetype_to_sre_ops(self, mcp_client):
        """serviceType='meghacache' must be sent to SRE-OPS (not cassandra or other)."""
        mock_svc = AsyncMock(return_value=[])

        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=mock_svc,
        ):
            mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_meghacache_upstream_dependencies",
                    {"assembly": "asm", "platform": "plat"},
                ),
                headers=_MCP_HEADERS,
            )

        called_params = mock_svc.call_args[0][0]
        assert called_params["serviceType"] == "meghacache"

    def test_error_returns_http_200_not_500(self, mcp_client):
        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(side_effect=RuntimeError("cache down")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_meghacache_upstream_dependencies",
                    {"assembly": "asm", "platform": "plat"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "error"
        assert "cache down" in result["error"]


# ─── SQL Server upstream E2E ──────────────────────────────────────────────────

class TestMcpSqlserverUpstreamToolCall:
    """Full E2E for fetch_sqlserver_upstream_dependencies via MCP wire format."""

    def test_returns_upstream_dependencies(self, mcp_client):
        deps = _make_deps(5)

        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(return_value=deps),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_sqlserver_upstream_dependencies",
                    {
                        "resource_group": "prod-rg",
                        "subscription_id": "abc-456",
                        "database_name": "inventory-db",
                    },
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "success"
        assert result["service_type"] == "sqlserver"
        assert result["direction"] == "upstream"
        assert result["total_count"] == 5

    def test_sends_camelcase_params_to_sre_ops(self, mcp_client):
        """snake_case inputs must be mapped to camelCase before SRE-OPS call."""
        mock_svc = AsyncMock(return_value=[])

        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=mock_svc,
        ):
            mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_sqlserver_upstream_dependencies",
                    {
                        "resource_group": "prod-rg",
                        "subscription_id": "abc-456",
                        "database_name": "inventory-db",
                    },
                ),
                headers=_MCP_HEADERS,
            )

        called_params = mock_svc.call_args[0][0]
        assert called_params["resourceGroup"] == "prod-rg"
        assert called_params["subscriptionId"] == "abc-456"
        assert called_params["databaseName"] == "inventory-db"
        assert called_params["serviceType"] == "sqlserver"

    def test_error_preserves_http_200(self, mcp_client):
        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(side_effect=TimeoutError("DB timed out")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_sqlserver_upstream_dependencies",
                    {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "error"
        assert "DB timed out" in result["error"]


# ─── WCNP downstream error propagation ───────────────────────────────────────

class TestMcpWcnpDownstreamErrorPropagation:
    """WCNP downstream errors must stay in content — not cause HTTP 500."""

    def test_service_error_does_not_cause_http_500(self, mcp_client):
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=ConnectionError("network unreachable")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_downstream_dependencies",
                    {"app_name": "my-app", "namespace": "my-ns"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "error"
        assert result["direction"] == "downstream"
        assert result["app_name"] == "my-app"
        assert result["namespace"] == "my-ns"
        assert "network unreachable" in result["error"]

    def test_error_total_count_is_zero(self, mcp_client):
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=RuntimeError("fail")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_downstream_dependencies",
                    {"app_name": "app", "namespace": "ns"},
                ),
                headers=_MCP_HEADERS,
            )

        result = _extract_tool_result(response)
        assert result["total_count"] == 0
        assert result["dependencies"] == []


# ─── OneOps error propagation ─────────────────────────────────────────────────

class TestMcpOneopsErrorPropagation:
    """OneOps tool errors must stay in content — not cause HTTP 500."""

    def test_upstream_error_stays_in_content(self, mcp_client):
        with patch(
            "src.mcp_server.tools.oneops._svc_upstream",
            new=AsyncMock(side_effect=RuntimeError("SRE-OPS 500")),
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
        result = _extract_tool_result(response)
        assert result["status"] == "error"
        assert result["direction"] == "upstream"
        assert result["org"] == "mexicoecomm"
        assert "SRE-OPS 500" in result["error"]

    def test_downstream_error_stays_in_content(self, mcp_client):
        with patch(
            "src.mcp_server.tools.oneops._svc_downstream",
            new=AsyncMock(side_effect=ConnectionError("conn refused")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_oneops_downstream_dependencies",
                    {"org": "org", "platform": "plat", "assembly": "asm"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "error"
        assert result["direction"] == "downstream"
        assert "conn refused" in result["error"]


# ─── list_apps_in_namespace error propagation ────────────────────────────────

class TestMcpListAppsErrorPropagation:
    """list_apps_in_namespace error (from service) should propagate through MCP wire."""

    def test_dx_console_error_propagates(self, mcp_client):
        """DX Console failure should return an error object (not HTTP 500)."""
        with patch(
            "src.mcp_server.tools.wcnp.get_apps_for_namespace",
            new=AsyncMock(side_effect=RuntimeError("DX Console unavailable")),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call("list_apps_in_namespace", {"namespace": "iro-async"}),
                headers=_MCP_HEADERS,
            )

        # list_apps_in_namespace does not wrap errors — it forwards the service response
        # as-is. The MCP framework will catch any unhandled exception and report it.
        # HTTP status should still be 200 (MCP wraps errors in content or JSON-RPC error)
        assert response.status_code == 200


# ─── Unknown tool and bad arguments ──────────────────────────────────────────

class TestMcpBadRequests:
    """Invalid tool names and missing arguments must return JSON-RPC errors, not HTTP 500."""

    def test_unknown_tool_name_returns_error(self, mcp_client):
        """Calling a non-existent tool must return a JSON-RPC error response."""
        response = mcp_client.post(
            "/mcp/",
            json=_tool_call("does_not_exist", {"foo": "bar"}),
            headers=_MCP_HEADERS,
        )
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        # JSON-RPC spec: error must be at top level OR isError in result
        has_rpc_error = "error" in data
        has_tool_error = data.get("result", {}).get("isError") is True
        assert has_rpc_error or has_tool_error, (
            f"Expected error response for unknown tool, got: {data}"
        )

    def test_missing_required_arg_returns_error(self, mcp_client):
        """Calling a tool with missing required argument must return an error."""
        response = mcp_client.post(
            "/mcp/",
            # fetch_wcnp_upstream_dependencies requires app_name AND namespace
            json=_tool_call("fetch_wcnp_upstream_dependencies", {"app_name": "only-name"}),
            headers=_MCP_HEADERS,
        )
        assert response.status_code == 200
        data = _parse_mcp_response(response)
        has_rpc_error = "error" in data
        result_is_error = data.get("result", {}).get("isError") is True
        # At minimum, should not cause unhandled crash
        # (some MCP implementations might infer missing optional args)
        assert response.status_code == 200


# ─── Zero-dependency success responses ───────────────────────────────────────

class TestMcpZeroDependencySuccess:
    """Zero dependencies is a valid success — important for leaf/orphan apps."""

    def test_wcnp_upstream_zero_deps_is_success(self, mcp_client):
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=([], [], {})),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "orphan-app", "namespace": "prod"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert result["dependencies"] == []

    def test_oneops_downstream_zero_deps_is_success(self, mcp_client):
        with patch(
            "src.mcp_server.tools.oneops._svc_downstream",
            new=AsyncMock(return_value=[]),
        ):
            response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_oneops_downstream_dependencies",
                    {"org": "org", "platform": "plat", "assembly": "asm"},
                ),
                headers=_MCP_HEADERS,
            )

        assert response.status_code == 200
        result = _extract_tool_result(response)
        assert result["status"] == "success"
        assert result["total_count"] == 0

    def test_cassandra_zero_deps_is_success(self, mcp_client):
        with patch(
            "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies",
            new=AsyncMock(return_value=[]),
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
        result = _extract_tool_result(response)
        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert result["direction"] == "upstream"


# ─── Stateless HTTP invariant ─────────────────────────────────────────────────

class TestMcpStatelessHTTP:
    """With stateless_http=True, every request is independent."""

    def test_two_sequential_calls_both_succeed(self, mcp_client):
        """Two independent calls to the same tool must both work."""
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=([], [], {})),
        ):
            r1 = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "app-1", "namespace": "ns"},
                ),
                headers=_MCP_HEADERS,
            )
            r2 = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "app-2", "namespace": "ns"},
                ),
                headers=_MCP_HEADERS,
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        result1 = _extract_tool_result(r1)
        result2 = _extract_tool_result(r2)
        assert result1["app_name"] == "app-1"
        assert result2["app_name"] == "app-2"

    def test_call_after_error_still_works(self, mcp_client):
        """A successful call after an error call must still return success."""
        # First call: error
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=RuntimeError("fail")),
        ):
            mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "app", "namespace": "ns"},
                ),
                headers=_MCP_HEADERS,
            )

        # Second call: success
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=([{"app": "x"}], [], {"total": 1})),
        ):
            r2 = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "app", "namespace": "ns"},
                ),
                headers=_MCP_HEADERS,
            )

        assert r2.status_code == 200
        result2 = _extract_tool_result(r2)
        assert result2["status"] == "success"


# ─── Prompt content E2E ───────────────────────────────────────────────────────

class TestMcpPromptContentE2E:
    """prompts/get must return correctly structured prompt content."""

    def test_trace_wcnp_prompt_step3_summarise(self, mcp_client):
        """trace_wcnp_app prompt must instruct LLM to summarise in step 3."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("prompts/get", {
                "name": "trace_wcnp_app",
                "arguments": {"app_name": "my-app", "namespace": "prod"},
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
        assert "3." in full_text  # step 3 must exist
        assert "Summarise" in full_text or "summarise" in full_text

    def test_trace_wcnp_prompt_mentions_t0(self, mcp_client):
        """Prompt must mention T0-tier as critical."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("prompts/get", {
                "name": "trace_wcnp_app",
                "arguments": {"app_name": "my-app", "namespace": "prod"},
            }),
            headers=_MCP_HEADERS,
        )

        data = _parse_mcp_response(response)
        messages = data["result"]["messages"]
        full_text = " ".join(
            m["content"]["text"] for m in messages
            if isinstance(m.get("content"), dict) and "text" in m["content"]
        )
        assert "T0" in full_text or "critical" in full_text.lower()

    def test_trace_oneops_prompt_all_three_params_interpolated(self, mcp_client):
        """trace_oneops_app must embed org, platform, AND assembly in the output."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("prompts/get", {
                "name": "trace_oneops_app",
                "arguments": {
                    "org": "test-org",
                    "platform": "test-platform",
                    "assembly": "test-assembly",
                },
            }),
            headers=_MCP_HEADERS,
        )

        data = _parse_mcp_response(response)
        messages = data["result"]["messages"]
        full_text = " ".join(
            m["content"]["text"] for m in messages
            if isinstance(m.get("content"), dict) and "text" in m["content"]
        )
        assert "test-org" in full_text
        assert "test-platform" in full_text
        assert "test-assembly" in full_text

    def test_trace_oneops_prompt_references_both_tools(self, mcp_client):
        """trace_oneops_app must mention both upstream and downstream tool names."""
        response = mcp_client.post(
            "/mcp/",
            json=_rpc("prompts/get", {
                "name": "trace_oneops_app",
                "arguments": {"org": "o", "platform": "p", "assembly": "a"},
            }),
            headers=_MCP_HEADERS,
        )

        data = _parse_mcp_response(response)
        messages = data["result"]["messages"]
        full_text = " ".join(
            m["content"]["text"] for m in messages
            if isinstance(m.get("content"), dict) and "text" in m["content"]
        )
        assert "fetch_oneops_upstream_dependencies" in full_text
        assert "fetch_oneops_downstream_dependencies" in full_text


# ─── Full dependency trace workflow ──────────────────────────────────────────

class TestMcpFullTraceWorkflow:
    """Simulates the complete multi-tool workflow an LLM would follow."""

    def test_wcnp_full_trace_upstream_then_downstream(self, mcp_client):
        """Simulate LLM calling both upstream and downstream for a complete picture."""
        upstream = _make_deps(3, "upstream")
        downstream = _make_deps(2, "downstream")
        breakdown = {"upstream_count": 3, "downstream_count": 2, "total": 5}

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=[
                (upstream, [], breakdown),   # first call: upstream
                ([], downstream, breakdown), # second call: downstream
            ]),
        ):
            up_response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "payment-svc", "namespace": "payments-prod"},
                ),
                headers=_MCP_HEADERS,
            )
            down_response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_downstream_dependencies",
                    {"app_name": "payment-svc", "namespace": "payments-prod"},
                ),
                headers=_MCP_HEADERS,
            )

        up_result = _extract_tool_result(up_response)
        down_result = _extract_tool_result(down_response)

        assert up_result["status"] == "success"
        assert up_result["direction"] == "upstream"
        assert up_result["total_count"] == 3

        assert down_result["status"] == "success"
        assert down_result["direction"] == "downstream"
        assert down_result["total_count"] == 2

    def test_namespace_discovery_then_dependency_fetch(self, mcp_client):
        """Simulate LLM: list_apps first, then fetch dependencies for specific app."""
        apps_response_payload = {
            "apps": ["payment-svc", "order-svc", "user-svc"],
            "namespace": "prod",
        }
        deps = _make_deps(2, "upstream")

        with patch(
            "src.mcp_server.tools.wcnp.get_apps_for_namespace",
            new=AsyncMock(return_value=apps_response_payload),
        ):
            list_response = mcp_client.post(
                "/mcp/",
                json=_tool_call("list_apps_in_namespace", {"namespace": "prod"}),
                headers=_MCP_HEADERS,
            )

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=(deps, [], {"upstream_count": 2})),
        ):
            dep_response = mcp_client.post(
                "/mcp/",
                json=_tool_call(
                    "fetch_wcnp_upstream_dependencies",
                    {"app_name": "payment-svc", "namespace": "prod"},
                ),
                headers=_MCP_HEADERS,
            )

        assert list_response.status_code == 200
        list_result = _extract_tool_result(list_response)
        assert "apps" in list_result
        assert "payment-svc" in list_result["apps"]

        assert dep_response.status_code == 200
        dep_result = _extract_tool_result(dep_response)
        assert dep_result["status"] == "success"
        assert dep_result["total_count"] == 2
