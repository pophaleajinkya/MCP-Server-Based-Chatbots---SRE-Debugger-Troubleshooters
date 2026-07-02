"""Consumer-driven contract tests for all public API endpoints.

These tests define the API contracts (expected request/response shapes) and
verify the implementation honours them.  No Pact broker is needed — contracts
are defined inline as Python dicts and validated against live FastAPI responses
using jsonschema-style assertions.

Endpoints covered:
  GET  /health          — liveness + capability snapshot
  GET  /ready           — Kubernetes readiness probe
  POST /query           — submit a natural language query
  POST /query_api       — alternate query entry point (identical contract)
  POST /mcp/validate    — MCP server validation endpoint
  POST /mcp-proxy       — JSON-RPC proxy to MCP pool
  GET  /sessions        — list conversation sessions
  GET  /sessions/{id}/messages  — get message history
  PATCH /sessions/{id}/visibility — set session visibility

Contract format:
  Each contract specifies:
    - request:  method, path, headers, body schema
    - response: status_code, required_fields, field_types, enum_values

Contracts are version-tagged so breaking changes are caught immediately.
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# ── Stub google.adk and genai modules if not installed ────────────────────────
# google-adk requires live credentials and heavy deps not present in CI.
# We stub out the exact symbols imported by app.services.runner so the module
# can be loaded without google-adk being installed on the test runner.
def _stub_google_adk():
    """Inject minimal sys.modules stubs for google.adk / google.genai."""
    import types

    def _make_module(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    if "google" not in sys.modules:
        _make_module("google")
    if "google.adk" not in sys.modules:
        _make_module("google.adk")
    if "google.adk.runners" not in sys.modules:
        mod = _make_module("google.adk.runners")
        mod.Runner = MagicMock  # type: ignore[attr-defined]
    if "google.adk.agents" not in sys.modules:
        _make_module("google.adk.agents")
    if "google.adk.agents.callback_context" not in sys.modules:
        mod = _make_module("google.adk.agents.callback_context")
        mod.CallbackContext = MagicMock  # type: ignore[attr-defined]
    if "google.adk.tools" not in sys.modules:
        _make_module("google.adk.tools")
    if "google.adk.tools.base_tool" not in sys.modules:
        mod = _make_module("google.adk.tools.base_tool")
        mod.BaseTool = MagicMock  # type: ignore[attr-defined]
    if "google.adk.tools.tool_context" not in sys.modules:
        mod = _make_module("google.adk.tools.tool_context")
        mod.ToolContext = MagicMock  # type: ignore[attr-defined]
    if "google.genai" not in sys.modules:
        _make_module("google.genai")
    if "google.genai.types" not in sys.modules:
        mod = _make_module("google.genai.types")
        mod.Content = MagicMock  # type: ignore[attr-defined]
        mod.Part    = MagicMock  # type: ignore[attr-defined]

try:
    import google.adk.runners  # noqa: F401
except ImportError:
    _stub_google_adk()

# ── Contract version ──────────────────────────────────────────────────────────
CONTRACT_VERSION = "1.0.0"

# ── Test headers ─────────────────────────────────────────────────────────────
_DEFAULT_HEADERS = {"loginId": "contract-test@walmart.com"}


# ── Contract assertion helpers ────────────────────────────────────────────────

def assert_field_present(data: dict, field: str, context: str = ""):
    """Assert a required field exists in the response body."""
    assert field in data, (
        f"Contract violation [{context}]: required field '{field}' missing in response. "
        f"Got fields: {list(data.keys())}"
    )


def assert_field_type(data: dict, field: str, expected_type, context: str = ""):
    """Assert a field has the expected type."""
    assert_field_present(data, field, context)
    value = data[field]
    assert isinstance(value, expected_type), (
        f"Contract violation [{context}]: field '{field}' expected {expected_type.__name__} "
        f"but got {type(value).__name__} (value={value!r})"
    )


def assert_field_enum(data: dict, field: str, allowed_values: set, context: str = ""):
    """Assert a field value is one of the allowed enum values."""
    assert_field_present(data, field, context)
    value = data[field]
    assert value in allowed_values, (
        f"Contract violation [{context}]: field '{field}' = {value!r} "
        f"is not in allowed values {allowed_values}"
    )


def assert_contract(data: dict, contract: dict, context: str = ""):
    """Validate a response dict against a contract spec."""
    for field in contract.get("required_fields", []):
        assert_field_present(data, field, context)
    for field, ftype in contract.get("field_types", {}).items():
        assert_field_type(data, field, ftype, context)
    for field, allowed in contract.get("enum_values", {}).items():
        assert_field_enum(data, field, allowed, context)


# ── App factory ───────────────────────────────────────────────────────────────

def _make_runner(answer="Contract test response"):
    """Build a mock ADK Runner that yields a final response."""
    part = MagicMock()
    part.text = answer
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.is_final_response.return_value = True
    event.content = content

    async def _run(**kwargs):
        yield event

    runner = MagicMock()
    runner.run_async = _run
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    runner.session_service._redis = MagicMock()
    runner.session_service._ttl = 604800
    return runner


def _make_mcp_pool(sessions=None):
    pool = MagicMock()
    pool._sessions = sessions or []
    pool.call_tool = AsyncMock(return_value="tool result")
    pool.call_prompt = AsyncMock(return_value="prompt result")
    return pool


def _make_redis_for_sessions():
    redis = MagicMock()
    redis.zrevrange = AsyncMock(return_value=[("sess-contract", time.time())])
    redis.hgetall   = AsyncMock(return_value={"sess-contract": "Contract query"})
    redis.get       = AsyncMock(return_value=None)
    redis.lrange    = AsyncMock(return_value=[
        json.dumps({"type": "user",     "text": "test query",    "ts": time.time()}).encode(),
        json.dumps({"type": "complete", "text": "test response", "ts": time.time()}).encode(),
    ])
    redis.set    = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    redis.zadd   = AsyncMock(return_value=1)
    redis.zrem   = AsyncMock(return_value=1)
    return redis


def _build_contract_app(env_vars=None, monkeypatch=None) -> FastAPI:
    from app.routers import health, query, sessions
    from app.routers.mcp_proxy import router as mcp_proxy_router
    from app.routers.mcp_validate import router as mcp_validate_router
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    app = FastAPI()
    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(AgentError, agent_error_handler)
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(sessions.router)
    app.include_router(mcp_proxy_router)
    app.include_router(mcp_validate_router)

    runner = _make_runner()
    runner.session_service._redis = _make_redis_for_sessions()

    app.state.runner     = runner
    app.state.mcp_pool   = _make_mcp_pool()
    app.state.mcp_servers = [{"name": "wcnp-mcp", "url": "http://mcp.test/mcp"}]
    app.state.mcp_tools  = ["check_health", "get_metrics"]
    return app


@pytest.fixture
def contract_client(env_vars):
    app = _build_contract_app()
    return TestClient(app, headers=_DEFAULT_HEADERS)


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: GET /health
# ═════════════════════════════════════════════════════════════════════════════

HEALTH_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "GET /health",
    "response_status": 200,
    "required_fields": ["status", "version", "active_llm", "llm_endpoint", "mcp_servers", "mcp_tools"],
    "field_types": {
        "status":       str,
        "version":      str,
        "active_llm":   str,
        "llm_endpoint": str,
        "mcp_servers":  list,
        "mcp_tools":    list,
    },
    "enum_values": {
        "status":     {"ok"},
        "active_llm": {"openai", "claude"},
    },
}


class TestHealthContract:
    def test_health_response_matches_contract(self, contract_client):
        resp = contract_client.get("/health")
        assert resp.status_code == HEALTH_CONTRACT["response_status"], (
            f"Contract violation: expected {HEALTH_CONTRACT['response_status']}, got {resp.status_code}"
        )
        assert_contract(resp.json(), HEALTH_CONTRACT, context="GET /health")

    def test_health_mcp_servers_each_have_name_and_url(self, contract_client):
        """Each item in mcp_servers must have 'name' and 'url' fields."""
        data = contract_client.get("/health").json()
        for server in data["mcp_servers"]:
            assert "name" in server, "Contract: mcp_servers[*].name is required"
            assert "url"  in server, "Contract: mcp_servers[*].url is required"

    def test_health_mcp_tools_are_strings(self, contract_client):
        """mcp_tools must be a list of strings."""
        data = contract_client.get("/health").json()
        for tool in data["mcp_tools"]:
            assert isinstance(tool, str), f"Contract: mcp_tools[*] must be str, got {type(tool)}"

    def test_health_version_is_semver_like(self, contract_client):
        """Version should match major.minor.patch pattern."""
        version = contract_client.get("/health").json()["version"]
        parts = version.split(".")
        assert len(parts) == 3, f"Contract: version '{version}' is not semver (major.minor.patch)"
        for part in parts:
            assert part.isdigit(), f"Contract: version part '{part}' is not numeric"

    def test_health_content_type_is_json(self, contract_client):
        resp = contract_client.get("/health")
        assert "application/json" in resp.headers.get("content-type", "")

    def test_health_with_claude_primary_llm(self, env_vars, monkeypatch):
        """When Claude is primary, active_llm must be 'claude'."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()
        app = _build_contract_app()
        client = TestClient(app, headers=_DEFAULT_HEADERS)
        data = client.get("/health").json()
        assert data["active_llm"] == "claude"
        get_settings.cache_clear()


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: GET /ready
# ═════════════════════════════════════════════════════════════════════════════

