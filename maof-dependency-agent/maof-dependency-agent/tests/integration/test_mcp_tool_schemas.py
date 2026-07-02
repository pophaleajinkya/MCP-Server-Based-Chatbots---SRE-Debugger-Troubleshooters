"""Integration tests for MCP tool input schemas (tools/list inputSchema).

Strategy:
  - Use the session-scoped `mcp_client` (stateless HTTP, no session ID required)
  - Call tools/list and validate the inputSchema for every tool:
      * required parameters exist
      * parameter types are correct (string, not enum/Optional)
      * no extra 'direction' parameter on explicit upstream/downstream tools
  - Validates MCP wire compliance for structured tool input
"""
import json
import pytest


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


def _get_tools(mcp_client) -> dict:
    """Return {tool_name: tool_dict} from tools/list."""
    response = mcp_client.post("/mcp/", json=_rpc("tools/list"), headers=_MCP_HEADERS)
    assert response.status_code == 200
    data = _parse_mcp_response(response)
    return {t["name"]: t for t in data["result"]["tools"]}


# ─── list_apps_in_namespace schema ───────────────────────────────────────────

class TestListAppsInNamespaceSchema:
    """Input schema for list_apps_in_namespace."""

    def test_has_input_schema(self, mcp_client):
        tools = _get_tools(mcp_client)
        tool = tools["list_apps_in_namespace"]
        assert "inputSchema" in tool

    def test_requires_namespace_parameter(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["list_apps_in_namespace"]["inputSchema"]
        props = schema.get("properties", {})
        assert "namespace" in props, "list_apps_in_namespace must require 'namespace'"

    def test_namespace_is_string_type(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["list_apps_in_namespace"]["inputSchema"]
        ns_prop = schema["properties"]["namespace"]
        assert ns_prop.get("type") == "string"

    def test_no_direction_parameter(self, mcp_client):
        """list_apps_in_namespace takes no direction — namespace only."""
        tools = _get_tools(mcp_client)
        schema = tools["list_apps_in_namespace"]["inputSchema"]
        props = schema.get("properties", {})
        assert "direction" not in props


# ─── fetch_wcnp_upstream_dependencies schema ─────────────────────────────────

class TestWcnpUpstreamSchema:
    """Input schema for fetch_wcnp_upstream_dependencies."""

    def test_has_input_schema(self, mcp_client):
        tools = _get_tools(mcp_client)
        assert "inputSchema" in tools["fetch_wcnp_upstream_dependencies"]

    def test_requires_app_name_and_namespace(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_wcnp_upstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "app_name" in props
        assert "namespace" in props

    def test_app_name_and_namespace_are_strings(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_wcnp_upstream_dependencies"]["inputSchema"]
        props = schema["properties"]
        assert props["app_name"].get("type") == "string"
        assert props["namespace"].get("type") == "string"

    def test_no_direction_in_schema(self, mcp_client):
        """Direction is encoded in the tool name — must NOT be a parameter."""
        tools = _get_tools(mcp_client)
        schema = tools["fetch_wcnp_upstream_dependencies"]["inputSchema"]
        assert "direction" not in schema.get("properties", {})


# ─── fetch_wcnp_downstream_dependencies schema ───────────────────────────────

class TestWcnpDownstreamSchema:
    """Input schema for fetch_wcnp_downstream_dependencies."""

    def test_has_app_name_and_namespace(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_wcnp_downstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "app_name" in props
        assert "namespace" in props

    def test_no_direction_in_schema(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_wcnp_downstream_dependencies"]["inputSchema"]
        assert "direction" not in schema.get("properties", {})

    def test_schema_same_structure_as_upstream(self, mcp_client):
        """Upstream and downstream WCNP tools should have the same input schema shape."""
        tools = _get_tools(mcp_client)
        up_props = set(tools["fetch_wcnp_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        down_props = set(tools["fetch_wcnp_downstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        assert up_props == down_props


# ─── fetch_oneops_upstream_dependencies schema ───────────────────────────────

class TestOneopsUpstreamSchema:
    """Input schema for fetch_oneops_upstream_dependencies."""

    def test_has_three_required_params(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_oneops_upstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "org" in props
        assert "platform" in props
        assert "assembly" in props

    def test_all_params_are_strings(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_oneops_upstream_dependencies"]["inputSchema"]
        props = schema["properties"]
        for param in ("org", "platform", "assembly"):
            assert props[param].get("type") == "string", f"'{param}' must be string type"

    def test_no_direction_in_schema(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_oneops_upstream_dependencies"]["inputSchema"]
        assert "direction" not in schema.get("properties", {})


# ─── fetch_oneops_downstream_dependencies schema ─────────────────────────────

class TestOneopsDownstreamSchema:
    """Input schema for fetch_oneops_downstream_dependencies."""

    def test_has_same_schema_structure_as_upstream(self, mcp_client):
        tools = _get_tools(mcp_client)
        up_props = set(tools["fetch_oneops_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        down_props = set(tools["fetch_oneops_downstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        assert up_props == down_props


# ─── fetch_cassandra_upstream_dependencies schema ────────────────────────────

class TestCassandraSchema:
    """Input schema for fetch_cassandra_upstream_dependencies."""

    def test_requires_assembly_and_platform(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_cassandra_upstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "assembly" in props
        assert "platform" in props

    def test_no_azure_params(self, mcp_client):
        """Cassandra uses assembly/platform — must not have Azure resource_group params."""
        tools = _get_tools(mcp_client)
        schema = tools["fetch_cassandra_upstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "resource_group" not in props
        assert "subscription_id" not in props
        assert "database_name" not in props

    def test_assembly_and_platform_are_strings(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_cassandra_upstream_dependencies"]["inputSchema"]
        props = schema["properties"]
        assert props["assembly"].get("type") == "string"
        assert props["platform"].get("type") == "string"


# ─── fetch_meghacache_upstream_dependencies schema ───────────────────────────

class TestMeghacacheSchema:
    """Input schema for fetch_meghacache_upstream_dependencies."""

    def test_has_same_params_as_cassandra(self, mcp_client):
        """MeghaCache uses the same assembly/platform params as Cassandra."""
        tools = _get_tools(mcp_client)
        cassandra_props = set(tools["fetch_cassandra_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        megha_props = set(tools["fetch_meghacache_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        assert cassandra_props == megha_props


# ─── fetch_cosmos_upstream_dependencies schema ────────────────────────────────

class TestCosmosSchema:
    """Input schema for fetch_cosmos_upstream_dependencies."""

    def test_requires_azure_params(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_cosmos_upstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "resource_group" in props
        assert "subscription_id" in props
        assert "database_name" in props

    def test_no_assembly_or_platform(self, mcp_client):
        """Cosmos uses Azure params — must not have OneOps assembly/platform."""
        tools = _get_tools(mcp_client)
        schema = tools["fetch_cosmos_upstream_dependencies"]["inputSchema"]
        props = schema.get("properties", {})
        assert "assembly" not in props
        assert "platform" not in props

    def test_all_azure_params_are_strings(self, mcp_client):
        tools = _get_tools(mcp_client)
        schema = tools["fetch_cosmos_upstream_dependencies"]["inputSchema"]
        props = schema["properties"]
        for param in ("resource_group", "subscription_id", "database_name"):
            assert props[param].get("type") == "string"


# ─── fetch_sqlserver_upstream_dependencies schema ────────────────────────────

class TestSqlserverSchema:
    """Input schema for fetch_sqlserver_upstream_dependencies."""

    def test_has_same_params_as_cosmos(self, mcp_client):
        """SQL Server uses the same Azure params as Cosmos DB."""
        tools = _get_tools(mcp_client)
        cosmos_props = set(tools["fetch_cosmos_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        sql_props = set(tools["fetch_sqlserver_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        assert cosmos_props == sql_props


# ─── Cross-schema invariants ──────────────────────────────────────────────────

class TestCrossSchemaInvariants:
    """Invariants that apply to all 9 tool schemas."""

    def test_all_tools_have_input_schema(self, mcp_client):
        """Every registered tool must have an inputSchema."""
        tools = _get_tools(mcp_client)
        for name, tool in tools.items():
            assert "inputSchema" in tool, f"Tool '{name}' missing inputSchema"

    def test_no_tool_accepts_direction_parameter(self, mcp_client):
        """No tool should accept a 'direction' parameter — it's encoded in tool name."""
        tools = _get_tools(mcp_client)
        for name, tool in tools.items():
            props = tool.get("inputSchema", {}).get("properties", {})
            assert "direction" not in props, (
                f"Tool '{name}' should not have a 'direction' parameter"
            )

    def test_all_tools_have_non_empty_description(self, mcp_client):
        """Every tool must have a non-empty description for LLM routing."""
        tools = _get_tools(mcp_client)
        for name, tool in tools.items():
            assert tool.get("description"), f"Tool '{name}' has empty description"
            assert len(tool["description"]) > 20, (
                f"Tool '{name}' description too short to be useful"
            )

    def test_managed_service_tools_have_different_params_from_wcnp(self, mcp_client):
        """Managed service tools (assembly/platform or Azure) differ from WCNP (app_name/namespace)."""
        tools = _get_tools(mcp_client)
        wcnp_props = set(tools["fetch_wcnp_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        cassandra_props = set(tools["fetch_cassandra_upstream_dependencies"]["inputSchema"].get("properties", {}).keys())
        assert not wcnp_props.intersection(cassandra_props), (
            "WCNP and Cassandra tools should have distinct parameter sets"
        )

    def test_prompt_trace_wcnp_app_has_argument_definitions(self, mcp_client):
        """prompts/list must return argument definitions for trace_wcnp_app."""
        response = mcp_client.post("/mcp/", json=_rpc("prompts/list"), headers=_MCP_HEADERS)
        data = _parse_mcp_response(response)
        prompts = {p["name"]: p for p in data["result"]["prompts"]}
        wcnp_prompt = prompts.get("trace_wcnp_app", {})
        arguments = wcnp_prompt.get("arguments", [])
        arg_names = [a["name"] for a in arguments]
        assert "app_name" in arg_names
        assert "namespace" in arg_names

    def test_prompt_trace_oneops_app_has_argument_definitions(self, mcp_client):
        """prompts/list must return argument definitions for trace_oneops_app."""
        response = mcp_client.post("/mcp/", json=_rpc("prompts/list"), headers=_MCP_HEADERS)
        data = _parse_mcp_response(response)
        prompts = {p["name"]: p for p in data["result"]["prompts"]}
        oneops_prompt = prompts.get("trace_oneops_app", {})
        arguments = oneops_prompt.get("arguments", [])
        arg_names = [a["name"] for a in arguments]
        assert "org" in arg_names
        assert "platform" in arg_names
        assert "assembly" in arg_names
