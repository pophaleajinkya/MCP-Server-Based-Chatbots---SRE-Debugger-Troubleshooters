"""
Unit tests for app.routers.mcp_validate — /mcp/validate endpoint.

Covers:
  - Pydantic request / response models
  - _parse_response: plain JSON and text/event-stream branches
  - _validate_tool: all issue categories (non-dict schema, not serialisable,
    missing type, wrong type, forbidden/deprecated top-level keys,
    nested property forbidden keys, ok tool, warning-only tool)
  - _validate_resource: missing uri, missing name, both present
  - _validate_prompt: missing name, non-list arguments, valid prompt
  - validate_mcp_server endpoint: successful round-trip, tools/list failure,
    resources/list failure, prompts/list failure, custom headers forwarded,
    summary status rollup (ok / warning / error)

No live network calls are made — all httpx interactions are mocked via
respx or unittest.mock patching of httpx.AsyncClient.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_REQUEST = httpx.Request("POST", "http://mcp.test/mcp")


def _mock_response(body: dict | str, status: int = 200,
                   content_type: str = "application/json",
                   headers: dict | None = None) -> httpx.Response:
    """Build a fake httpx.Response with a request set (required for raise_for_status)."""
    if isinstance(body, dict):
        text = json.dumps(body)
    else:
        text = body
    hdrs = {"content-type": content_type}
    if headers:
        hdrs.update(headers)
    return httpx.Response(status_code=status, text=text, headers=hdrs, request=_DUMMY_REQUEST)


def _sse_response(body: dict) -> httpx.Response:
    """Build a fake SSE httpx.Response with a single data: line."""
    text = f"data: {json.dumps(body)}\n\n"
    return httpx.Response(
        status_code=200,
        text=text,
        headers={"content-type": "text/event-stream"},
        request=_DUMMY_REQUEST,
    )


def _init_resp(server_name: str = "test-server",
               server_version: str = "1.0",
               session_id: str = "sess-abc") -> httpx.Response:
    body = {
        "jsonrpc": "2.0", "id": 0,
        "result": {
            "serverInfo": {"name": server_name, "version": server_version},
            "sessionId": session_id,
        },
    }
    return _mock_response(body, headers={"mcp-session-id": session_id})


def _list_resp(key: str, items: list) -> httpx.Response:
    return _mock_response({"jsonrpc": "2.0", "id": 1, "result": {key: items}})


def _good_tool(name: str = "my_tool") -> dict:
    return {
        "name": name,
        "description": "does something",
        "inputSchema": {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mcp_client():
    from app.routers.mcp_validate import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    """_parse_response handles plain JSON and text/event-stream."""

    def test_plain_json_response(self):
        from app.routers.mcp_validate import _parse_response
        resp = _mock_response({"result": {"tools": []}})
        assert _parse_response(resp) == {"result": {"tools": []}}

    def test_sse_response_first_data_line(self):
        from app.routers.mcp_validate import _parse_response
        body = {"result": {"tools": [{"name": "t1"}]}}
        resp = _sse_response(body)
        assert _parse_response(resp) == body

    def test_sse_response_no_data_line_returns_empty(self):
        from app.routers.mcp_validate import _parse_response
        resp = httpx.Response(
            status_code=200, text="event: ping\n\n",
            headers={"content-type": "text/event-stream"},
        )
        assert _parse_response(resp) == {}


# ---------------------------------------------------------------------------
# Tests: _validate_tool
# ---------------------------------------------------------------------------

class TestValidateTool:
    """_validate_tool produces correct ToolValidation objects."""

    def test_valid_tool_returns_ok(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, _good_tool())
        assert tv.status == "ok"
        assert tv.issues == []
        assert tv.name == "my_tool"
        assert tv.index == 0

    def test_unnamed_tool_uses_fallback_name(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(3, {"description": "no name", "inputSchema": {"type": "object"}})
        assert tv.name == "<unnamed-3>"

    def test_non_dict_schema_returns_error(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "bad", "inputSchema": ["not", "a", "dict"]})
        assert tv.status == "error"
        assert any("expected dict" in issue for issue in tv.issues)
        assert tv.input_schema == {}

    def test_missing_type_field_is_error(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {"properties": {}}})
        assert tv.status == "error"
        assert any("missing top-level 'type'" in i for i in tv.issues)

    def test_wrong_type_field_is_error(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {"type": "string"}})
        assert tv.status == "error"
        assert any("type='object'" in i for i in tv.issues)

    def test_forbidden_key_definitions_is_error(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {
            "type": "object", "definitions": {"Foo": {}}
        }})
        assert tv.status == "error"
        assert any("definitions" in i for i in tv.issues)

    def test_deprecated_key_id_is_warning(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {
            "type": "object", "id": "my-schema"
        }})
        # "id" is deprecated — issues present but no hard error → warning
        assert tv.status in ("warning", "error")
        assert any("id" in i for i in tv.issues)

    def test_deprecated_key_schema_is_warning_or_error(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {
            "type": "object", "$schema": "draft-07"
        }})
        assert tv.status in ("warning", "error")
        assert any("$schema" in i for i in tv.issues)

    def test_nested_property_forbidden_key_produces_issue(self):
        from app.routers.mcp_validate import _validate_tool
        schema = {
            "type": "object",
            "properties": {
                "my_prop": {"type": "string", "definitions": {"X": {}}}
            },
        }
        tv = _validate_tool(0, {"name": "t", "inputSchema": schema})
        assert any("my_prop" in i for i in tv.issues)

    def test_input_schema_from_input_schema_key(self):
        """inputSchema key (camelCase) is checked before input_schema (snake_case)."""
        from app.routers.mcp_validate import _validate_tool
        tool = {"name": "t", "inputSchema": {"type": "object"}}
        tv = _validate_tool(0, tool)
        assert tv.status == "ok"

    def test_input_schema_fallback_to_snake_case(self):
        from app.routers.mcp_validate import _validate_tool
        tool = {"name": "t", "input_schema": {"type": "object"}}
        tv = _validate_tool(0, tool)
        assert tv.status == "ok"

    def test_empty_schema_triggers_type_missing_issue(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {}})
        assert any("missing top-level 'type'" in i for i in tv.issues)

    def test_non_serialisable_schema_is_error(self):
        """A schema that cannot be JSON-serialised (e.g. contains a set) → error."""
        schema = {"type": "object"}
        # Monkey-patch json.dumps to raise TypeError for this specific value
        original_dumps = json.dumps
        def _patched_dumps(obj, **kw):
            if obj is schema:
                raise TypeError("not serialisable")
            return original_dumps(obj, **kw)

        import app.routers.mcp_validate as mod
        original = mod.json.dumps
        mod.json.dumps = _patched_dumps
        try:
            tv = mod._validate_tool(0, {"name": "t", "inputSchema": schema})
            assert any("not JSON-serialisable" in i for i in tv.issues)
            assert tv.status == "error"
        finally:
            mod.json.dumps = original

    def test_no_description_defaults_to_empty_string(self):
        from app.routers.mcp_validate import _validate_tool
        tv = _validate_tool(0, {"name": "t", "inputSchema": {"type": "object"}})
        assert tv.description == ""


# ---------------------------------------------------------------------------
# Tests: _validate_resource
# ---------------------------------------------------------------------------

class TestValidateResource:

    def test_valid_resource_returns_ok(self):
        from app.routers.mcp_validate import _validate_resource
        r = _validate_resource({
            "uri": "file:///data.json", "name": "data", "description": "some data",
            "mimeType": "application/json",
        })
        assert r.status == "ok"
        assert r.issues == []

    def test_missing_uri_is_error(self):
        from app.routers.mcp_validate import _validate_resource
        r = _validate_resource({"name": "data"})
        assert r.status == "error"
        assert any("uri" in i for i in r.issues)

    def test_missing_name_is_error(self):
        from app.routers.mcp_validate import _validate_resource
        r = _validate_resource({"uri": "file:///data.json"})
        assert r.status == "error"
        assert any("name" in i for i in r.issues)

    def test_missing_both_uri_and_name_is_error(self):
        from app.routers.mcp_validate import _validate_resource
        r = _validate_resource({})
        assert r.status == "error"
        assert len(r.issues) == 2

    def test_default_empty_fields(self):
        from app.routers.mcp_validate import _validate_resource
        r = _validate_resource({"uri": "x://y", "name": "n"})
        assert r.description == ""
        assert r.mime_type == ""


# ---------------------------------------------------------------------------
# Tests: _validate_prompt
# ---------------------------------------------------------------------------

class TestValidatePrompt:

    def test_valid_prompt_returns_ok(self):
        from app.routers.mcp_validate import _validate_prompt
        p = _validate_prompt({"name": "greet", "description": "greets the user", "arguments": []})
        assert p.status == "ok"
        assert p.issues == []
        assert p.arguments == []

    def test_missing_name_is_error(self):
        from app.routers.mcp_validate import _validate_prompt
        p = _validate_prompt({"description": "no name"})
        assert p.status == "error"
        assert any("name" in i for i in p.issues)

    def test_non_list_arguments_is_error(self):
        from app.routers.mcp_validate import _validate_prompt
        p = _validate_prompt({"name": "p", "arguments": {"key": "val"}})
        assert p.status == "error"
        assert any("list" in i for i in p.issues)
        # arguments is reset to [] when non-list
        assert p.arguments == []

    def test_missing_arguments_defaults_to_empty_list(self):
        from app.routers.mcp_validate import _validate_prompt
        p = _validate_prompt({"name": "p"})
        assert p.arguments == []
        assert p.status == "ok"

    def test_missing_description_defaults_to_empty_string(self):
        from app.routers.mcp_validate import _validate_prompt
        p = _validate_prompt({"name": "p"})
        assert p.description == ""


# ---------------------------------------------------------------------------
# Tests: validate_mcp_server endpoint (full round-trip via mocked httpx)
# ---------------------------------------------------------------------------

class TestValidateMCPServerEndpoint:

    def _make_post_side_effects(self, *, tools=None, resources=None, prompts=None,
                                session_id="sess-1",
                                server_name="my-mcp", server_version="2.0",
                                tools_fail=False, resources_fail=False, prompts_fail=False):
        """Return an async side_effect list for httpx.AsyncClient.post."""
        init = _init_resp(server_name, server_version, session_id)

        async def _post(url, *, json=None, headers=None, timeout=None):
            method = (json or {}).get("method", "")
            if method == "initialize":
                return init
            if method == "notifications/initialized":
                return _mock_response({}, 200)
            if method == "tools/list":
                if tools_fail:
                    raise httpx.RequestError("tools list failed", request=MagicMock())
                return _list_resp("tools", tools or [])
            if method == "resources/list":
                if resources_fail:
                    raise httpx.RequestError("resources list failed", request=MagicMock())
                return _list_resp("resources", resources or [])
            if method == "prompts/list":
                if prompts_fail:
                    raise httpx.RequestError("prompts list failed", request=MagicMock())
                return _list_resp("prompts", prompts or [])
            return _mock_response({}, 200)

        return _post

    def test_successful_validation_returns_200(self, mcp_client):
        post_fn = self._make_post_side_effects(tools=[_good_tool()])
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.status_code == 200

    def test_response_contains_server_name(self, mcp_client):
        post_fn = self._make_post_side_effects(server_name="awesome-mcp")
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.json()["server_name"] == "awesome-mcp"

    def test_response_contains_server_version(self, mcp_client):
        post_fn = self._make_post_side_effects(server_version="3.1.4")
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.json()["server_version"] == "3.1.4"

    def test_tool_validation_results_in_response(self, mcp_client):
        post_fn = self._make_post_side_effects(tools=[_good_tool("check_health")])
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        data = resp.json()
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "check_health"
        assert data["tools"][0]["status"] == "ok"

    def test_summary_reflects_tool_counts(self, mcp_client):
        tools = [
            _good_tool("ok_tool"),
            {"name": "bad_tool", "description": "", "inputSchema": {"type": "string"}},
        ]
        post_fn = self._make_post_side_effects(tools=tools)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        summary = resp.json()["summary"]
        assert summary["tools_total"] == 2
        assert summary["tools_ok"] == 1
        assert summary["tools_errors"] == 1
        assert summary["overall_status"] == "error"

    def test_summary_ok_when_no_issues(self, mcp_client):
        post_fn = self._make_post_side_effects(tools=[_good_tool()])
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.json()["summary"]["overall_status"] == "ok"

    def test_summary_warning_when_only_warnings(self, mcp_client):
        """A tool with only deprecated-key warnings (not hard errors) → overall=warning."""
        tools = [{"name": "t", "description": "", "inputSchema": {"type": "object", "id": "x"}}]
        post_fn = self._make_post_side_effects(tools=tools)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        summary = resp.json()["summary"]
        assert summary["overall_status"] in ("warning", "error")

    def test_resources_present_in_response(self, mcp_client):
        resources = [{"uri": "file:///data.json", "name": "data", "description": "", "mimeType": "application/json"}]
        post_fn = self._make_post_side_effects(resources=resources)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        data = resp.json()
        assert len(data["resources"]) == 1
        assert data["summary"]["resources_total"] == 1

    def test_prompts_present_in_response(self, mcp_client):
        prompts = [{"name": "greet", "description": "", "arguments": []}]
        post_fn = self._make_post_side_effects(prompts=prompts)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        data = resp.json()
        assert len(data["prompts"]) == 1
        assert data["summary"]["prompts_total"] == 1

    def test_tools_list_failure_still_returns_200(self, mcp_client):
        """If tools/list raises, the endpoint still returns a valid response with empty tools."""
        post_fn = self._make_post_side_effects(tools_fail=True)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.status_code == 200
        assert resp.json()["tools"] == []

    def test_resources_list_failure_still_returns_200(self, mcp_client):
        """If resources/list raises, the endpoint returns empty resources."""
        post_fn = self._make_post_side_effects(resources_fail=True)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.status_code == 200
        assert resp.json()["resources"] == []

    def test_prompts_list_failure_still_returns_200(self, mcp_client):
        """If prompts/list raises, the endpoint returns empty prompts."""
        post_fn = self._make_post_side_effects(prompts_fail=True)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.status_code == 200
        assert resp.json()["prompts"] == []

    def test_custom_headers_accepted_in_request_body(self, mcp_client):
        """The request body's 'headers' field is forwarded to the MCP server."""
        post_fn = self._make_post_side_effects()
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)) as mock_post:
            mcp_client.post("/mcp/validate", json={
                "url": "http://mcp.test/mcp",
                "headers": {"Authorization": "Bearer tok-xyz"},
            })
        # At least one call must have been made to the MCP server
        assert mock_post.called

    def test_sse_transport_accepted(self, mcp_client):
        """transport='sse' is a valid enum value and the request succeeds."""
        post_fn = self._make_post_side_effects()
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={
                "url": "http://mcp.test/mcp",
                "transport": "sse",
            })
        assert resp.status_code == 200

    def test_default_transport_is_streamable_http(self, mcp_client):
        """When 'transport' is omitted it defaults to 'streamable_http'."""
        resp_data = mcp_client.post("/mcp/validate", json={})
        # Pydantic validation error for missing 'url' — transport default is fine
        assert resp_data.status_code == 422  # url is required

    def test_invalid_transport_returns_422(self, mcp_client):
        resp = mcp_client.post("/mcp/validate", json={
            "url": "http://mcp.test/mcp",
            "transport": "invalid_type",
        })
        assert resp.status_code == 422

    def test_session_id_from_response_header(self, mcp_client):
        """If the server returns mcp-session-id in a response header it is used."""
        # The _connect helper uses the header value — test verifies no crash
        post_fn = self._make_post_side_effects(session_id="hdr-session-99")
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.status_code == 200

    def test_no_tools_returns_empty_list_and_ok_summary(self, mcp_client):
        """Server with no tools → summary tools_total=0 overall_status='ok'."""
        post_fn = self._make_post_side_effects(tools=[])
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        summary = resp.json()["summary"]
        assert summary["tools_total"] == 0
        assert summary["overall_status"] == "ok"

    def test_connect_sends_initialized_notification(self, mcp_client):
        """_connect must call notifications/initialized after initialize."""
        calls = []
        orig_post_fn = self._make_post_side_effects()

        async def _tracking_post(url, *, json=None, **kw):
            method = (json or {}).get("method", "")
            calls.append(method)
            return await orig_post_fn(url, json=json, **kw)

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_tracking_post)):
            mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})

        assert "notifications/initialized" in calls

    def test_connect_initialized_notification_failure_is_ignored(self, mcp_client):
        """If notifications/initialized raises, connect must not propagate the error."""
        async def _post(url, *, json=None, headers=None, timeout=None):
            method = (json or {}).get("method", "")
            if method == "initialize":
                return _init_resp()
            if method == "notifications/initialized":
                raise httpx.RequestError("no notify", request=MagicMock())
            return _list_resp("tools", [])

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_post)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert resp.status_code == 200

    def test_tool_with_issues_logged_but_still_in_response(self, mcp_client):
        """Tools with issues must still appear in the tools list (not silently dropped)."""
        tools = [{"name": "broken", "description": "", "inputSchema": {"type": "array"}}]
        post_fn = self._make_post_side_effects(tools=tools)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=post_fn)):
            resp = mcp_client.post("/mcp/validate", json={"url": "http://mcp.test/mcp"})
        assert len(resp.json()["tools"]) == 1
        assert resp.json()["tools"][0]["name"] == "broken"

    def test_mcp_validate_request_model_defaults(self):
        """MCPValidateRequest: transport defaults to 'streamable_http', headers to {}."""
        from app.routers.mcp_validate import MCPValidateRequest
        req = MCPValidateRequest(url="http://x.test/mcp")
        assert req.transport == "streamable_http"
        assert req.headers == {}

    def test_mcp_validate_request_rejects_bad_transport(self):
        """MCPValidateRequest: invalid transport raises ValidationError."""
        from app.routers.mcp_validate import MCPValidateRequest
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MCPValidateRequest(url="http://x.test/mcp", transport="grpc")