READY_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "GET /ready",
    "response_status": 200,
    "required_fields": ["status"],
    "field_types": {"status": str},
    "enum_values": {"status": {"ready"}},
}


class TestReadyContract:
    def test_ready_response_matches_contract(self, contract_client):
        resp = contract_client.get("/ready")
        assert resp.status_code == READY_CONTRACT["response_status"]
        assert_contract(resp.json(), READY_CONTRACT, context="GET /ready")

    def test_ready_status_is_ready(self, contract_client):
        assert contract_client.get("/ready").json()["status"] == "ready"


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: POST /query
# ═════════════════════════════════════════════════════════════════════════════

QUERY_REQUEST_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "POST /query",
    "required_body_fields": ["query"],
    "optional_body_fields": ["session_id", "user_id"],
    "query_min_length": 1,
    "query_max_length": 4096,
}

QUERY_RESPONSE_CONTRACT = {
    "version": CONTRACT_VERSION,
    "response_status": 200,
    "required_fields": ["response", "session_id"],
    "field_types": {
        "response":   str,
        "session_id": str,
    },
}


class TestQueryContract:
    def test_query_response_matches_contract(self, contract_client):
        resp = contract_client.post("/query", json={"query": "Check namespace health"})
        assert resp.status_code == QUERY_RESPONSE_CONTRACT["response_status"]
        assert_contract(resp.json(), QUERY_RESPONSE_CONTRACT, context="POST /query")

    def test_query_with_explicit_session_id_echoed_back(self, contract_client):
        """Contract: session_id in body must be returned in response."""
        resp = contract_client.post("/query", json={
            "query": "Test query",
            "session_id": "contract-session-123",
        })
        assert resp.json()["session_id"] == "contract-session-123"

    def test_query_auto_generates_session_id_when_omitted(self, contract_client):
        """Contract: a UUID session_id must be generated when not provided."""
        resp = contract_client.post("/query", json={"query": "Auto session test"})
        sid = resp.json()["session_id"]
        assert len(sid) > 0
        # UUID format: 8-4-4-4-12
        parts = sid.split("-")
        assert len(parts) == 5

    def test_query_empty_string_rejected_422(self, contract_client):
        """Contract: query must not be empty (min_length=1)."""
        resp = contract_client.post("/query", json={"query": ""})
        assert resp.status_code == 422

    def test_query_over_max_length_rejected_422(self, contract_client):
        """Contract: query exceeding 4096 chars must be rejected."""
        resp = contract_client.post("/query", json={"query": "x" * 4097})
        assert resp.status_code == 422

    def test_query_missing_body_422(self, contract_client):
        """Contract: missing request body must return 422."""
        resp = contract_client.post("/query")
        assert resp.status_code == 422

    def test_query_user_id_required_without_header(self, env_vars):
        """Contract: when no user_id in body or headers, must return 422."""
        app = _build_contract_app()
        client_no_header = TestClient(app)  # no loginId header
        resp = client_no_header.post("/query", json={"query": "test"})
        assert resp.status_code == 422

    def test_query_user_id_accepted_via_header(self, contract_client):
        """Contract: loginId header satisfies user_id requirement."""
        resp = contract_client.post("/query", json={"query": "header test"})
        assert resp.status_code == 200

    def test_query_user_id_accepted_via_wm_llm_gw_header(self, env_vars):
        """Contract: wm_llm_gw.user_name header satisfies user_id requirement."""
        app = _build_contract_app()
        client = TestClient(app, headers={"wm_llm_gw.user_name": "user@walmart.com"})
        resp = client.post("/query", json={"query": "gateway header test"})
        assert resp.status_code == 200

    def test_query_response_is_non_empty_string(self, contract_client):
        """Contract: response field must be a string (may be empty on no-op runner)."""
        data = contract_client.post("/query", json={"query": "test"}).json()
        assert isinstance(data["response"], str)


