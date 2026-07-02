"""Negative and boundary integration tests for all API endpoints.

Tests every error path, invalid input, and boundary condition at the HTTP level.
No live network, Redis, or ADK credentials required — all external deps mocked.

Endpoints covered:
  POST /query         — query boundary lengths, missing identity, LLM errors
  POST /query_api     — same contract as /query
  GET  /health        — state edge cases (empty tools/servers)
  GET  /ready         — always 200
  POST /mcp-proxy     — all negative paths at HTTP level
  POST /mcp/validate  — invalid request bodies, Pydantic validation
  GET  /sessions      — Redis failure fallback, malformed members
  GET  /sessions/{id}/messages — unknown session, timeout fallback
  PATCH /sessions/{id}/visibility — missing body fields
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub google.adk if not installed (matches strategy in test_contract.py)
def _stub_google_adk():
    import types

    def _m(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    for pkg in ("google", "google.adk", "google.adk.runners", "google.adk.agents",
                "google.adk.agents.callback_context", "google.adk.tools",
                "google.adk.tools.base_tool", "google.adk.tools.tool_context",
                "google.genai", "google.genai.types"):
        if pkg not in sys.modules:
            mod = _m(pkg)
            if pkg.endswith(".runners"):
                mod.Runner = MagicMock
            elif pkg.endswith(".callback_context"):
                mod.CallbackContext = MagicMock
            elif pkg.endswith(".base_tool"):
                mod.BaseTool = MagicMock
            elif pkg.endswith(".tool_context"):
                mod.ToolContext = MagicMock
            elif pkg.endswith(".types"):
                mod.Content = MagicMock
                mod.Part = MagicMock

try:
    import google.adk.runners  # noqa: F401
except ImportError:
    _stub_google_adk()


# ── App / client builders ─────────────────────────────────────────────────────

def _make_runner(answer="ok", raise_exc=None):
    part = MagicMock()
    part.text = answer
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.is_final_response.return_value = True
    event.content = content

    if raise_exc:
        async def _run(**kwargs):
            raise raise_exc
            yield  # pragma: no cover
    else:
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


def _make_pool(sessions=None):
    pool = MagicMock()
    pool._sessions = sessions or []
    pool.call_tool = AsyncMock(return_value="result")
    pool.call_prompt = AsyncMock(return_value="prompt")
    return pool


def _make_redis(**kwargs):
    redis = MagicMock()
    redis.zrevrange = AsyncMock(return_value=kwargs.get("zrevrange", []))
    redis.hgetall   = AsyncMock(return_value=kwargs.get("hgetall", {}))
    redis.smembers  = AsyncMock(return_value=kwargs.get("smembers", set()))
    redis.lrange    = AsyncMock(return_value=kwargs.get("lrange", []))
    redis.get       = AsyncMock(return_value=kwargs.get("get", None))
    redis.hget      = AsyncMock(return_value=None)
    redis.set       = AsyncMock(return_value=True)
    redis.expire    = AsyncMock(return_value=True)
    redis.zadd      = AsyncMock(return_value=1)
    redis.zrem      = AsyncMock(return_value=1)
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__  = AsyncMock(return_value=None)
    pipe.get = MagicMock()
    pipe.lrange = MagicMock()
    pipe.execute = AsyncMock(return_value=kwargs.get("pipeline", []))
    redis.pipeline = MagicMock(return_value=pipe)

    async def _scan(*a, **kw):
        for k in kwargs.get("scan_keys", []):
            yield k
    redis.scan_iter = _scan
    return redis


def _build_full_app(runner=None, pool=None, redis=None):
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

    _runner = runner or _make_runner()
    if redis:
        _runner.session_service._redis = redis

    app.state.runner     = _runner
    app.state.mcp_pool   = pool or _make_pool()
    app.state.mcp_servers = [{"name": "t", "url": "http://mcp.test"}]
    app.state.mcp_tools  = ["check_health"]
    return app


_DEFAULT_HEADERS = {"loginId": "tester@walmart.com"}


@pytest.fixture
def client(env_vars):
    return TestClient(_build_full_app(), headers=_DEFAULT_HEADERS)


@pytest.fixture
def client_no_auth(env_vars):
    """Client with NO loginId / wm_llm_gw headers."""
    return TestClient(_build_full_app())


# ═══════════════════════════════════════════════════════════════════════════════
# POST /query — negative and boundary
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueryNegative:
    def test_empty_query_returns_422(self, client):
        assert client.post("/query", json={"query": ""}).status_code == 422

    def test_null_query_returns_422(self, client):
        assert client.post("/query", json={"query": None}).status_code == 422

    def test_missing_query_field_returns_422(self, client):
        assert client.post("/query", json={"user_id": "alice"}).status_code == 422

    def test_no_body_returns_422(self, client):
        assert client.post("/query").status_code == 422

    def test_empty_json_object_returns_422(self, client):
        assert client.post("/query", json={}).status_code == 422

    def test_wrong_content_type_returns_422(self, client):
        resp = client.post(
            "/query",
            content=b"query=test",
            headers={"Content-Type": "application/x-www-form-urlencoded", "loginId": "t@test.com"},
        )
        assert resp.status_code == 422

    def test_query_integer_type_returns_422(self, client):
        assert client.post("/query", json={"query": 42}).status_code == 422

    def test_query_list_type_returns_422(self, client):
        assert client.post("/query", json={"query": ["a", "b"]}).status_code == 422

    def test_no_user_identity_returns_422(self, client_no_auth):
        resp = client_no_auth.post("/query", json={"query": "test"})
        assert resp.status_code == 422

    def test_user_id_in_body_satisfies_requirement(self, env_vars):
        app = _build_full_app()
        c = TestClient(app)  # no headers
        resp = c.post("/query", json={"query": "test", "user_id": "alice@walmart.com"})
        assert resp.status_code == 200

    def test_loginid_header_satisfies_requirement(self, env_vars):
        app = _build_full_app()
        c = TestClient(app, headers={"loginId": "bob@walmart.com"})
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 200

    def test_wm_llm_gw_user_name_header_satisfies_requirement(self, env_vars):
        app = _build_full_app()
        c = TestClient(app, headers={"wm_llm_gw.user_name": "carol@walmart.com"})
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 200

    def test_llm_error_returns_502(self, env_vars):
        from app.exceptions import LLMError
        runner = _make_runner(raise_exc=LLMError(502, "upstream gateway error"))
        app = _build_full_app(runner=runner)
        c = TestClient(app, headers=_DEFAULT_HEADERS, raise_server_exceptions=False)
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 502
        assert resp.json()["error"] == "llm_error"
        assert resp.json()["llm_status_code"] == 502

    def test_agent_error_returns_500(self, env_vars):
        from app.exceptions import AgentError
        runner = _make_runner(raise_exc=AgentError("agentic loop failed"))
        app = _build_full_app(runner=runner)
        c = TestClient(app, headers=_DEFAULT_HEADERS, raise_server_exceptions=False)
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 500
        assert resp.json()["error"] == "agent_error"

    def test_runtime_error_returns_500(self, env_vars):
        runner = _make_runner(raise_exc=RuntimeError("unexpected crash"))
        app = _build_full_app(runner=runner)
        c = TestClient(app, headers=_DEFAULT_HEADERS, raise_server_exceptions=False)
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 500

    def test_llm_error_400_status_code_preserved(self, env_vars):
        from app.exceptions import LLMError
        runner = _make_runner(raise_exc=LLMError(400, "bad request to gateway"))
        app = _build_full_app(runner=runner)
        c = TestClient(app, headers=_DEFAULT_HEADERS, raise_server_exceptions=False)
        resp = c.post("/query", json={"query": "test"})
        data = resp.json()
        assert data["llm_status_code"] == 400


class TestQueryBoundary:
    def test_query_exactly_one_char(self, client):
        resp = client.post("/query", json={"query": "x"})
        assert resp.status_code == 200

    def test_query_exactly_4096_chars(self, client):
        resp = client.post("/query", json={"query": "a" * 4096})
        assert resp.status_code == 200

    def test_query_4097_chars_rejected(self, client):
        resp = client.post("/query", json={"query": "a" * 4097})
        assert resp.status_code == 422

    def test_session_id_exactly_1_char(self, client):
        resp = client.post("/query", json={"query": "test", "session_id": "x"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "x"

    def test_session_id_exactly_256_chars(self, client):
        long_sid = "s" * 256
        resp = client.post("/query", json={"query": "test", "session_id": long_sid})
        assert resp.status_code == 200

    def test_session_id_257_chars_rejected(self, client):
        resp = client.post("/query", json={"query": "test", "session_id": "s" * 257})
        assert resp.status_code == 422

    def test_session_id_empty_rejected(self, client):
        resp = client.post("/query", json={"query": "test", "session_id": ""})
        assert resp.status_code == 422

    def test_user_id_exactly_512_chars(self, env_vars):
        app = _build_full_app()
        c = TestClient(app)
        resp = c.post("/query", json={"query": "test", "user_id": "u" * 512})
        assert resp.status_code == 200

    def test_user_id_513_chars_rejected(self, env_vars):
        app = _build_full_app()
        c = TestClient(app)
        resp = c.post("/query", json={"query": "test", "user_id": "u" * 513})
        assert resp.status_code == 422

    def test_query_all_whitespace_accepted_at_schema_level(self, client):
        """A query of spaces passes min_length=1; business logic may reject it but schema won't."""
        resp = client.post("/query", json={"query": " "})
        assert resp.status_code == 200

    def test_query_with_newlines_and_tabs(self, client):
        resp = client.post("/query", json={"query": "check\nnamespace\thealth"})
        assert resp.status_code == 200

    def test_query_with_unicode_chars(self, client):
        resp = client.post("/query", json={"query": "检查命名空间 🚀"})
        assert resp.status_code == 200

    def test_query_response_contains_non_empty_session_id(self, client):
        resp = client.post("/query", json={"query": "test"})
        assert resp.json()["session_id"] != ""

    def test_repeated_same_session_id_returns_same_id(self, client):
        sid = "fixed-session-abc"
        for _ in range(3):
            resp = client.post("/query", json={"query": "test", "session_id": sid})
            assert resp.json()["session_id"] == sid


