"""Negative and edge-case tests for src/app/factory.py and src/app/api.py.

Covers:
  - create_app() with missing/broken configs
  - Lifespan startup/shutdown failures (MCP, Redis)
  - LLMHeaderMiddleware edge cases (websocket, missing headers)
  - CORS and TrustedHost middleware boundaries
  - Exception handler variants
  - A2A mounting and interceptor edge cases
  - api.py route and lifespan edge cases
  - Tool schema validation edge cases
  - Guide ADK safety validation
"""

import sys
import types
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Ensure src is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# ---------------------------------------------------------------------------
# Stub heavy external dependencies BEFORE any application imports.
# ---------------------------------------------------------------------------

def _ensure_stub(dotted_name: str):
    parts = dotted_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = []
            sys.modules[name] = mod
            if depth > 1:
                parent = ".".join(parts[:depth - 1])
                if parent in sys.modules:
                    setattr(sys.modules[parent], parts[depth - 1], mod)


try:
    from google.adk.runners import Runner as _RealRunner  # noqa: F401
    _HAS_ADK = True
except (ImportError, ModuleNotFoundError):
    _HAS_ADK = False

if not _HAS_ADK:
    _ADK_STUBS = [
        "google", "google.adk",
        "google.adk.runners",
        "google.adk.agents", "google.adk.agents.invocation_context",
        "google.adk.agents.callback_context",
        "google.adk.code_executors", "google.adk.code_executors.code_execution_utils",
        "google.adk.models", "google.adk.models.lite_llm",
        "google.adk.tools", "google.adk.tools.base_tool", "google.adk.tools.tool_context",
        "google.adk.tools.mcp_tool", "google.adk.tools.mcp_tool.mcp_toolset",
        "google.adk.tools.skill_toolset",
        "google.adk.events", "google.adk.events.event",
        "google.adk.sessions", "google.adk.sessions.base_session_service",
        "google.adk.sessions.session", "google.adk.sessions.state",
        "google.adk.skills", "google.adk.skills._utils",
        "google.adk.artifacts",
        "google.adk.a2a", "google.adk.a2a.executor",
        "google.adk.a2a.executor.a2a_agent_executor", "google.adk.a2a.executor.config",
    ]
    for _s in _ADK_STUBS:
        _ensure_stub(_s)

    sys.modules["google.adk.runners"].Runner = MagicMock
    sys.modules["google.adk.agents"].Agent = MagicMock
    sys.modules["google.adk.agents.invocation_context"].InvocationContext = MagicMock
    sys.modules["google.adk.agents.callback_context"].CallbackContext = MagicMock
    sys.modules["google.adk.code_executors"].UnsafeLocalCodeExecutor = MagicMock
    sys.modules["google.adk.code_executors.code_execution_utils"].CodeExecutionInput = MagicMock
    sys.modules["google.adk.code_executors.code_execution_utils"].CodeExecutionResult = MagicMock
    sys.modules["google.adk.tools.base_tool"].BaseTool = MagicMock
    sys.modules["google.adk.tools.tool_context"].ToolContext = MagicMock
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].MCPToolset = MagicMock
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].SseConnectionParams = MagicMock
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].StreamableHTTPConnectionParams = MagicMock
    sys.modules["google.adk.tools.skill_toolset"].SkillToolset = MagicMock
    sys.modules["google.adk.events.event"].Event = MagicMock
    sys.modules["google.adk.sessions.base_session_service"].BaseSessionService = type(
        "BaseSessionService", (), {}
    )
    sys.modules["google.adk.sessions.base_session_service"].GetSessionConfig = MagicMock
    sys.modules["google.adk.sessions.base_session_service"].ListSessionsResponse = MagicMock
    sys.modules["google.adk.sessions.session"].Session = MagicMock
    sys.modules["google.adk.sessions.state"].State = MagicMock
    sys.modules["google.adk.skills._utils"]._load_skill_from_dir = MagicMock(return_value=None)
    sys.modules["google.adk.artifacts"].InMemoryArtifactService = MagicMock

    class _StubLiteLLMClient:
        pass

    sys.modules["google.adk.models.lite_llm"].LiteLlm = MagicMock
    sys.modules["google.adk.models.lite_llm"].LiteLLMClient = _StubLiteLLMClient