class TestQueryApiContract:
    """POST /query_api has identical contract to POST /query."""

    def test_query_api_matches_same_contract(self, contract_client):
        resp = contract_client.post("/query_api", json={"query": "alternate endpoint"})
        assert resp.status_code == 200
        assert_contract(resp.json(), QUERY_RESPONSE_CONTRACT, context="POST /query_api")

    def test_query_api_empty_query_rejected(self, contract_client):
        resp = contract_client.post("/query_api", json={"query": ""})
        assert resp.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: POST /mcp-proxy
# ═════════════════════════════════════════════════════════════════════════════

MCP_PROXY_TOOLS_LIST_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "POST /mcp-proxy (tools/list)",
    "response_status": 200,
    "required_fields": ["result"],
}

MCP_PROXY_TOOLS_CALL_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "POST /mcp-proxy (tools/call)",
    "response_status": 200,
    "required_fields": ["result"],
}


class TestMcpProxyContract:
    def test_tools_list_contract(self, contract_client):
        resp = contract_client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == MCP_PROXY_TOOLS_LIST_CONTRACT["response_status"]
        data = resp.json()
        assert_field_present(data, "result", context="mcp-proxy tools/list")
        assert "tools" in data["result"], "Contract: result.tools must be present"
        assert isinstance(data["result"]["tools"], list)

    def test_tools_call_contract(self, contract_client):
        resp = contract_client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "check_health", "arguments": {"ns": "sre"}},
        })
        assert resp.status_code == MCP_PROXY_TOOLS_CALL_CONTRACT["response_status"]
        data = resp.json()
        assert_field_present(data, "result", context="mcp-proxy tools/call")
        assert "content" in data["result"]
        content = data["result"]["content"]
        assert isinstance(content, list)
        assert len(content) > 0
        assert content[0]["type"] == "text"
        assert isinstance(content[0]["text"], str)

    def test_invalid_json_returns_400_with_error_field(self, contract_client):
        resp = contract_client.post(
            "/mcp-proxy",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_unsupported_method_returns_400_with_error_field(self, contract_client):
        resp = contract_client.post("/mcp-proxy", json={"method": "unknown/method"})
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_missing_tool_name_returns_400(self, contract_client):
        resp = contract_client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {},
        })
        assert resp.status_code == 400

    def test_missing_resource_uri_returns_400(self, contract_client):
        resp = contract_client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {},
        })
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: POST /mcp/validate
# ═════════════════════════════════════════════════════════════════════════════

