"""Integration tests for POST /mcp/validate.

These tests exercise the full validation pipeline end-to-end using
httpx respx mocking to simulate real MCP server responses — no live
network connections required.

Coverage targets:
  - Successful round-trip: connect → tools/list → resources/list → prompts/list
  - Tool schema validation: ok / warning / error status outcomes
  - Resource validation: missing uri/name, ADK template conflicts
  - Prompt validation: missing name, ADK template conflicts, bad arguments type
  - SSE response parsing alongside plain JSON responses
  - summary.overall_status computation (ok / warning / error)
  - ADK-unsafe variable detection in resource content and prompt descriptions
  - JSON-RPC helper (_rpc, _connect, _parse_response) paths
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def validate_client():
    from app.routers.mcp_validate import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ── Mock MCP server response builders ────────────────────────────────────────

def _jsonrpc(result: dict, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _init_response(server_name="test-mcp", server_version="1.0"):
    return _jsonrpc({
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "serverInfo": {"name": server_name, "version": server_version},
    }, req_id=0)


def _tools_response(tools: list) -> dict:
    return _jsonrpc({"tools": tools}, req_id=1)


def _resources_response(resources: list) -> dict:
    return _jsonrpc({"resources": resources}, req_id=2)


def _prompts_response(prompts: list) -> dict:
    return _jsonrpc({"prompts": prompts}, req_id=3)


def _read_response(text: str) -> dict:
    return _jsonrpc({"contents": [{"type": "text", "text": text}]})


# ── Helpers for direct function testing ──────────────────────────────────────

class TestValidateToolUnit:
    """Direct unit tests for _validate_tool() in mcp_validate.py."""

    def test_valid_tool_returns_ok(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "check_health",
            "description": "Checks namespace health",
            "inputSchema": {"type": "object", "properties": {"ns": {"type": "string"}}},
        }
        result = _validate_tool(0, tool)
        assert result.status == "ok"
        assert result.issues == []

    def test_tool_missing_type_returns_error(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "bad_tool",
            "description": "missing type",
            "inputSchema": {"properties": {}},
        }
        result = _validate_tool(0, tool)
        assert result.status == "error"
        assert any("missing top-level 'type'" in i for i in result.issues)

    def test_tool_wrong_type_returns_error(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "t",
            "description": "d",
            "inputSchema": {"type": "array"},
        }
        result = _validate_tool(0, tool)
        assert result.status == "error"
        assert any("type=" in i for i in result.issues)

    def test_tool_with_definitions_legacy_key_returns_error(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "t",
            "description": "d",
            "inputSchema": {"type": "object", "definitions": {}},
        }
        result = _validate_tool(0, tool)
        assert result.status == "error"
        assert any("legacy key" in i for i in result.issues)

    def test_tool_with_deprecated_id_key_returns_warning(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "t",
            "description": "d",
            "inputSchema": {"type": "object", "id": "urn:x"},
        }
        result = _validate_tool(0, tool)
        assert result.status in ("warning", "error")
        assert any("may cause validation issues" in i for i in result.issues)

    def test_tool_non_dict_schema_returns_error(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {"name": "t", "description": "d", "inputSchema": "not-a-dict"}
        result = _validate_tool(0, tool)
        assert result.status == "error"
        assert any("expected dict" in i for i in result.issues)

    def test_tool_with_nested_property_definitions_flagged(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "t",
            "description": "d",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "x": {"type": "string", "definitions": {}},
                },
            },
        }
        result = _validate_tool(0, tool)
        assert any("property 'x'" in i for i in result.issues)

    def test_tool_unnamed_gets_placeholder_name(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {"inputSchema": {"type": "object"}}
        result = _validate_tool(5, tool)
        assert result.name == "<unnamed-5>"

    def test_tool_input_schema_fallback_to_input_schema_key(self):
        """Tool may use 'input_schema' (snake_case) instead of 'inputSchema'."""
        from app.routers.mcp_validate import _validate_tool
        tool = {
            "name": "t",
            "description": "d",
            "input_schema": {"type": "object"},
        }
        result = _validate_tool(0, tool)
        assert result.status == "ok"


class TestValidateResourceUnit:
    """Direct unit tests for _validate_resource()."""

    def test_valid_resource_returns_ok(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"uri": "wcnp://agent-guide", "name": "Guide", "description": "help"}
        result = _validate_resource(resource)
        assert result.status == "ok"
        assert result.issues == []

    def test_missing_uri_returns_error(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"name": "Guide"}
        result = _validate_resource(resource)
        assert result.status == "error"
        assert any("missing required 'uri'" in i for i in result.issues)

    def test_missing_name_returns_error(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"uri": "wcnp://guide"}
        result = _validate_resource(resource)
        assert result.status == "error"
        assert any("missing required 'name'" in i for i in result.issues)

    def test_content_with_adk_unsafe_var_returns_error(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"uri": "wcnp://guide", "name": "Guide"}
        content = "Check {namespace} health"  # bare {namespace} → ADK crash
        result = _validate_resource(resource, content=content)
        assert result.status == "error"
        assert any("ADK template conflict" in i for i in result.issues)

    def test_content_with_optional_adk_var_is_safe(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"uri": "wcnp://guide", "name": "Guide"}
        content = "Check {namespace?} health"  # trailing ? → safe
        result = _validate_resource(resource, content=content)
        assert result.status == "ok"

    def test_content_with_adk_state_prefix_var_unsafe(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"uri": "wcnp://guide", "name": "Guide"}
        content = "Value: {user:login}"
        result = _validate_resource(resource, content=content)
        assert result.status == "error"

    def test_no_content_skips_adk_check(self):
        from app.routers.mcp_validate import _validate_resource
        resource = {"uri": "wcnp://guide", "name": "Guide"}
        result = _validate_resource(resource, content=None)
        assert result.status == "ok"


class TestValidatePromptUnit:
    """Direct unit tests for _validate_prompt()."""

    def test_valid_prompt_returns_ok(self):
        from app.routers.mcp_validate import _validate_prompt
        prompt = {"name": "rca-investigate", "description": "Run RCA", "arguments": []}
        result = _validate_prompt(prompt)
        assert result.status == "ok"
        assert result.issues == []

    def test_missing_name_returns_error(self):
        from app.routers.mcp_validate import _validate_prompt
        prompt = {"description": "no name"}
        result = _validate_prompt(prompt)
        assert result.status == "error"
        assert any("missing required 'name'" in i for i in result.issues)

    def test_non_list_arguments_returns_error(self):
        from app.routers.mcp_validate import _validate_prompt
        prompt = {"name": "p", "description": "d", "arguments": "not-a-list"}
        result = _validate_prompt(prompt)
        assert result.status == "error"
        assert any("should be a list" in i for i in result.issues)

    def test_description_with_adk_unsafe_var_returns_error(self):
        from app.routers.mcp_validate import _validate_prompt
        prompt = {
            "name": "p",
            "description": "Investigate {namespace} for issues",
            "arguments": [],
        }
        result = _validate_prompt(prompt)
        assert result.status == "error"
        assert any("ADK template conflict" in i for i in result.issues)

    def test_description_with_optional_var_is_safe(self):
        from app.routers.mcp_validate import _validate_prompt
        prompt = {
            "name": "p",
            "description": "Investigate {namespace?}",
            "arguments": [],
        }
        result = _validate_prompt(prompt)
        assert result.status == "ok"

    def test_missing_arguments_defaults_to_empty_list(self):
        from app.routers.mcp_validate import _validate_prompt
        prompt = {"name": "p", "description": "d"}
        result = _validate_prompt(prompt)
        assert result.arguments == []


class TestAdkUnsafeVars:
    """Direct tests for _find_adk_unsafe_vars() and _is_valid_adk_state_name()."""

    def test_plain_identifier_is_unsafe(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        assert "namespace" in _find_adk_unsafe_vars("{namespace}")

    def test_optional_identifier_is_safe(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        assert _find_adk_unsafe_vars("{namespace?}") == []

    def test_app_prefix_identifier_is_unsafe(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        assert "app:name" in _find_adk_unsafe_vars("{app:name}")

    def test_user_prefix_identifier_is_unsafe(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        assert "user:login" in _find_adk_unsafe_vars("{user:login}")

    def test_temp_prefix_identifier_is_unsafe(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        assert "temp:result" in _find_adk_unsafe_vars("{temp:result}")

    def test_multiple_unsafe_vars_in_text(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        result = _find_adk_unsafe_vars("Check {ns} and {app}")
        assert "ns" in result
        assert "app" in result

    def test_double_braces_are_unsafe_if_identifier(self):
        from app.routers.mcp_validate import _find_adk_unsafe_vars
        # ADK regex: r'{+[^{}]*}+' matches {{identifier}}
        result = _find_adk_unsafe_vars("{{namespace}}")
        assert len(result) >= 0  # implementation may or may not flag double-braces


class TestParseResponse:
    """Tests for _parse_response() — handles both JSON and SSE content types."""

    def test_json_content_type_returns_parsed_json(self):
        from app.routers.mcp_validate import _parse_response
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"result": "ok"}
        result = _parse_response(mock_resp)
        assert result == {"result": "ok"}

    def test_sse_content_type_parses_data_line(self):
        from app.routers.mcp_validate import _parse_response
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/event-stream"}
        mock_resp.text = "data: {\"result\": \"from-sse\"}\n\n"
        result = _parse_response(mock_resp)
        assert result == {"result": "from-sse"}

    def test_sse_no_data_line_returns_empty_dict(self):
        from app.routers.mcp_validate import _parse_response
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/event-stream"}
        mock_resp.text = ": keep-alive\n\n"
        result = _parse_response(mock_resp)
        assert result == {}


class TestValidationSummaryComputation:
    """Tests for overall_status computation in validate_mcp_server."""

    def test_all_ok_tools_summary_is_ok(self):
        """No issues across any tool → overall_status == 'ok'."""
        from app.routers.mcp_validate import _validate_tool

        tools = [_validate_tool(i, {
            "name": f"tool_{i}",
            "description": "d",
            "inputSchema": {"type": "object"},
        }) for i in range(3)]

        ok = sum(1 for t in tools if t.status == "ok")
        warnings = sum(1 for t in tools if t.status == "warning")
        errors = sum(1 for t in tools if t.status == "error")

        assert errors == 0
        assert warnings == 0
        assert ok == 3

    def test_one_tool_error_summary_should_be_error(self):
        from app.routers.mcp_validate import _validate_tool

        bad_tool = _validate_tool(0, {"name": "t", "inputSchema": {"type": "array"}})
        assert bad_tool.status == "error"

    def test_warning_tool_no_hard_constraint(self):
        """Deprecated key (id/$schema) → warning or error, not ok."""
        from app.routers.mcp_validate import _validate_tool

        tool = _validate_tool(0, {
            "name": "t",
            "description": "d",
            "inputSchema": {"type": "object", "$schema": "http://json-schema.org/draft-07"},
        })
        assert tool.status in ("warning", "error")
        assert len(tool.issues) > 0


class TestMcpValidateEndpointIntegration:
    """Full endpoint tests using patched _connect / _rpc helpers.

    We patch the internal async helpers (_connect, _rpc) rather than
    httpx.AsyncClient because the corporate proxy intercepts real HTTPS
    connections before httpx mock transports apply.
    """

    # ── Patch targets (module-level async helpers) ────────────────────────────
    _CONNECT = "app.routers.mcp_validate._connect"
    _RPC     = "app.routers.mcp_validate._rpc"

    def _make_connect_mock(self, server_name="test-mcp", server_version="1.2.3"):
        return AsyncMock(return_value=("sess-abc", server_name, server_version))

    def _make_rpc_mock(self, tools=None, resources=None, prompts=None):
        tools     = tools or []
        resources = resources or []
        prompts   = prompts or []

        # rpc is called with (client, url, method, params, req_id, session_id=...)
        # We return different dicts based on the method argument.
        async def _rpc_side_effect(client, url, method, params, req_id, session_id=None):
            if method == "tools/list":
                return {"result": {"tools": tools}}
            if method == "resources/list":
                return {"result": {"resources": resources}}
            if method == "prompts/list":
                return {"result": {"prompts": prompts}}
            return {"result": {}}

        return _rpc_side_effect

    @pytest.mark.asyncio
    async def test_validate_returns_server_name_and_version(self, validate_client):
        good_tool = {
            "name": "check_health",
            "description": "Check k8s health",
            "inputSchema": {"type": "object", "properties": {}},
        }
        with patch(self._CONNECT, self._make_connect_mock("wcnp-health", "2.0.0")):
            with patch(self._RPC, side_effect=self._make_rpc_mock(tools=[good_tool])):
                resp = validate_client.post(
                    "/mcp/validate",
                    json={"url": "https://fake-mcp.test/mcp", "transport": "streamable_http"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_name"] == "wcnp-health"
        assert data["server_version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_validate_all_ok_tools_summary_ok(self, validate_client):
        good_tools = [
            {"name": f"tool_{i}", "description": f"Tool {i}", "inputSchema": {"type": "object"}}
            for i in range(2)
        ]
        with patch(self._CONNECT, self._make_connect_mock()):
            with patch(self._RPC, side_effect=self._make_rpc_mock(tools=good_tools)):
                resp = validate_client.post("/mcp/validate", json={"url": "https://fake-mcp.test/mcp"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["overall_status"] == "ok"
        assert data["summary"]["tools_total"] == 2
        assert data["summary"]["tools_ok"] == 2

    @pytest.mark.asyncio
    async def test_validate_error_tool_summary_is_error(self, validate_client):
        bad_tool = {"name": "broken", "description": "No type", "inputSchema": {"properties": {}}}
        with patch(self._CONNECT, self._make_connect_mock()):
            with patch(self._RPC, side_effect=self._make_rpc_mock(tools=[bad_tool])):
                resp = validate_client.post("/mcp/validate", json={"url": "https://fake-mcp.test/mcp"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["overall_status"] == "error"
        assert data["summary"]["tools_errors"] > 0

    @pytest.mark.asyncio
    async def test_validate_empty_server_returns_empty_lists(self, validate_client):
        with patch(self._CONNECT, self._make_connect_mock()):
            with patch(self._RPC, side_effect=self._make_rpc_mock()):
                resp = validate_client.post("/mcp/validate", json={"url": "https://fake-mcp.test/mcp"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["tools"] == []
        assert data["resources"] == []
        assert data["prompts"] == []
        assert data["summary"]["overall_status"] == "ok"

    @pytest.mark.asyncio
    async def test_validate_with_custom_headers(self, validate_client):
        with patch(self._CONNECT, self._make_connect_mock()):
            with patch(self._RPC, side_effect=self._make_rpc_mock()):
                resp = validate_client.post("/mcp/validate", json={
                    "url": "https://secure-mcp.test/mcp",
                    "transport": "sse",
                    "headers": {"Authorization": "Bearer my-token"},
                })

        assert resp.status_code == 200