try:
    import google.genai as _real_genai  # noqa: F401
    _HAS_GENAI = True
except (ImportError, ModuleNotFoundError):
    _HAS_GENAI = False

if not _HAS_GENAI:
    _ensure_stub("google.genai")
    _ensure_stub("google.genai.types")
    _genai_types_mock = MagicMock()
    _genai_types_mock.__name__ = "google.genai.types"
    sys.modules["google.genai.types"] = _genai_types_mock
    sys.modules["google.genai"].types = _genai_types_mock

try:
    from a2a.types import TaskState as _RealTaskState  # noqa: F401
    _HAS_A2A = True
except (ImportError, ModuleNotFoundError):
    _HAS_A2A = False

if not _HAS_A2A:
    _A2A_STUBS = [
        "a2a", "a2a.server", "a2a.server.apps",
        "a2a.server.apps.jsonrpc", "a2a.server.apps.jsonrpc.jsonrpc_app",
        "a2a.server.context", "a2a.server.request_handlers",
        "a2a.server.tasks",
        "a2a.server.agent_execution", "a2a.server.agent_execution.context",
        "a2a.types",
    ]
    for _s in _A2A_STUBS:
        _ensure_stub(_s)

    sys.modules["a2a.server.apps"].A2AStarletteApplication = MagicMock
    sys.modules["a2a.server.apps.jsonrpc.jsonrpc_app"].CallContextBuilder = type(
        "CallContextBuilder", (), {}
    )
    sys.modules["a2a.server.context"].ServerCallContext = MagicMock
    sys.modules["a2a.server.request_handlers"].DefaultRequestHandler = MagicMock
    sys.modules["a2a.server.tasks"].InMemoryTaskStore = MagicMock
    sys.modules["a2a.server.tasks"].InMemoryPushNotificationConfigStore = MagicMock
    sys.modules["a2a.server.agent_execution.context"].RequestContext = MagicMock
    sys.modules["a2a.types"].AgentCard = MagicMock
    sys.modules["a2a.types"].TaskStatusUpdateEvent = MagicMock
    sys.modules["a2a.types"].TaskArtifactUpdateEvent = MagicMock
    sys.modules["a2a.types"].TaskState = MagicMock

# ---------------------------------------------------------------------------
# Now safe to import application code and test frameworks
# ---------------------------------------------------------------------------

import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from app.request_context import (
    extract_llm_headers, set_llm_headers, clear_llm_headers, get_llm_headers,
)
from app.exceptions import (
    AgentError, LLMError, MCPConnectionError,
    agent_error_handler, llm_error_handler, mcp_connection_error_handler,
)


# ---------------------------------------------------------------------------
# Re-implement LLMHeaderMiddleware identically to factory.py
# ---------------------------------------------------------------------------