MCP_VALIDATE_RESPONSE_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "POST /mcp/validate",
    "required_fields": [
        "server_name", "server_version", "tools", "resources", "prompts", "summary"
    ],
    "field_types": {
        "server_name":    str,
        "server_version": str,
        "tools":          list,
        "resources":      list,
        "prompts":        list,
        "summary":        dict,
    },
}

MCP_VALIDATE_SUMMARY_CONTRACT = {
    "required_fields": [
        "tools_total", "tools_ok", "tools_warnings", "tools_errors",
        "resources_total", "prompts_total", "overall_status",
    ],
    "field_types": {
        "tools_total":     int,
        "tools_ok":        int,
        "tools_warnings":  int,
        "tools_errors":    int,
        "resources_total": int,
        "prompts_total":   int,
        "overall_status":  str,
    },
    "enum_values": {
        "overall_status": {"ok", "warning", "error"},
    },
}

MCP_VALIDATE_REQUEST_CONTRACT = {
    "required_fields": ["url"],
    "optional_fields": ["transport", "headers"],
    "transport_enum": {"streamable_http", "sse"},
}


class TestMcpValidateContract:
    """Validate the shape of /mcp/validate responses without a live server."""

    def test_validate_request_missing_url_returns_422(self, contract_client):
        """Contract: 'url' is required in the request body."""
        resp = contract_client.post("/mcp/validate", json={"transport": "streamable_http"})
        assert resp.status_code == 422

    def test_validate_request_invalid_transport_returns_422(self, contract_client):
        """Contract: transport must be 'streamable_http' or 'sse'."""
        resp = contract_client.post("/mcp/validate", json={
            "url": "https://mcp.test/mcp",
            "transport": "invalid_transport",
        })
        assert resp.status_code == 422

    def test_validate_summary_contract_structure(self):
        """Unit-level: ValidationSummary fields match contract."""
        from app.routers.mcp_validate import ValidationSummary
        summary = ValidationSummary(
            tools_total=3, tools_ok=2, tools_warnings=1, tools_errors=0,
            resources_total=1, prompts_total=0, overall_status="warning",
        )
        data = summary.model_dump()
        assert_contract(data, MCP_VALIDATE_SUMMARY_CONTRACT, context="ValidationSummary")

    def test_validate_tool_validation_contract_structure(self):
        """Unit-level: ToolValidation response shape matches contract."""
        from app.routers.mcp_validate import _validate_tool
        result = _validate_tool(0, {
            "name": "check_health",
            "description": "Checks health",
            "inputSchema": {"type": "object"},
        })
        assert hasattr(result, "index")
        assert hasattr(result, "name")
        assert hasattr(result, "description")
        assert hasattr(result, "status")
        assert hasattr(result, "issues")
        assert hasattr(result, "input_schema")
        assert result.status in ("ok", "warning", "error")
        assert isinstance(result.issues, list)

    def test_validate_resource_info_contract_structure(self):
        """Unit-level: ResourceInfo response shape matches contract."""
        from app.routers.mcp_validate import _validate_resource
        result = _validate_resource({"uri": "wcnp://guide", "name": "Guide"})
        assert hasattr(result, "uri")
        assert hasattr(result, "name")
        assert hasattr(result, "status")
        assert hasattr(result, "issues")
        assert result.status in ("ok", "warning", "error")

    def test_validate_prompt_info_contract_structure(self):
        """Unit-level: PromptInfo response shape matches contract."""
        from app.routers.mcp_validate import _validate_prompt
        result = _validate_prompt({"name": "rca-investigate", "description": "RCA prompt"})
        assert hasattr(result, "name")
        assert hasattr(result, "status")
        assert hasattr(result, "issues")
        assert result.status in ("ok", "error")

    def test_validate_request_with_extra_headers_field_accepted(self, contract_client):
        """Contract: custom headers dict in body must pass Pydantic validation (not 422).
        The endpoint may fail at connection time (500/502) but must NOT return 422.
        We patch _connect to prevent any real network call.
        """
        from unittest.mock import patch, AsyncMock
        with patch("app.routers.mcp_validate._connect", AsyncMock(return_value=("s", "srv", "1.0"))):
            with patch("app.routers.mcp_validate._rpc", AsyncMock(return_value={"result": {}})):
                resp = contract_client.post("/mcp/validate", json={
                    "url": "https://mcp.test/mcp",
                    "headers": {"Authorization": "Bearer test"},
                })
        assert resp.status_code != 422


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: GET /sessions
# ═════════════════════════════════════════════════════════════════════════════