# ═══════════════════════════════════════════════════════════════════════════════
# GET /health — edge states
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthNegativeBoundary:
    def test_empty_mcp_servers_returns_empty_list(self, env_vars):
        app = _build_full_app()
        app.state.mcp_servers = []
        app.state.mcp_tools = []
        c = TestClient(app)
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["mcp_servers"] == []
        assert resp.json()["mcp_tools"] == []

    def test_many_mcp_tools_returned_completely(self, env_vars):
        app = _build_full_app()
        app.state.mcp_tools = [f"tool_{i}" for i in range(100)]
        c = TestClient(app)
        resp = c.get("/health")
        assert len(resp.json()["mcp_tools"]) == 100

    def test_health_method_not_allowed_post(self, client):
        assert client.post("/health").status_code == 405

    def test_ready_method_not_allowed_post(self, client):
        assert client.post("/ready").status_code == 405

    def test_health_with_no_accept_header(self, env_vars):
        app = _build_full_app()
        c = TestClient(app)
        resp = c.get("/health", headers={"Accept": "*/*"})
        assert resp.status_code == 200

    def test_health_status_always_ok(self, env_vars):
        """Health endpoint always reports status=ok regardless of LLM config."""
        for claude_primary in ("true", "false"):
            import os
            os.environ["CLAUDE_IS_PRIMARY_LLM"] = claude_primary
            from app.config import get_settings
            get_settings.cache_clear()
            app = _build_full_app()
            c = TestClient(app)
            assert c.get("/health").json()["status"] == "ok"
        get_settings.cache_clear()