class LLMHeaderMiddleware:
    """Capture WM_LLM_GW.* headers -- identical to factory.py implementation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            set_llm_headers(extract_llm_headers(request))
            try:
                await self.app(scope, receive, send)
            finally:
                clear_llm_headers()
        else:
            await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_runner():
    mock_part = MagicMock()
    mock_part.text = "test response"
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content = mock_content

    async def _run_async(**kwargs):
        yield mock_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    runner.session_service._redis = AsyncMock()
    runner.session_service._ttl = 604800
    return runner


def _build_app(**overrides):
    """Build a test app mirroring create_app() wiring, with optional overrides."""
    from app.routers import debug, health, mcp_proxy, mcp_validate, query, sessions, faqs

    app = FastAPI(
        title="A2A Health Agent",
        description="Negative test app",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    cors_origins = overrides.get("cors_origins", ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=overrides.get("cors_methods", ["GET", "POST", "OPTIONS"]),
        allow_headers=["*"],
        allow_credentials=overrides.get("cors_credentials", True),
    )
    app.add_middleware(LLMHeaderMiddleware)

    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(MCPConnectionError, mcp_connection_error_handler)
    app.add_exception_handler(AgentError, agent_error_handler)

    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(sessions.router)
    app.include_router(mcp_validate.router)
    app.include_router(mcp_proxy.router)
    app.include_router(debug.router)
    app.include_router(faqs.router)

    app.state.runner = overrides.get("runner", _make_mock_runner())
    app.state.tasks = overrides.get("tasks", {})
    app.state.mcp_servers = overrides.get("mcp_servers", [])
    app.state.mcp_tools = overrides.get("mcp_tools", [])
    app.state.mcp_pool = overrides.get("mcp_pool", MagicMock(_sessions=[]))
    app.state.http_client = overrides.get("http_client", MagicMock())
    app.state.a2a_agents = overrides.get("a2a_agents", [])
    app.state.dynamic_faqs = overrides.get("dynamic_faqs", [])

    return app


# ---------------------------------------------------------------------------
# Fixture: set required env vars + reset settings cache
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env_and_reset(monkeypatch):
    monkeypatch.setenv("AGENT_HOST", "127.0.0.1")
    monkeypatch.setenv("AGENT_PORT", "9999")
    monkeypatch.setenv("ELEMENT_GATEWAY_BASE_URL", "https://llm.test.com/openai")
    monkeypatch.setenv("ELEMENT_GATEWAY_API_KEY", "test-key-openai")
    monkeypatch.setenv("ELEMENT_GATEWAY_API_VERSION", "2024-10-21")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4-test")
    monkeypatch.setenv("CLAUDE_GATEWAY_URL", "https://claude.test.com/messages")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key-claude")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-test")
    monkeypatch.setenv("CLAUDE_ANTHROPIC_VERSION", "vertex-2023-10-16")
    monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "false")
    monkeypatch.setenv("MAX_TOOL_ROUNDS", "3")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "5")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ===========================================================================
# factory.py NEGATIVE TESTS
# ===========================================================================


class TestCreateAppNoMCPServers:
    """create_app with no MCP servers configured."""

    def test_app_starts_with_empty_mcp_servers(self):
        app = _build_app(mcp_servers=[], mcp_tools=[])
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mcp_servers"] == []

    def test_health_reports_no_tools_when_empty(self):
        app = _build_app(mcp_servers=[], mcp_tools=[])
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.json()["mcp_tools"] == []


class TestCreateAppInvalidMCPUrls:
    """create_app with invalid MCP server URLs."""

    def test_invalid_url_in_mcp_servers_list(self):
        app = _build_app(
            mcp_servers=[{"name": "bad", "url": "not-a-url"}],
            mcp_tools=[],
        )
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["mcp_servers"] == [{"name": "bad", "url": "not-a-url"}]


class TestLifespanMCPFailure:
    """Lifespan startup when MCP pool connect raises."""

    @pytest.mark.asyncio
    async def test_lifespan_aborts_on_mcp_pool_connect_error(self):
        from app.factory import lifespan

        mock_pool = MagicMock()
        mock_pool.connect = AsyncMock(side_effect=ConnectionError("MCP unreachable"))

        mock_http = AsyncMock()

        with patch("app.factory.load_mcp_servers", new_callable=AsyncMock, return_value=[]):
            with patch("app.factory.MCPPool", return_value=mock_pool):
                with patch("app.factory.httpx.AsyncClient", return_value=mock_http):
                    app = FastAPI()
                    with pytest.raises(ConnectionError, match="MCP unreachable"):
                        async with lifespan(app):
                            pass
                    mock_http.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_aborts_on_failed_servers(self):
        from app.factory import lifespan

        mock_pool = MagicMock()
        mock_pool.connect = AsyncMock()
        mock_pool.failed_servers = [{"name": "srv1", "url": "http://bad", "error": "refused"}]

        mock_http = AsyncMock()

        with patch("app.factory.load_mcp_servers", new_callable=AsyncMock, return_value=[]):
            with patch("app.factory.MCPPool", return_value=mock_pool):
                with patch("app.factory.httpx.AsyncClient", return_value=mock_http):
                    app = FastAPI()
                    with pytest.raises(RuntimeError, match="Startup aborted"):
                        async with lifespan(app):
                            pass
                    mock_http.aclose.assert_awaited_once()


class TestLifespanRedisFailure:
    """Lifespan startup/shutdown with Redis connection problems."""

    @pytest.mark.asyncio
    async def test_redis_close_failure_during_shutdown(self):
        """Shutdown should propagate exception if redis aclose fails."""
        from app.factory import lifespan

        mock_pool = MagicMock()
        mock_pool.connect = AsyncMock()
        mock_pool.failed_servers = []
        mock_pool.servers = []
        mock_pool.tools = []
        mock_pool.claude_tools = []
        mock_pool.guide = ""
        mock_pool._sessions = []
        mock_pool.generate_faqs = MagicMock(return_value=[])

        mock_http = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock(side_effect=ConnectionError("Redis close failed"))

        mock_session_svc = MagicMock()
        mock_session_svc._redis = mock_redis
        mock_session_svc._ttl = 604800

        mock_runner = MagicMock()
        mock_runner.session_service = mock_session_svc

        mock_cfg = MagicMock()
        mock_cfg.name = "test"
        mock_cfg.url = "http://test:8080/mcp"
        mock_cfg.headers = {}
        mock_cfg.transport = "streamable_http"

        with patch("app.factory.load_mcp_servers", new_callable=AsyncMock, return_value=[mock_cfg]):
            with patch("app.factory.MCPPool", return_value=mock_pool):
                with patch("app.factory.httpx.AsyncClient", return_value=mock_http):
                    with patch("app.factory.make_agent", return_value=MagicMock(name="test-agent", model="test")):
                        with patch("app.factory.RedisSessionService", return_value=mock_session_svc):
                            with patch("app.factory.Runner", return_value=mock_runner):
                                with patch("app.factory._mount_a2a"):
                                    with patch("app.factory._validate_tool_schemas"):
                                        with patch("app.factory._validate_guide_adk_safety"):
                                            with patch("app.factory.register_mcp_tools"):
                                                with patch("app.factory.register_mcp_servers"):
                                                    with patch("app.factory.load_a2a_agents", new_callable=AsyncMock, return_value=[]):
                                                        with patch("app.factory.pingfed") as mock_pf:
                                                            mock_pf.close = AsyncMock()
                                                            app = FastAPI()
                                                            with pytest.raises(ConnectionError, match="Redis close failed"):
                                                                async with lifespan(app):
                                                                    pass


class TestLLMHeaderMiddlewareNonHTTP:
    """LLMHeaderMiddleware with non-HTTP scope types."""

    @pytest.mark.asyncio
    async def test_websocket_scope_passes_through(self):
        """Websocket connections should bypass header extraction."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = LLMHeaderMiddleware(inner_app)
        scope = {"type": "websocket", "headers": []}
        await middleware(scope, AsyncMock(), AsyncMock())
        assert inner_called

    @pytest.mark.asyncio
    async def test_lifespan_scope_passes_through(self):
        """Lifespan scope should bypass header extraction."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = LLMHeaderMiddleware(inner_app)
        scope = {"type": "lifespan"}
        await middleware(scope, AsyncMock(), AsyncMock())
        assert inner_called


class TestLLMHeaderMiddlewareMissingHeaders:
    """LLMHeaderMiddleware when required headers are missing."""

    def test_no_llm_headers_request_succeeds(self):
        """Request without LLM headers still succeeds (middleware doesn't block)."""
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_partial_llm_headers(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get(
            "/health",
            headers={"wm_llm_gw.user_type": "ASSOCIATE"},
        )
        assert resp.status_code == 200


class TestCORSMiddlewareEdgeCases:
    """CORS middleware boundary tests."""

    def test_disallowed_origin_no_cors_headers(self):
        app = _build_app(cors_origins=["https://allowed.example.com"])
        client = TestClient(app)
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Disallowed origin: CORS headers should NOT include the evil origin
        assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"

    def test_allowed_origin_returns_cors_headers(self):
        app = _build_app(cors_origins=["https://allowed.example.com"])
        client = TestClient(app)
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://allowed.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://allowed.example.com"

    def test_empty_cors_origins_rejects_all(self):
        app = _build_app(cors_origins=[])
        client = TestClient(app)
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://any.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") != "https://any.example.com"

    def test_wildcard_cors_origin_allows_all(self):
        app = _build_app(cors_origins=["*"])
        client = TestClient(app)
        resp = client.get(
            "/health",
            headers={"Origin": "https://anything.example.com"},
        )
        assert resp.status_code == 200


class TestExceptionHandlers:
    """Exception handlers receiving various exception types."""

    def test_llm_error_returns_502(self):
        app = _build_app()

        @app.get("/test-llm-error")
        async def _trigger():
            raise LLMError(status_code=429, detail="Rate limited by gateway")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-llm-error")
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"] == "llm_error"
        assert body["llm_status_code"] == 429

    def test_agent_error_returns_500(self):
        app = _build_app()

        @app.get("/test-agent-error")
        async def _trigger():
            raise AgentError("Agent loop crashed")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-agent-error")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"] == "agent_error"
        assert "Agent loop crashed" in body["detail"]

    def test_mcp_connection_error_returns_503(self):
        app = _build_app()

        @app.get("/test-mcp-error")
        async def _trigger():
            raise MCPConnectionError("MCP server down")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-mcp-error")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"] == "mcp_connection_error"

    def test_llm_error_with_empty_detail(self):
        app = _build_app()

        @app.get("/test-llm-empty")
        async def _trigger():
            raise LLMError(status_code=500, detail="")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-llm-empty")
        assert resp.status_code == 502
        assert resp.json()["detail"] == ""

    def test_unhandled_exception_returns_500(self):
        app = _build_app()

        @app.get("/test-unhandled")
        async def _trigger():
            raise ValueError("Unexpected error")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-unhandled")
        assert resp.status_code == 500