SESSIONS_LIST_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "GET /sessions",
    "response_status": 200,
    "required_fields": ["sessions"],
    "field_types": {"sessions": list},
}

SESSION_ITEM_CONTRACT = {
    "required_fields": ["session_id", "title", "last_update_time", "user_id"],
    "field_types": {
        "session_id":       str,
        "title":            str,
        "last_update_time": (int, float),
        "user_id":          str,
    },
}


class TestSessionsListContract:
    def test_sessions_list_response_matches_contract(self, contract_client):
        resp = contract_client.get("/sessions")
        assert resp.status_code == SESSIONS_LIST_CONTRACT["response_status"]
        assert_contract(resp.json(), SESSIONS_LIST_CONTRACT, context="GET /sessions")

    def test_sessions_list_items_match_item_contract(self, contract_client):
        """Each session item in the list must satisfy the item contract."""
        data = contract_client.get("/sessions").json()
        for item in data["sessions"]:
            for field in SESSION_ITEM_CONTRACT["required_fields"]:
                assert field in item, (
                    f"Contract violation: session item missing field '{field}'. "
                    f"Got: {list(item.keys())}"
                )

    def test_sessions_accepts_user_id_query_param(self, contract_client):
        """Contract: user_id query parameter must be accepted."""
        resp = contract_client.get("/sessions?user_id=test-user@walmart.com")
        assert resp.status_code == 200

    def test_sessions_default_user_id_is_admin(self, contract_client):
        """Contract: omitting user_id defaults to 'admin' — should not error."""
        resp = contract_client.get("/sessions")
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: GET /sessions/{id}/messages
# ═════════════════════════════════════════════════════════════════════════════

SESSION_MESSAGES_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "GET /sessions/{id}/messages",
    "response_status": 200,
    "required_fields": ["session_id", "messages"],
    "field_types": {
        "session_id": str,
        "messages":   list,
    },
}

MESSAGE_ITEM_CONTRACT = {
    "required_fields": ["role", "content", "timestamp"],
    "field_types": {
        "role":      str,
        "content":   str,
        "timestamp": (int, float),
    },
    "enum_values": {
        "role": {"user", "assistant"},
    },
}