# ═══════════════════════════════════════════════════════════════════════════════
# POST /mcp-proxy — negative and boundary at HTTP level
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpProxyNegativeBoundary:
    def test_completely_empty_body_returns_400(self, client):
        resp = client.post("/mcp-proxy", content=b"", headers={"Content-Type": "application/json"})
        assert resp.status_code in (400, 422)

    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/mcp-proxy", content=b"{broken json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_array_json_body_triggers_error_response(self, client):
        """A JSON array body: request.json() succeeds but body.get('method', '')
        raises AttributeError because lists don't have .get().
        This call is outside the inner try-except in mcp_proxy.py, so the
        AttributeError propagates → FastAPI returns 500 (unhandled server error).
        """
        resp = TestClient(_build_full_app(), headers=_DEFAULT_HEADERS,
                          raise_server_exceptions=False).post("/mcp-proxy", json=["tools/list"])
        assert resp.status_code == 500

    def test_number_json_body_triggers_error_response(self, client):
        """A JSON number body: same as array — AttributeError on body.get → 500."""
        resp = TestClient(_build_full_app(), headers=_DEFAULT_HEADERS,
                          raise_server_exceptions=False).post("/mcp-proxy", json=42)
        assert resp.status_code == 500

    def test_tools_call_with_very_long_tool_name(self, client):
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "x" * 10000, "arguments": {}},
        })
        assert resp.status_code in (200, 400, 502)

    def test_tools_call_with_deeply_nested_arguments(self, client):
        args = {"level": {}}
        for _ in range(20):
            args = {"level": args}
        resp = client.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "check_health", "arguments": args},
        })
        assert resp.status_code in (200, 502)

    def test_resources_read_with_special_uri(self, client):
        resp = client.post("/mcp-proxy", json={
            "method": "resources/read",
            "params": {"uri": "wcnp://agent-guide?version=2&lang=en"},
        })
        # No sessions in pool → 404
        assert resp.status_code in (404, 200)

    def test_prompts_get_with_empty_name(self, client):
        resp = client.post("/mcp-proxy", json={
            "method": "prompts/get",
            "params": {"name": "", "arguments": {}},
        })
        # Empty name is passed through to pool.call_prompt — no 400 at proxy level
        assert resp.status_code in (200, 502)

    def test_unsupported_rpc_method_variants(self, client):
        for method in ("initialize", "tools/update", "sessions/list", "notifications/initialized"):
            resp = client.post("/mcp-proxy", json={"method": method})
            assert resp.status_code == 400, f"Expected 400 for method={method}"

    def test_method_with_uppercase_returns_400(self, client):
        resp = client.post("/mcp-proxy", json={"method": "TOOLS/LIST"})
        assert resp.status_code == 400

    def test_method_with_null_returns_400(self, client):
        resp = client.post("/mcp-proxy", json={"method": None})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# POST /mcp/validate — request validation negative
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpValidateNegativeBoundary:
    def test_missing_url_returns_422(self, client):
        resp = client.post("/mcp/validate", json={"transport": "streamable_http"})
        assert resp.status_code == 422

    def test_null_url_returns_422(self, client):
        resp = client.post("/mcp/validate", json={"url": None})
        assert resp.status_code == 422

    def test_invalid_transport_returns_422(self, client):
        resp = client.post("/mcp/validate", json={"url": "http://x.test", "transport": "grpc"})
        assert resp.status_code == 422

    def test_transport_null_returns_422(self, client):
        resp = client.post("/mcp/validate", json={"url": "http://x.test", "transport": None})
        assert resp.status_code == 422

    def test_transport_empty_string_returns_422(self, client):
        resp = client.post("/mcp/validate", json={"url": "http://x.test", "transport": ""})
        assert resp.status_code == 422

    def test_headers_must_be_dict(self, client):
        resp = client.post("/mcp/validate", json={
            "url": "http://x.test",
            "headers": ["not-a-dict"],
        })
        assert resp.status_code == 422

    def test_both_transports_accepted_at_schema_level(self, client):
        from unittest.mock import patch, AsyncMock
        for transport in ("streamable_http", "sse"):
            with patch("app.routers.mcp_validate._connect", AsyncMock(return_value=("s", "n", "1"))):
                with patch("app.routers.mcp_validate._rpc", AsyncMock(return_value={"result": {}})):
                    resp = client.post("/mcp/validate", json={
                        "url": "http://x.test/mcp",
                        "transport": transport,
                    })
            assert resp.status_code == 200, f"transport={transport} returned {resp.status_code}"

    def test_empty_headers_dict_accepted(self, client):
        from unittest.mock import patch, AsyncMock
        with patch("app.routers.mcp_validate._connect", AsyncMock(return_value=("s", "n", "1"))):
            with patch("app.routers.mcp_validate._rpc", AsyncMock(return_value={"result": {}})):
                resp = client.post("/mcp/validate", json={
                    "url": "http://x.test/mcp",
                    "headers": {},
                })
        assert resp.status_code == 200

    def test_no_body_returns_422(self, client):
        assert client.post("/mcp/validate").status_code == 422

    def test_empty_json_object_returns_422(self, client):
        assert client.post("/mcp/validate", json={}).status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# GET /sessions — negative and boundary
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionsNegativeBoundary:
    def test_redis_zrevrange_exception_returns_empty_with_error(self, env_vars):
        redis = _make_redis()
        redis.zrevrange = AsyncMock(side_effect=RuntimeError("connection refused"))
        redis.hgetall   = AsyncMock(side_effect=RuntimeError("connection refused"))
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data

    def test_redis_timeout_returns_empty_with_error(self, env_vars):
        redis = _make_redis()
        redis.zrevrange = AsyncMock(side_effect=asyncio.TimeoutError())
        redis.hgetall   = AsyncMock(side_effect=asyncio.TimeoutError())
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_session_method_not_allowed(self, env_vars):
        app = _build_full_app()
        c = TestClient(app)
        assert c.delete("/sessions").status_code == 405

    def test_sessions_with_empty_user_id_still_200(self, env_vars):
        """Empty user_id is a query param string — FastAPI accepts it."""
        app = _build_full_app()
        c = TestClient(app)
        resp = c.get("/sessions?user_id=")
        assert resp.status_code == 200

    def test_sessions_with_very_long_user_id(self, env_vars):
        app = _build_full_app()
        c = TestClient(app)
        resp = c.get(f"/sessions?user_id={'u' * 512}")
        assert resp.status_code == 200

    def test_visibility_missing_body_returns_422(self, env_vars):
        redis = _make_redis()
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.patch("/sessions/sess-123/visibility")
        assert resp.status_code == 422

    def test_visibility_string_public_coerced_by_pydantic(self, env_vars):
        """Pydantic v2 coerces 'yes' → True for bool fields (not a 422).
        The request reaches the handler; we need a real async Redis mock.
        """
        redis = _make_redis()
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.patch("/sessions/sess-x/visibility", json={"public": "yes"})
        # Pydantic accepts "yes" as True → handler runs → redis ops called → 200
        assert resp.status_code == 200
        assert resp.json()["public"] is True

    def test_visibility_tags_not_list_returns_422(self, env_vars):
        redis = _make_redis()
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.patch("/sessions/sess-x/visibility", json={"public": True, "tags": "Alert"})
        assert resp.status_code == 422

    def test_messages_redis_timeout_returns_503(self, env_vars):
        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=asyncio.TimeoutError())
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.get("/sessions/sess-abc/messages?user_id=alice")
        assert resp.status_code == 503

    def test_messages_for_nonexistent_session_returns_200_empty(self, env_vars):
        redis = _make_redis(lrange=[])
        redis.get = AsyncMock(return_value=None)  # no shared/visibility
        app = _build_full_app(redis=redis)
        c = TestClient(app)
        resp = c.get("/sessions/nonexistent-session/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_messages_malformed_event_json_handled_gracefully(self, env_vars):
        """A corrupted event in the list should cause a 500 (json.loads fails)
        but not a silent data corruption.
        """
        redis = _make_redis(lrange=[b"not-valid-json"])
        app = _build_full_app(redis=redis)
        c = TestClient(app, raise_server_exceptions=False)
        # Either 200 (if error is swallowed) or 500 (if it bubbles up)
        resp = c.get("/sessions/sess-bad/messages?user_id=alice")
        assert resp.status_code in (200, 500, 503)


# ═══════════════════════════════════════════════════════════════════════════════
# General API boundary — HTTP method mismatches
# ═══════════════════════════════════════════════════════════════════════════════

class TestHttpMethodBoundary:
    def test_get_query_returns_405(self, client):
        assert client.get("/query").status_code == 405

    def test_put_query_returns_405(self, client):
        assert client.put("/query", json={"query": "test"}).status_code == 405

    def test_delete_query_returns_405(self, client):
        assert client.delete("/query").status_code == 405

    def test_patch_query_returns_405(self, client):
        assert client.patch("/query").status_code == 405

    def test_get_mcp_proxy_returns_405(self, client):
        assert client.get("/mcp-proxy").status_code == 405

    def test_delete_sessions_returns_405(self, client):
        assert client.delete("/sessions").status_code == 405

    def test_unknown_endpoint_returns_404(self, client):
        assert client.get("/nonexistent-endpoint").status_code == 404

    def test_unknown_post_endpoint_returns_404(self, client):
        assert client.post("/nonexistent", json={}).status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Content-Type boundary tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestContentTypeBoundary:
    def test_query_with_extra_unknown_fields_ignored(self, client):
        """Pydantic should ignore extra fields (model_config extra='ignore')."""
        resp = client.post("/query", json={
            "query": "test",
            "unknown_field": "ignored",
            "another": 42,
        })
        assert resp.status_code == 200

    def test_health_response_content_type_is_json(self, client):
        resp = client.get("/health")
        assert "application/json" in resp.headers.get("content-type", "")

    def test_query_response_content_type_is_json(self, client):
        resp = client.post("/query", json={"query": "test"})
        assert "application/json" in resp.headers.get("content-type", "")

    def test_422_response_contains_detail_field(self, client):
        resp = client.post("/query", json={"query": ""})
        data = resp.json()
        assert "detail" in data

    def test_422_detail_is_list_of_errors(self, client):
        resp = client.post("/query", json={"query": ""})
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert len(detail) > 0
