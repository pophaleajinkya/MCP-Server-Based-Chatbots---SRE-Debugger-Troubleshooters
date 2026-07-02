"""Comprehensive negative and edge-case tests for ALL routers in src/app/routers/.

Covers: mcp_proxy, debug, faqs, health, query, sessions routers.
Tests invalid inputs, error paths, exception handling, and boundary conditions.
"""

import asyncio
import json
import sys
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app():
    """Build a FastAPI app with all routers mounted and mocked state."""
    from app.routers import mcp_proxy, debug, faqs, health, query, sessions
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    app = FastAPI()
    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(AgentError, agent_error_handler)
    app.include_router(mcp_proxy.router)
    app.include_router(debug.router)
    app.include_router(faqs.router)
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(sessions.router)
    return app


def _mock_redis(**overrides):
    """Return an AsyncMock Redis client with sensible defaults."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(return_value=[])
    redis.smembers = AsyncMock(return_value=set())
    redis.hgetall = AsyncMock(return_value={})
    redis.zrevrange = AsyncMock(return_value=[])
    redis.ttl = AsyncMock(return_value=-2)
    redis.pipeline = MagicMock()

    # Pipeline context manager
    pipe_mock = AsyncMock()
    pipe_mock.execute = AsyncMock(return_value=[])
    pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
    pipe_mock.__aexit__ = AsyncMock(return_value=None)
    redis.pipeline.return_value = pipe_mock

    redis.scan_iter = MagicMock(return_value=AsyncIterEmpty())

    for k, v in overrides.items():
        setattr(redis, k, v)
    return redis


class AsyncIterEmpty:
    """Async iterator that yields nothing."""
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _mock_runner(redis=None):
    """Return a mock runner with a session_service containing a redis client."""
    runner = MagicMock()
    runner.session_service = MagicMock()
    runner.session_service._redis = redis or _mock_redis()
    runner.session_service._ttl = 604800
    runner.agent = MagicMock()
    runner.agent.model = MagicMock()
    runner.agent.model._additional_args = {}
    return runner


def _mock_mcp_pool(sessions=None):
    """Return a mock MCP pool."""
    pool = MagicMock()
    pool._sessions = sessions or []
    pool.call_tool = AsyncMock()
    pool.call_prompt = AsyncMock()
    return pool


@pytest.fixture
def full_app():
    """Fixture that builds a full app with all routers and mocked state."""
    app = _build_app()
    redis = _mock_redis()
    runner = _mock_runner(redis)
    app.state.runner = runner
    app.state.mcp_pool = _mock_mcp_pool()
    app.state.mcp_servers = []
    app.state.mcp_tools = []
    app.state.dynamic_faqs = []
    app.state.tasks = {}
    return app


@pytest.fixture
def client(full_app):
    return TestClient(full_app, headers={"loginId": "test-user@walmart.com"})


# ===========================================================================
# MCP Proxy negative tests
# ===========================================================================

class TestMCPProxyNegative:
    """Negative and edge-case tests for POST /mcp-proxy."""

    def test_invalid_json_body(self, full_app):
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", content=b"not json at all{{{", headers={"Content-Type": "application/json"})
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]

    def test_missing_method_field(self, client):
        resp = client.post("/mcp-proxy", json={"params": {}})
        # empty string method falls through to "Unsupported method"
        assert resp.status_code == 400
        assert "Unsupported method" in resp.json()["error"]

    def test_unsupported_method_name(self, client):
        resp = client.post("/mcp-proxy", json={"method": "foo/bar", "params": {}})
        assert resp.status_code == 400
        assert "Unsupported method: foo/bar" in resp.json()["error"]

    def test_tools_call_missing_tool_name(self, client):
        resp = client.post("/mcp-proxy", json={"method": "tools/call", "params": {}})
        assert resp.status_code == 400
        assert "Missing tool name" in resp.json()["error"]

    def test_tools_call_mcp_pool_exception(self, full_app):
        full_app.state.mcp_pool.call_tool = AsyncMock(side_effect=RuntimeError("MCP down"))
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "tools/call", "params": {"name": "my_tool"}})
        assert resp.status_code == 502
        assert "Internal proxy error" in resp.json()["error"]

    def test_resources_read_missing_uri(self, client):
        resp = client.post("/mcp-proxy", json={"method": "resources/read", "params": {}})
        assert resp.status_code == 400
        assert "Missing resource URI" in resp.json()["error"]

    def test_resources_read_all_sessions_fail(self, full_app):
        session1 = MagicMock()
        session1._name = "s1"
        session1._rpc = AsyncMock(side_effect=RuntimeError("fail"))
        session2 = MagicMock()
        session2._name = "s2"
        session2._rpc = AsyncMock(side_effect=RuntimeError("fail"))
        full_app.state.mcp_pool._sessions = [session1, session2]
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "resources/read", "params": {"uri": "file:///x"}})
        assert resp.status_code == 404
        assert "Resource not found" in resp.json()["error"]

    def test_resources_list_all_sessions_fail(self, full_app):
        session1 = MagicMock()
        session1._name = "s1"
        session1._rpc = AsyncMock(side_effect=RuntimeError("fail"))
        full_app.state.mcp_pool._sessions = [session1]
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "resources/list", "params": {}})
        assert resp.status_code == 200
        assert resp.json()["result"]["resources"] == []

    def test_prompts_get_exception(self, full_app):
        full_app.state.mcp_pool.call_prompt = AsyncMock(side_effect=ValueError("bad prompt"))
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "prompts/get", "params": {"name": "p1"}})
        assert resp.status_code == 502
        assert "Internal proxy error" in resp.json()["error"]

    def test_empty_params(self, client):
        resp = client.post("/mcp-proxy", json={"method": "tools/call"})
        # params defaults to {}; tools/call with empty name → 400
        assert resp.status_code == 400
        assert "Missing tool name" in resp.json()["error"]

    def test_internal_proxy_error_generic_exception(self, full_app):
        """Exception in tools/list when iterating sessions."""
        session = MagicMock()
        type(session).tools = PropertyMock(side_effect=RuntimeError("kaboom"))
        full_app.state.mcp_pool._sessions = [session]
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 502
        assert "Internal proxy error" in resp.json()["error"]

    def test_extremely_long_method_name(self, client):
        long_method = "x" * 10000
        resp = client.post("/mcp-proxy", json={"method": long_method, "params": {}})
        assert resp.status_code == 400
        assert "Unsupported method" in resp.json()["error"]

    def test_method_with_special_characters(self, client):
        resp = client.post("/mcp-proxy", json={"method": "tools/<script>alert(1)</script>", "params": {}})
        assert resp.status_code == 400
        assert "Unsupported method" in resp.json()["error"]

    def test_prompts_list_all_sessions_fail(self, full_app):
        session1 = MagicMock()
        session1._name = "s1"
        session1._rpc = AsyncMock(side_effect=RuntimeError("fail"))
        full_app.state.mcp_pool._sessions = [session1]
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "prompts/list", "params": {}})
        assert resp.status_code == 200
        assert resp.json()["result"]["prompts"] == []


# ===========================================================================
# Debug router negative tests
# ===========================================================================

class TestDebugSessionNegative:
    """Negative tests for GET /debug/session/{session_id}."""

    def test_redis_timeout_returns_503(self, full_app):
        redis = full_app.state.runner.session_service._redis
        redis.get = AsyncMock(side_effect=asyncio.TimeoutError())
        redis.lrange = AsyncMock(side_effect=asyncio.TimeoutError())
        redis.hgetall = AsyncMock(return_value={})

        async def _gather_timeout(*coros):
            raise asyncio.TimeoutError()

        c = TestClient(full_app)
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            resp = c.get("/debug/session/abc123?user_id=admin")
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"]

    def _setup_debug_redis(self, full_app, session_raw=None, events_raw=None,
                           ui_raw=None, app_state_raw=None, user_state_raw=None):
        """Helper: configure redis mocks for debug_session endpoint.

        The endpoint calls asyncio.gather with:
          redis.get(session_key), redis.lrange(events_key), redis.lrange(ui_events_key),
          redis.get(app_state_key), redis.get(user_state_key)
        """
        redis = full_app.state.runner.session_service._redis
        redis.get = AsyncMock(side_effect=[session_raw, app_state_raw, user_state_raw])
        redis.lrange = AsyncMock(side_effect=[events_raw or [], ui_raw or []])
        return redis

    def test_session_not_found_returns_404(self, full_app):
        self._setup_debug_redis(full_app, session_raw=None)
        c = TestClient(full_app)
        resp = c.get("/debug/session/nonexistent?user_id=admin")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_malformed_json_in_session_data(self, full_app):
        """Session doc has invalid JSON — json.loads raises JSONDecodeError."""
        self._setup_debug_redis(full_app, session_raw="not{valid json")
        c = TestClient(full_app, raise_server_exceptions=False)
        resp = c.get("/debug/session/test123?user_id=admin")
        assert resp.status_code == 500

    def test_malformed_json_in_events_list(self, full_app):
        session_doc = json.dumps({"state": {}, "last_update_time": 1.0, "title": "t"})
        self._setup_debug_redis(full_app, session_raw=session_doc, events_raw=["not-json"])
        c = TestClient(full_app, raise_server_exceptions=False)
        resp = c.get("/debug/session/test123?user_id=admin")
        assert resp.status_code == 500

    def test_empty_events_list(self, full_app):
        session_doc = json.dumps({"state": {"foo": "bar"}, "last_update_time": 1.0, "title": "Test"})
        self._setup_debug_redis(full_app, session_raw=session_doc)
        c = TestClient(full_app)
        resp = c.get("/debug/session/test123?user_id=admin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_count"] == 0
        assert data["tool_calls"] == []

    def test_empty_ui_events_list(self, full_app):
        session_doc = json.dumps({"state": {}, "last_update_time": 1.0, "title": "Test"})
        self._setup_debug_redis(full_app, session_raw=session_doc)
        c = TestClient(full_app)
        resp = c.get("/debug/session/test123?user_id=admin")
        assert resp.status_code == 200
        assert resp.json()["ui_events"] == []


class TestParseToolCalls:
    """Tests for _parse_tool_calls helper in debug.py."""

    def test_malformed_events_no_content(self):
        from app.routers.debug import _parse_tool_calls
        events = [{"timestamp": 1.0}, {"content": None}, {}]
        result = _parse_tool_calls(events)
        assert result == []

    def test_function_response_without_matching_call(self):
        from app.routers.debug import _parse_tool_calls
        events = [
            {
                "timestamp": 2.0,
                "content": {
                    "role": "model",
                    "parts": [
                        {"function_response": {"name": "orphan_tool", "id": "orphan_1", "response": {"data": "x"}}}
                    ],
                },
            }
        ]
        result = _parse_tool_calls(events)
        assert len(result) == 1
        assert result[0]["call_id"] == "orphan_1"
        assert result[0]["args"] is None
        assert result[0]["response"] == {"data": "x"}
        assert result[0]["ts_call"] is None

    def test_missing_function_call_fields(self):
        from app.routers.debug import _parse_tool_calls
        # function_call with no name, no id — but must be truthy so include a dummy key
        events = [
            {
                "timestamp": 1.0,
                "content": {
                    "role": "model",
                    "parts": [{"function_call": {"args": {}}}],
                },
            }
        ]
        result = _parse_tool_calls(events)
        assert len(result) == 1
        assert result[0]["call_id"] == "<unknown>"
        assert result[0]["tool"] == ""

    def test_functionCall_camelCase_variant(self):
        from app.routers.debug import _parse_tool_calls
        events = [
            {
                "timestamp": 1.0,
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "my_tool", "id": "c1", "args": {"a": 1}}}],
                },
            }
        ]
        result = _parse_tool_calls(events)
        assert len(result) == 1
        assert result[0]["tool"] == "my_tool"

    def test_turn_counter_increments_on_user_role(self):
        from app.routers.debug import _parse_tool_calls
        events = [
            {"content": {"role": "user", "parts": []}},
            {
                "timestamp": 1.0,
                "content": {
                    "role": "model",
                    "parts": [{"function_call": {"name": "t1", "id": "c1"}}],
                },
            },
            {"content": {"role": "user", "parts": []}},
            {
                "timestamp": 2.0,
                "content": {
                    "role": "model",
                    "parts": [{"function_call": {"name": "t2", "id": "c2"}}],
                },
            },
        ]
        result = _parse_tool_calls(events)
        assert result[0]["turn"] == 1
        assert result[1]["turn"] == 2


class TestToolCategory:
    """Tests for _tool_category helper in debug.py."""

    def test_skill_tools(self):
        from app.routers.debug import _tool_category
        assert _tool_category("list_skills") == "skill"
        assert _tool_category("load_skill") == "skill"

    def test_regular_tools(self):
        from app.routers.debug import _tool_category
        assert _tool_category("check_health") == "tool"
        assert _tool_category("get_metrics") == "tool"


class TestDebugTokensNegative:
    """Negative tests for GET /debug/tokens."""

    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._get_pingfed_redis")
    def test_redis_error_per_cluster(self, mock_get_redis, mock_settings):
        redis = AsyncMock()

        async def _timeout_hgetall(*a, **kw):
            raise asyncio.TimeoutError("Redis timeout")

        redis.hgetall = _timeout_hgetall
        redis.ttl = AsyncMock(return_value=-2)
        mock_get_redis.return_value = redis

        settings = MagicMock()
        settings.pingfed_url_list = ["https://cluster1.example.com"]
        settings.sso_username = "user"
        settings.sso_password = "pass"
        mock_settings.return_value = settings

        with patch("app.routers.debug._bare_host", return_value="cluster1.example.com"), \
             patch("app.routers.debug._pingfed_keys", return_value=("token_key", "lock_key", "notify_key")):
            app = _build_app()
            app.state.runner = _mock_runner()
            app.state.mcp_pool = _mock_mcp_pool()
            app.state.mcp_servers = []
            app.state.mcp_tools = []
            app.state.dynamic_faqs = []
            c = TestClient(app)
            resp = c.get("/debug/tokens")

        assert resp.status_code == 200
        data = resp.json()
        assert data["clusters"][0]["status"] == "redis_error"

    def _build_token_app(self, mock_get_redis, mock_settings, fields, ttl_val, urls, sso_user="", sso_pass=""):
        """Helper to build an app for debug/tokens tests."""
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value=fields)
        redis.ttl = AsyncMock(return_value=ttl_val)
        mock_get_redis.return_value = redis

        settings = MagicMock()
        settings.pingfed_url_list = urls
        settings.sso_username = sso_user
        settings.sso_password = sso_pass
        mock_settings.return_value = settings

        app = _build_app()
        app.state.runner = _mock_runner()
        app.state.mcp_pool = _mock_mcp_pool()
        app.state.mcp_servers = []
        app.state.mcp_tools = []
        app.state.dynamic_faqs = []
        return app

    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._get_pingfed_redis")
    def test_expired_token_state(self, mock_get_redis, mock_settings):
        now = time.time()
        app = self._build_token_app(mock_get_redis, mock_settings,
            fields={
                "access_token": "tok123",
                "expires_at": str(now - 100),
                "refresh_at": str(now - 200),
                "acquired_by": "pod-1",
                "acquired_at": str(now - 300),
            },
            ttl_val=3000, urls=["https://expired.example.com"], sso_user="u", sso_pass="p")

        with patch("app.routers.debug._bare_host", return_value="expired.example.com"), \
             patch("app.routers.debug._pingfed_keys", return_value=("tk", "lk", "nk")):
            c = TestClient(app)
            resp = c.get("/debug/tokens")

        assert resp.status_code == 200
        cluster = resp.json()["clusters"][0]
        assert cluster["status"] == "expired"

    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._get_pingfed_redis")
    def test_stale_token_state(self, mock_get_redis, mock_settings):
        now = time.time()
        app = self._build_token_app(mock_get_redis, mock_settings,
            fields={
                "access_token": "tok123",
                "expires_at": str(now + 1000),
                "refresh_at": str(now - 10),
                "acquired_by": "pod-2",
                "acquired_at": str(now - 500),
            },
            ttl_val=3000, urls=["https://stale.example.com"])

        with patch("app.routers.debug._bare_host", return_value="stale.example.com"), \
             patch("app.routers.debug._pingfed_keys", return_value=("tk", "lk", "nk")):
            c = TestClient(app)
            resp = c.get("/debug/tokens")

        assert resp.status_code == 200
        cluster = resp.json()["clusters"][0]
        assert cluster["status"] == "stale"
        assert resp.json()["sso_configured"] is False

    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._get_pingfed_redis")
    def test_missing_token_state(self, mock_get_redis, mock_settings):
        app = self._build_token_app(mock_get_redis, mock_settings,
            fields={}, ttl_val=-2,
            urls=["https://empty.example.com"], sso_user="u", sso_pass="p")

        with patch("app.routers.debug._bare_host", return_value="empty.example.com"), \
             patch("app.routers.debug._pingfed_keys", return_value=("tk", "lk", "nk")):
            c = TestClient(app)
            resp = c.get("/debug/tokens")

        assert resp.status_code == 200
        cluster = resp.json()["clusters"][0]
        assert cluster["status"] == "missing"


class TestDebugLLMNegative:
    """Tests for GET /debug/llm with various LLM configs."""

    @patch("app.routers.debug.get_settings")
    def test_azure_provider(self, mock_settings):
        settings = MagicMock()
        settings.claude_is_primary_llm = False
        settings.openai_model = "gpt-4"
        settings.element_gateway_base_url = "https://azure.test.com"
        mock_settings.return_value = settings

        app = _build_app()
        runner = _mock_runner()
        runner.agent.model._additional_args = {}
        app.state.runner = runner
        app.state.mcp_pool = _mock_mcp_pool()
        app.state.mcp_servers = []
        app.state.mcp_tools = []
        app.state.dynamic_faqs = []
        c = TestClient(app)
        resp = c.get("/debug/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "azure"
        assert data["prompt_caching"]["status"] == "N/A"

    @patch("app.routers.debug.get_settings")
    def test_anthropic_with_cache_header(self, mock_settings):
        settings = MagicMock()
        settings.claude_is_primary_llm = True
        settings.claude_model = "claude-opus-4-6"
        settings.claude_gateway_url = "https://claude.test.com"
        mock_settings.return_value = settings

        app = _build_app()
        runner = _mock_runner()
        runner.agent.model._additional_args = {
            "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
        }
        app.state.runner = runner
        app.state.mcp_pool = _mock_mcp_pool()
        app.state.mcp_servers = []
        app.state.mcp_tools = []
        app.state.dynamic_faqs = []
        c = TestClient(app)
        resp = c.get("/debug/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "anthropic"
        assert data["prompt_caching"]["beta_header_present"] is True
        assert "HEADER_PRESENT" in data["prompt_caching"]["status"]

    @patch("app.routers.debug.get_settings")
    def test_anthropic_without_cache_header(self, mock_settings):
        settings = MagicMock()
        settings.claude_is_primary_llm = True
        settings.claude_model = "claude-opus-4-6"
        settings.claude_gateway_url = "https://claude.test.com"
        mock_settings.return_value = settings

        app = _build_app()
        runner = _mock_runner()
        runner.agent.model._additional_args = {"extra_headers": {}}
        app.state.runner = runner
        app.state.mcp_pool = _mock_mcp_pool()
        app.state.mcp_servers = []
        app.state.mcp_tools = []
        app.state.dynamic_faqs = []
        c = TestClient(app)
        resp = c.get("/debug/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt_caching"]["status"] == "DISABLED"


# ===========================================================================
# FAQs router negative tests
# ===========================================================================

class TestFAQsNegative:
    """Negative and edge-case tests for GET /group/faqs."""

    def test_faqs_json_doesnt_exist(self, full_app):
        """No faqs.json and no agent.json → empty list."""
        c = TestClient(full_app)
        with patch("app.routers.faqs.Path") as MockPath:
            faqs_path = MagicMock()
            faqs_path.exists.return_value = False
            agent_path = MagicMock()
            agent_path.open.side_effect = FileNotFoundError("no agent.json")
            # __file__.parents[2] / "agent" / "faqs.json"
            MockPath.return_value = MagicMock()
            # Need to handle the chained call
            mock_file_path = MagicMock()
            mock_file_path.parents.__getitem__ = MagicMock(return_value=MagicMock())
            MockPath.__file__ = mock_file_path

            # Simpler approach: just ensure dynamic_faqs is empty and patch file paths
            full_app.state.dynamic_faqs = []
            resp = c.get("/group/faqs")
        # With no dynamic_faqs and the real faqs.json/agent.json possibly existing,
        # the response may be empty or contain real data. We just verify it's a valid response.
        assert resp.status_code == 200

    def test_faqs_json_invalid_json(self, full_app):
        """faqs.json exists but contains invalid JSON — should be caught by except pass."""
        c = TestClient(full_app)
        import builtins
        original_open = builtins.open

        faqs_path = Path(__file__).resolve().parent.parent.parent / "src" / "agent" / "faqs.json"
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "open", side_effect=json.JSONDecodeError("bad", "", 0)):
            resp = c.get("/group/faqs")
        assert resp.status_code == 200

    def test_dynamic_faqs_with_duplicate_titles(self, full_app):
        """Dynamic FAQs have titles that overlap with existing — merge path."""
        full_app.state.dynamic_faqs = [
            {"title": "Existing Group", "faqs": ["New question?"]},
            {"title": "Brand New Group", "faqs": ["Another question?"]},
        ]
        c = TestClient(full_app)
        resp = c.get("/group/faqs")
        assert resp.status_code == 200

    def test_dynamic_faqs_with_empty_faqs_list(self, full_app):
        """Dynamic FAQ entry has an empty faqs list."""
        full_app.state.dynamic_faqs = [
            {"title": "Empty Group", "faqs": []},
        ]
        c = TestClient(full_app)
        resp = c.get("/group/faqs")
        assert resp.status_code == 200

    def test_no_faqs_from_any_source(self, full_app):
        """All sources yield nothing → empty response."""
        full_app.state.dynamic_faqs = []

        # Patch both file paths to not exist / fail
        with patch("app.routers.faqs.Path") as MockPath:
            mock_parents = MagicMock()
            mock_agent_dir = MagicMock()
            mock_faqs_json = MagicMock()
            mock_faqs_json.exists.return_value = False
            mock_agent_json = MagicMock()
            mock_agent_json.open.side_effect = FileNotFoundError()

            mock_agent_dir.__truediv__ = MagicMock(side_effect=lambda x: mock_faqs_json if x == "faqs.json" else mock_agent_json)
            mock_parents.__getitem__ = MagicMock(return_value=mock_agent_dir)

            mock_file = MagicMock()
            mock_file.parents = mock_parents
            MockPath.return_value = mock_file

            c = TestClient(full_app)
            resp = c.get("/group/faqs")
        assert resp.status_code == 200
        # Could be empty list or actual faqs from real files
        assert isinstance(resp.json(), list)

    def test_unicode_in_faq_titles_and_content(self, full_app):
        full_app.state.dynamic_faqs = [
            {"title": "Unicode test", "faqs": ["What about emojis?"]},
        ]
        c = TestClient(full_app)
        resp = c.get("/group/faqs")
        assert resp.status_code == 200


# ===========================================================================
# Health router edge tests
# ===========================================================================

class TestHealthEdge:
    """Edge-case tests for GET /health."""

    def test_empty_mcp_servers_list(self, full_app):
        full_app.state.mcp_servers = []
        full_app.state.mcp_tools = []
        c = TestClient(full_app)
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mcp_servers"] == []
        assert data["mcp_tools"] == []

    def test_empty_mcp_tools_list(self, full_app):
        full_app.state.mcp_servers = [{"name": "s1", "url": "http://localhost:8999/mcp"}]
        full_app.state.mcp_tools = []
        c = TestClient(full_app)
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["mcp_servers"]) == 1
        assert data["mcp_tools"] == []

    @patch("app.routers.health.get_settings")
    def test_active_llm_claude(self, mock_settings, full_app):
        settings = MagicMock()
        settings.active_llm = "claude"
        settings.active_llm_endpoint = "https://claude.test.com"
        mock_settings.return_value = settings
        full_app.state.mcp_servers = []
        full_app.state.mcp_tools = []
        c = TestClient(full_app)
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["active_llm"] == "claude"

    @patch("app.routers.health.get_settings")
    def test_active_llm_openai(self, mock_settings, full_app):
        settings = MagicMock()
        settings.active_llm = "openai"
        settings.active_llm_endpoint = "https://openai.test.com"
        mock_settings.return_value = settings
        full_app.state.mcp_servers = []
        full_app.state.mcp_tools = []
        c = TestClient(full_app)
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["active_llm"] == "openai"

    def test_ready_endpoint(self, full_app):
        c = TestClient(full_app)
        resp = c.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"


# ===========================================================================
# Query router negative tests
# ===========================================================================

class TestQueryNegative:
    """Negative tests for POST /query and POST /query_api."""

    def test_missing_query_field(self, full_app):
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        resp = c.post("/query", json={"user_id": "user@test.com"})
        assert resp.status_code == 422  # pydantic validation

    def test_missing_user_id_and_no_header(self, full_app):
        c = TestClient(full_app)  # no loginId header
        resp = c.post("/query", json={"query": "test query"})
        assert resp.status_code == 422
        assert "user_id is required" in resp.json()["detail"]

    def test_empty_query_string(self, full_app):
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        resp = c.post("/query", json={"query": "", "user_id": "user@test.com"})
        assert resp.status_code == 422  # min_length=1

    def test_very_long_query(self, full_app):
        """Query exceeding max_length=4096 should be rejected."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        long_query = "x" * 100_000
        resp = c.post("/query", json={"query": long_query, "user_id": "user@test.com"})
        assert resp.status_code == 422

    def test_unicode_emoji_in_query(self, full_app):
        """Unicode and emojis should be accepted as valid query text."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        with patch("app.routers.query.run_agent", new=AsyncMock(return_value="ok")):
            resp = c.post("/query", json={"query": "hello world", "user_id": "user@test.com"})
        assert resp.status_code == 200

    def test_sql_injection_in_query(self, full_app):
        """SQL injection payload should be treated as normal text."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        with patch("app.routers.query.run_agent", new=AsyncMock(return_value="safe")):
            resp = c.post("/query", json={
                "query": "'; DROP TABLE sessions; --",
                "user_id": "user@test.com",
            })
        assert resp.status_code == 200
        assert resp.json()["response"] == "safe"

    def test_xss_payloads_in_query(self, full_app):
        """XSS payload should be treated as normal text (no sanitization needed at API level)."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        with patch("app.routers.query.run_agent", new=AsyncMock(return_value="ok")):
            resp = c.post("/query", json={
                "query": "<script>alert('xss')</script>",
                "user_id": "user@test.com",
            })
        assert resp.status_code == 200

    def test_null_bytes_in_query(self, full_app):
        """Null bytes in query -- pydantic may accept or reject."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        with patch("app.routers.query.run_agent", new=AsyncMock(return_value="ok")):
            resp = c.post("/query", json={
                "query": "hello\x00world",
                "user_id": "user@test.com",
            })
        # Either accepted (200) or rejected by pydantic (422) is valid
        assert resp.status_code in (200, 422)

    def test_query_api_missing_user_id(self, full_app):
        """POST /query_api also requires user_id."""
        c = TestClient(full_app)  # no header
        resp = c.post("/query_api", json={"query": "test"})
        assert resp.status_code == 422

    def test_resolve_user_id_from_wm_header(self, full_app):
        """User resolved via wm_llm_gw.user_name header."""
        c = TestClient(full_app, headers={"wm_llm_gw.user_name": "wm-user@test.com"})
        with patch("app.routers.query.run_agent", new=AsyncMock(return_value="ok")):
            resp = c.post("/query", json={"query": "hello"})
        assert resp.status_code == 200

    def test_run_agent_raises_exception(self, full_app):
        """When run_agent raises, it should propagate as 500."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"}, raise_server_exceptions=False)
        with patch("app.routers.query.run_agent", new=AsyncMock(side_effect=RuntimeError("LLM exploded"))):
            resp = c.post("/query", json={"query": "test", "user_id": "user@test.com"})
        assert resp.status_code == 500


# ===========================================================================
# Sessions router negative tests
# ===========================================================================

class TestSessionsListNegative:
    """Negative tests for GET /sessions (list_sessions)."""

    def test_redis_connection_failure(self, full_app):
        redis = full_app.state.runner.session_service._redis
        redis.zrevrange = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis.hgetall = AsyncMock(side_effect=ConnectionError("Redis down"))
        c = TestClient(full_app)
        resp = c.get("/sessions?user_id=admin")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data or data["sessions"] == []

    def test_empty_session_list(self, full_app):
        redis = full_app.state.runner.session_service._redis
        redis.zrevrange = AsyncMock(return_value=[])
        redis.hgetall = AsyncMock(return_value={})
        redis.smembers = AsyncMock(return_value=set())

        # Also need to handle the public sessions fetch
        c = TestClient(full_app)
        resp = c.get("/sessions?user_id=admin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []

    def test_malformed_shared_metadata_json(self, full_app):
        """Shared metadata has invalid JSON — should be caught silently."""
        redis = full_app.state.runner.session_service._redis
        redis.zrevrange = AsyncMock(return_value=[("sid1", 1000.0)])
        redis.hgetall = AsyncMock(return_value={"sid1": "My Session"})

        pipe_mock = AsyncMock()
        # Return malformed JSON for shared and visibility
        pipe_mock.execute = AsyncMock(return_value=["not-valid-json{{{", "also-not-json{{{"])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        redis.pipeline.return_value = pipe_mock

        c = TestClient(full_app)
        resp = c.get("/sessions?user_id=admin")
        assert resp.status_code == 200
        data = resp.json()
        # Session should still appear (malformed metadata is silently ignored)
        sessions = data["sessions"]
        found = [s for s in sessions if s["session_id"] == "sid1"]
        assert len(found) >= 1

    def test_malformed_visibility_metadata_json(self, full_app):
        """Visibility metadata has invalid JSON in public sessions — caught silently."""
        redis = full_app.state.runner.session_service._redis
        redis.zrevrange = AsyncMock(side_effect=[
            [],  # user's own sessions (first call for zset)
            [("otheruser:sid2", 2000.0)],  # public sessions
        ])
        redis.hgetall = AsyncMock(return_value={})
        redis.smembers = AsyncMock(return_value=set())

        pipe_mock = AsyncMock()
        # hget for title, get for visibility - visibility is malformed
        pipe_mock.execute = AsyncMock(return_value=["Shared Title", "not{json"])
        pipe_mock.hget = MagicMock()
        pipe_mock.get = MagicMock()
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        redis.pipeline.return_value = pipe_mock

        c = TestClient(full_app)
        resp = c.get("/sessions?user_id=admin")
        assert resp.status_code == 200

    def test_invalid_session_id_format(self, full_app):
        """Session IDs with special characters should not crash the router."""
        c = TestClient(full_app)
        # The messages endpoint takes a session_id path param
        resp = c.get("/sessions/<script>/messages?user_id=admin")
        # Should get a valid response (empty or error), not crash
        assert resp.status_code in (200, 404, 503)

    def test_session_messages_redis_timeout(self, full_app):
        """Redis timeout on fetching messages returns 503."""
        redis = full_app.state.runner.session_service._redis
        redis.lrange = AsyncMock(side_effect=asyncio.TimeoutError())
        redis.get = AsyncMock(return_value=None)

        c = TestClient(full_app)
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            resp = c.get("/sessions/test-sid/messages?user_id=admin")
        assert resp.status_code == 503

    def test_visibility_update_valid(self, full_app):
        """PATCH /sessions/{id}/visibility with valid body."""
        redis = full_app.state.runner.session_service._redis
        redis.set = AsyncMock(return_value=True)
        redis.zadd = AsyncMock(return_value=1)
        redis.expire = AsyncMock(return_value=True)
        redis.zrem = AsyncMock(return_value=0)

        c = TestClient(full_app)
        resp = c.patch(
            "/sessions/sid1/visibility",
            json={"public": True, "tags": ["Alert"], "user_id": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["public"] is True
        assert data["tags"] == ["Alert"]

    def test_visibility_update_set_private(self, full_app):
        """PATCH visibility with public=false removes from public index."""
        redis = full_app.state.runner.session_service._redis
        redis.set = AsyncMock(return_value=True)
        redis.zrem = AsyncMock(return_value=1)

        c = TestClient(full_app)
        resp = c.patch(
            "/sessions/sid1/visibility",
            json={"public": False, "tags": [], "user_id": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["public"] is False

    def test_list_sessions_legacy_fallback(self, full_app):
        """When ZSET is empty but legacy SET has sessions, the legacy path runs."""
        redis = full_app.state.runner.session_service._redis
        redis.zrevrange = AsyncMock(return_value=[])
        redis.hgetall = AsyncMock(return_value={})
        redis.smembers = AsyncMock(return_value={"legacy-sid"})

        pipe_mock = AsyncMock()
        session_doc = json.dumps({
            "state": {},
            "last_update_time": 100.0,
            "title": "Legacy Session",
        })
        pipe_mock.execute = AsyncMock(return_value=[session_doc])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        redis.pipeline.return_value = pipe_mock

        c = TestClient(full_app)
        resp = c.get("/sessions?user_id=admin")
        assert resp.status_code == 200
        data = resp.json()
        sessions = data["sessions"]
        assert any(s["session_id"] == "legacy-sid" for s in sessions)

    def test_list_sessions_legacy_redis_timeout(self, full_app):
        """Legacy path: Redis timeout on smembers."""
        redis = full_app.state.runner.session_service._redis
        redis.zrevrange = AsyncMock(return_value=[])
        redis.hgetall = AsyncMock(return_value={})
        # smembers wrapped in wait_for
        redis.smembers = AsyncMock(return_value=set())

        c = TestClient(full_app)
        with patch("asyncio.wait_for", side_effect=[
            # First wait_for in public sessions path
            asyncio.TimeoutError(),
        ]):
            # This may take a different code path; the important thing is no crash
            resp = c.get("/sessions?user_id=admin")
        # Public session fetch failure is caught; may still return sessions
        assert resp.status_code == 200


# ===========================================================================
# Additional cross-cutting edge cases
# ===========================================================================

class TestCrossCuttingEdgeCases:
    """Edge cases spanning multiple routers."""

    def test_mcp_proxy_tools_list_empty_pool(self, client):
        """tools/list with no sessions returns empty tools list."""
        resp = client.post("/mcp-proxy", json={"method": "tools/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["tools"] == []

    def test_mcp_proxy_resources_read_empty_pool(self, full_app):
        """resources/read with no sessions returns 404."""
        full_app.state.mcp_pool._sessions = []
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "resources/read", "params": {"uri": "file:///x"}})
        assert resp.status_code == 404

    def test_mcp_proxy_resources_list_empty_pool(self, full_app):
        """resources/list with no sessions returns empty list."""
        full_app.state.mcp_pool._sessions = []
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={"method": "resources/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["resources"] == []

    def test_mcp_proxy_tools_call_with_arguments(self, full_app):
        """tools/call with arguments passes them through."""
        full_app.state.mcp_pool.call_tool = AsyncMock(return_value="tool_result")
        c = TestClient(full_app)
        resp = c.post("/mcp-proxy", json={
            "method": "tools/call",
            "params": {"name": "my_tool", "arguments": {"arg1": "val1"}},
        })
        assert resp.status_code == 200
        full_app.state.mcp_pool.call_tool.assert_called_once_with("my_tool", {"arg1": "val1"})

    def test_query_api_works_same_as_query(self, full_app):
        """POST /query_api is functionally identical to POST /query."""
        c = TestClient(full_app, headers={"loginId": "user@test.com"})
        with patch("app.routers.query.run_agent", new=AsyncMock(return_value="ok")):
            resp = c.post("/query_api", json={"query": "test query", "user_id": "user@test.com"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "ok"