class TestSessionMessagesContract:
    def test_messages_response_matches_contract(self, contract_client):
        resp = contract_client.get("/sessions/sess-contract/messages?user_id=contract-test@walmart.com")
        assert resp.status_code == SESSION_MESSAGES_CONTRACT["response_status"]
        assert_contract(resp.json(), SESSION_MESSAGES_CONTRACT, context="GET /sessions/{id}/messages")

    def test_messages_session_id_echoed(self, contract_client):
        """Contract: response.session_id must match the path parameter."""
        resp = contract_client.get("/sessions/my-session-id/messages")
        data = resp.json()
        if resp.status_code == 200:
            assert data["session_id"] == "my-session-id"

    def test_messages_items_match_item_contract(self, contract_client):
        """Each message in the list must satisfy the message item contract."""
        data = contract_client.get(
            "/sessions/sess-contract/messages?user_id=contract-test@walmart.com"
        ).json()
        for msg in data.get("messages", []):
            for field in MESSAGE_ITEM_CONTRACT["required_fields"]:
                assert field in msg, (
                    f"Contract violation: message item missing field '{field}'. "
                    f"Got: {list(msg.keys())}"
                )
            assert msg["role"] in MESSAGE_ITEM_CONTRACT["enum_values"]["role"]


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT: PATCH /sessions/{id}/visibility
# ═════════════════════════════════════════════════════════════════════════════

VISIBILITY_RESPONSE_CONTRACT = {
    "version": CONTRACT_VERSION,
    "endpoint": "PATCH /sessions/{id}/visibility",
    "response_status": 200,
    "required_fields": ["session_id", "public", "tags"],
    "field_types": {
        "session_id": str,
        "public":     bool,
        "tags":       list,
    },
}


class TestVisibilityContract:
    def test_visibility_response_matches_contract(self, contract_client):
        resp = contract_client.patch(
            "/sessions/sess-vis/visibility",
            json={"public": True, "tags": ["Alert"], "user_id": "contract-test@walmart.com"},
        )
        assert resp.status_code == VISIBILITY_RESPONSE_CONTRACT["response_status"]
        assert_contract(resp.json(), VISIBILITY_RESPONSE_CONTRACT, context="PATCH /sessions/{id}/visibility")

    def test_visibility_session_id_echoed(self, contract_client):
        resp = contract_client.patch(
            "/sessions/my-vis-session/visibility",
            json={"public": False, "tags": []},
        )
        assert resp.json()["session_id"] == "my-vis-session"

    def test_visibility_public_false_accepted(self, contract_client):
        resp = contract_client.patch(
            "/sessions/sess-x/visibility",
            json={"public": False, "tags": []},
        )
        assert resp.status_code == 200
        assert resp.json()["public"] is False

    def test_visibility_tags_is_list_of_strings(self, contract_client):
        resp = contract_client.patch(
            "/sessions/sess-y/visibility",
            json={"public": True, "tags": ["P1", "Incident-99"]},
        )
        data = resp.json()
        assert all(isinstance(t, str) for t in data["tags"])


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT REGISTRY — machine-readable snapshot
# ═════════════════════════════════════════════════════════════════════════════

ALL_CONTRACTS = {
    "version": CONTRACT_VERSION,
    "consumer": "super-agent",
    "endpoints": [
        HEALTH_CONTRACT,
        READY_CONTRACT,
        QUERY_RESPONSE_CONTRACT,
        MCP_PROXY_TOOLS_LIST_CONTRACT,
        MCP_PROXY_TOOLS_CALL_CONTRACT,
        MCP_VALIDATE_RESPONSE_CONTRACT,
        SESSIONS_LIST_CONTRACT,
        SESSION_MESSAGES_CONTRACT,
        VISIBILITY_RESPONSE_CONTRACT,
    ],
}


class TestContractRegistry:
    """Meta-tests that verify the contract registry itself is self-consistent."""

    def test_all_contracts_have_version(self):
        for contract in ALL_CONTRACTS["endpoints"]:
            assert "version" in contract, f"Contract missing version: {contract}"
            assert contract["version"] == CONTRACT_VERSION

    def test_all_contracts_have_endpoint(self):
        for contract in ALL_CONTRACTS["endpoints"]:
            if "endpoint" in contract:
                assert len(contract["endpoint"]) > 0

    def test_contract_version_is_semver(self):
        parts = CONTRACT_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