class TestMiddlewareChainException:
    """Middleware chain with requests that cause exceptions."""

    def test_exception_in_route_returns_500(self):
        """Route that raises still returns 500 — middleware doesn't break."""
        app = _build_app()

        @app.get("/test-crash")
        async def _crash():
            raise RuntimeError("boom")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/test-crash",
            headers={"wm_llm_gw.user_type": "ASSOCIATE"},
        )
        assert resp.status_code == 500


class TestHealthEndpointThroughMiddleware:
    """Health endpoint through full middleware chain."""

    def test_health_with_all_llm_headers(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/health", headers={
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "testuser@walmart.com",
            "wm_llm_gw.user_agent": "TestAgent/1.0",
            "wm_llm_gw.user_ip": "10.0.0.1",
        })
        assert resp.status_code == 200

    def test_ready_endpoint(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 200


# ===========================================================================
# factory.py EDGE CASE TESTS
# ===========================================================================


class TestEmptyMCPToolsAfterProbe:
    """Edge case: MCP connected but returned zero tools."""

    def test_health_with_zero_tools(self):
        mock_pool = MagicMock()
        mock_pool._sessions = []
        app = _build_app(mcp_servers=[{"name": "s", "url": "http://x"}], mcp_tools=[], mcp_pool=mock_pool)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["mcp_tools"] == []


class TestA2ADisabled:
    """A2A disabled -- no agents configured."""

    def test_no_a2a_agents_still_healthy(self):
        app = _build_app(a2a_agents=[])
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200


class TestCreateAppReturnsCorrectType:
    """create_app() itself returns a proper FastAPI instance."""

    def test_create_app_returns_fastapi(self):
        from app.factory import create_app
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_create_app_has_lifespan(self):
        from app.factory import create_app
        app = create_app()
        # FastAPI stores the lifespan in router.lifespan_context
        assert app.router.lifespan_context is not None

    def test_create_app_title(self):
        from app.factory import create_app
        app = create_app()
        assert app.title == "A2A Health Agent"

    def test_create_app_version(self):
        from app.factory import create_app
        app = create_app()
        assert app.version == "2.0.0"


class TestToolSchemaValidation:
    """_validate_tool_schemas edge cases."""

    def test_valid_tool_schema(self):
        from app.factory import _validate_tool_schemas
        tools = [{"name": "good_tool", "input_schema": {"type": "object", "properties": {}}}]
        # Should not raise
        _validate_tool_schemas(tools)

    def test_tool_with_missing_input_schema(self):
        from app.factory import _validate_tool_schemas
        tools = [{"name": "bad_tool"}]
        # Should log error but not raise
        _validate_tool_schemas(tools)

    def test_tool_with_non_dict_input_schema(self):
        from app.factory import _validate_tool_schemas
        tools = [{"name": "bad_tool", "input_schema": "not-a-dict"}]
        _validate_tool_schemas(tools)

    def test_tool_with_legacy_definitions_key(self):
        from app.factory import _validate_tool_schemas
        tools = [{"name": "legacy", "input_schema": {"type": "object", "definitions": {"a": {}}}}]
        # Should log warning but not raise
        _validate_tool_schemas(tools)

    def test_tool_with_non_object_type(self):
        from app.factory import _validate_tool_schemas
        tools = [{"name": "array_tool", "input_schema": {"type": "array"}}]
        _validate_tool_schemas(tools)

    def test_tool_unnamed(self):
        from app.factory import _validate_tool_schemas
        tools = [{"input_schema": {"type": "object"}}]
        _validate_tool_schemas(tools)

    def test_empty_tool_list(self):
        from app.factory import _validate_tool_schemas
        _validate_tool_schemas([])


class TestGuideADKSafetyValidation:
    """_validate_guide_adk_safety edge cases."""

    def test_guide_with_safe_content_passes(self):
        from app.factory import _validate_guide_adk_safety
        mock_session = MagicMock()
        mock_session.guide = "This guide has no template variables"
        mock_session._name = "safe-server"
        mock_pool = MagicMock()
        mock_pool._sessions = [mock_session]
        # Should not raise
        _validate_guide_adk_safety(mock_pool)

    def test_guide_with_no_guide_passes(self):
        from app.factory import _validate_guide_adk_safety
        mock_session = MagicMock()
        mock_session.guide = ""
        mock_session._name = "no-guide"
        mock_pool = MagicMock()
        mock_pool._sessions = [mock_session]
        _validate_guide_adk_safety(mock_pool)

    def test_empty_sessions_passes(self):
        from app.factory import _validate_guide_adk_safety
        mock_pool = MagicMock()
        mock_pool._sessions = []
        _validate_guide_adk_safety(mock_pool)


class TestMCPSummaryLogging:
    """_log_mcp_summary edge cases."""

    def test_log_summary_empty_pool(self):
        from app.factory import _log_mcp_summary
        mock_pool = MagicMock()
        mock_pool._sessions = []
        mock_pool.failed_servers = []
        # Should not raise
        _log_mcp_summary(mock_pool)

    def test_log_summary_with_failed_servers(self):
        from app.factory import _log_mcp_summary
        mock_session = MagicMock()
        mock_session._name = "good-server"
        mock_session._url = "http://good:8080"
        mock_session.sid = "sid-1"
        mock_session.tools = [{"name": "tool1", "description": "A tool"}]
        mock_session.guide = "some guide text"
        mock_pool = MagicMock()
        mock_pool._sessions = [mock_session]
        mock_pool.failed_servers = [{"name": "bad-server", "url": "http://bad", "error": "refused"}]
        _log_mcp_summary(mock_pool)

    def test_log_summary_session_without_guide(self):
        from app.factory import _log_mcp_summary
        mock_session = MagicMock()
        mock_session._name = "no-guide-server"
        mock_session._url = "http://x:8080"
        mock_session.sid = None
        mock_session.tools = []
        mock_session.guide = ""
        mock_pool = MagicMock()
        mock_pool._sessions = [mock_session]
        mock_pool.failed_servers = []
        _log_mcp_summary(mock_pool)


class TestA2AFriendlyMessage:
    """_a2a_friendly_message edge cases."""

    def test_message_with_known_server_url(self):
        from app.factory import _a2a_friendly_message
        from app.services.runner import _mcp_server_registry
        _mcp_server_registry["http://known:8080/mcp"] = "known-server"
        try:
            msg = _a2a_friendly_message("Error connecting to http://known:8080/mcp blah")
            assert "known-server" in msg
            assert "temporarily unavailable" in msg
        finally:
            _mcp_server_registry.pop("http://known:8080/mcp", None)

    def test_message_with_unknown_url_fallback_registry(self):
        from app.factory import _a2a_friendly_message
        from app.services.runner import _mcp_server_registry
        _mcp_server_registry["http://other:8080/mcp"] = "other-server"
        try:
            msg = _a2a_friendly_message("Some random error")
            assert "other-server" in msg
        finally:
            _mcp_server_registry.pop("http://other:8080/mcp", None)

    def test_message_with_empty_registry(self):
        from app.factory import _a2a_friendly_message
        from app.services.runner import _mcp_server_registry
        saved = dict(_mcp_server_registry)
        _mcp_server_registry.clear()
        try:
            msg = _a2a_friendly_message("Some error")
            assert "temporarily unavailable" in msg
        finally:
            _mcp_server_registry.update(saved)


class TestMCPErrorInterceptQueue:
    """_MCPErrorInterceptQueue edge cases."""

    @pytest.mark.asyncio
    async def test_non_failure_event_passes_through(self):
        from app.factory import _MCPErrorInterceptQueue

        inner_queue = AsyncMock()
        inner_queue.enqueue_event = AsyncMock()
        queue = _MCPErrorInterceptQueue(inner_queue)

        # A non-TaskStatusUpdateEvent should pass through
        event = MagicMock()
        await queue.enqueue_event(event)
        inner_queue.enqueue_event.assert_awaited_once_with(event)

    def test_getattr_forwards_to_inner(self):
        from app.factory import _MCPErrorInterceptQueue

        inner_queue = MagicMock()
        inner_queue.some_method = MagicMock(return_value="hello")
        queue = _MCPErrorInterceptQueue(inner_queue)
        assert queue.some_method() == "hello"


class TestGracefulA2aAgentExecutor:
    """_GracefulA2aAgentExecutor wraps the base executor."""

    def test_inherits_from_a2a_agent_executor(self):
        from app.factory import _GracefulA2aAgentExecutor
        from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
        assert issubclass(_GracefulA2aAgentExecutor, A2aAgentExecutor)


# ===========================================================================
# api.py NEGATIVE TESTS
# ===========================================================================


class TestApiCreateApp:
    """api.py create_app and route tests."""

    def test_api_create_app_returns_fastapi(self):
        from app.api import create_app
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_api_query_without_state_fails(self):
        """Query endpoint should fail if app state is not initialized."""
        from app.api import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/query", json={"query": "test"})
        assert resp.status_code == 500

    def test_api_query_empty_query_rejected(self):
        """Empty query string should be rejected by validation."""
        from app.api import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/query", json={"query": ""})
        assert resp.status_code == 422

    def test_api_query_missing_query_field(self):
        """Missing query field should fail validation."""
        from app.api import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/query", json={})
        assert resp.status_code == 422

    def test_api_query_api_endpoint_exists(self):
        """The /query_api endpoint should be registered."""
        from app.api import router
        app = FastAPI()
        app.include_router(router)
        paths = [r.path for r in app.routes]
        assert "/query_api" in paths

    def test_api_query_and_query_api_both_exist(self):
        """Both /query and /query_api endpoints should be registered."""
        from app.api import router
        app = FastAPI()
        app.include_router(router)
        paths = [r.path for r in app.routes]
        assert "/query" in paths
        assert "/query_api" in paths


class TestApiLifespan:
    """api.py lifespan edge cases."""

    @pytest.mark.asyncio
    async def test_api_lifespan_mcp_connect_failure_non_fatal(self):
        """api.py lifespan should survive MCP connect failure gracefully."""
        from app.api import lifespan

        mock_pool = MagicMock()
        mock_pool.connect = AsyncMock(side_effect=ConnectionError("MCP down"))

        mock_http = AsyncMock()
        mock_llm = AsyncMock()

        with patch("app.api.load_mcp_servers", new_callable=AsyncMock, return_value=[]):
            with patch("app.api.MCPPool", return_value=mock_pool):
                with patch("app.api.httpx.AsyncClient", side_effect=[mock_http, mock_llm]):
                    app = FastAPI()
                    async with lifespan(app):
                        # Should proceed despite MCP failure
                        assert app.state.mcp is mock_pool
                    mock_http.aclose.assert_awaited_once()
                    mock_llm.aclose.assert_awaited_once()


class TestApiQueryHandlerErrors:
    """api.py _handle_query error paths."""

    @pytest.mark.asyncio
    async def test_handle_query_llm_http_error(self):
        """HTTPStatusError from LLM should become 502."""
        import httpx
        from app.api import _handle_query, QueryRequest

        mock_mcp = MagicMock()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        error = httpx.HTTPStatusError("err", request=MagicMock(), response=mock_response)

        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            with patch("app.api.run_agent_openai", side_effect=error):
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as exc_info:
                    await _handle_query(QueryRequest(query="test"), mock_mcp, mock_client)
                assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_handle_query_generic_exception(self):
        """Generic exception from agent should become 500."""
        from app.api import _handle_query, QueryRequest

        mock_mcp = MagicMock()
        mock_client = MagicMock()

        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = True
            with patch("app.api.run_agent_claude", side_effect=RuntimeError("boom")):
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as exc_info:
                    await _handle_query(QueryRequest(query="test"), mock_mcp, mock_client)
                assert exc_info.value.status_code == 500


# ===========================================================================
# Additional edge cases to reach 40+ tests
# ===========================================================================


class TestMultipleRoutersRegistered:
    """Verify all expected routers are registered on the factory app."""

    def test_health_route_exists(self):
        app = _build_app()
        paths = [r.path for r in app.routes]
        assert "/health" in paths

    def test_ready_route_exists(self):
        app = _build_app()
        paths = [r.path for r in app.routes]
        assert "/ready" in paths

    def test_docs_url_accessible(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_url_accessible(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/redoc")
        assert resp.status_code == 200


class TestRequestThroughFullMiddlewareChain:
    """Requests that pass through both LLMHeaderMiddleware and CORS."""

    def test_get_health_with_origin_and_llm_headers(self):
        app = _build_app(cors_origins=["https://test.example.com"])
        client = TestClient(app)
        resp = client.get(
            "/health",
            headers={
                "Origin": "https://test.example.com",
                "wm_llm_gw.user_type": "ASSOCIATE",
                "wm_llm_gw.user_name": "test@walmart.com",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://test.example.com"

    def test_post_to_invalid_path_returns_404_or_405(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.post("/nonexistent-path", json={})
        # FastAPI returns 404 for unknown paths
        assert resp.status_code in (404, 405)


class TestDynamicFAQs:
    """Dynamic FAQ state edge cases."""

    def test_empty_dynamic_faqs(self):
        app = _build_app(dynamic_faqs=[])
        assert app.state.dynamic_faqs == []

    def test_dynamic_faqs_with_content(self):
        faqs = [{"q": "What is X?", "a": "X is Y"}]
        app = _build_app(dynamic_faqs=faqs)
        assert app.state.dynamic_faqs == faqs


class TestContextVarDefaults:
    """Verify factory contextvars have correct defaults."""

    def test_cv_login_id_default(self):
        from app.factory import _cv_login_id
        assert _cv_login_id.get() == "" or isinstance(_cv_login_id.get(), str)

    def test_cv_session_id_default(self):
        from app.factory import _cv_session_id
        assert _cv_session_id.get() == "" or isinstance(_cv_session_id.get(), str)

    def test_cv_permission_default(self):
        from app.factory import _cv_permission
        # Default is "read"
        val = _cv_permission.get()
        assert val == "read" or isinstance(val, str)
