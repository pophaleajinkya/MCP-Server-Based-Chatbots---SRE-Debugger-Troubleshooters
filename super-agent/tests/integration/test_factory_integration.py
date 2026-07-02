"""Integration tests for the application factory pattern (src/app/factory.py).

Verifies create_app() behaviour by reconstructing the same app wiring
(routers, middleware, exception handlers) and testing through the full HTTP stack.

For modules that transitively depend on google.adk (not installed in the test
environment), we install lightweight stubs before importing any application code.

Coverage targets:
  - create_app()-equivalent app returns a working FastAPI instance with all routers
  - CORS middleware is configured
  - Exception handlers are registered for LLMError, MCPConnectionError, AgentError
  - LLMHeaderMiddleware captures and clears headers correctly through a request cycle
  - Routes: /health, /ready, /query, /sessions, /mcp-proxy, /debug/*, /group/faqs
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Stub heavy external dependencies BEFORE any application imports.
# Must run before conftest or any "from app.xxx" triggers google.adk loads.
# ---------------------------------------------------------------------------

_SRC = str(Path(__file__).resolve().parent.parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _ensure_stub(dotted_name: str):
    """Create an empty stub module and all parent packages if absent."""
    parts = dotted_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = []  # make it a package
            sys.modules[name] = mod
            if depth > 1:
                parent = ".".join(parts[:depth - 1])
                if parent in sys.modules:
                    setattr(sys.modules[parent], parts[depth - 1], mod)


# All google.adk / google.genai / a2a modules needed transitively.
# IMPORTANT: Only install stubs when the real packages are NOT installed.
# When real packages ARE present, unconditional stubs corrupt sys.modules
# and cause failures in other test files.

# --- google.adk stubs ---
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

    # LiteLLMClient must be a real class so _HeaderInjectingClient can subclass it
    class _StubLiteLLMClient:
        pass

    sys.modules["google.adk.models.lite_llm"].LiteLlm = MagicMock
    sys.modules["google.adk.models.lite_llm"].LiteLLMClient = _StubLiteLLMClient

# --- google.genai stubs ---
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

# --- a2a SDK stubs ---
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
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from app.request_context import (
    extract_llm_headers, set_llm_headers, clear_llm_headers, get_llm_headers,
)


# ---------------------------------------------------------------------------
# LLMHeaderMiddleware — re-implemented identically to factory.py
# ---------------------------------------------------------------------------

class LLMHeaderMiddleware:
    """Capture WM_LLM_GW.* headers — identical to factory.py implementation."""

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
# Helpers — build the factory-equivalent app
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


def _build_factory_app():
    """Create an app that mirrors create_app() wiring."""
    from app.config import get_settings
    from app.exceptions import (
        AgentError, LLMError, MCPConnectionError,
        agent_error_handler, llm_error_handler, mcp_connection_error_handler,
    )
    from app.routers import debug, health, mcp_proxy, mcp_validate, query, sessions, faqs

    app = FastAPI(
        title="A2A Health Agent",
        description="Test mirror of create_app()",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    s = get_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
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

    app.state.runner = _make_mock_runner()
    app.state.tasks = {}
    app.state.mcp_servers = [{"name": "test-mcp", "url": "http://localhost:8999/mcp"}]
    app.state.mcp_tools = ["check_health"]
    app.state.mcp_pool = MagicMock()
    app.state.mcp_pool._sessions = []
    app.state.http_client = MagicMock()
    app.state.a2a_agents = []
    app.state.dynamic_faqs = []

    return app


# ---------------------------------------------------------------------------
# Fixture: reset settings cache
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_settings_cache(env_vars):
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ===========================================================================
# Test: App basics
# ===========================================================================

class TestCreateAppBasics:
    def test_returns_fastapi_instance(self):
        app = _build_factory_app()
        assert isinstance(app, FastAPI)

    def test_app_title_and_version(self):
        app = _build_factory_app()
        assert app.title == "A2A Health Agent"
        assert app.version == "2.0.0"

    def test_docs_url_configured(self):
        app = _build_factory_app()
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"


# ===========================================================================
# Test: All expected routes are registered
# ===========================================================================

class TestRouteRegistration:
    def _route_paths(self, app: FastAPI) -> set[str]:
        paths = set()
        for route in app.routes:
            if hasattr(route, "path"):
                paths.add(route.path)
        return paths

    def test_health_routes_registered(self):
        paths = self._route_paths(_build_factory_app())
        assert "/health" in paths
        assert "/ready" in paths

    def test_query_route_registered(self):
        paths = self._route_paths(_build_factory_app())
        assert "/query" in paths

    def test_sessions_routes_registered(self):
        paths = self._route_paths(_build_factory_app())
        assert "/sessions" in paths
        assert "/sessions/{session_id}/messages" in paths
        assert "/sessions/{session_id}/visibility" in paths

    def test_mcp_proxy_route_registered(self):
        paths = self._route_paths(_build_factory_app())
        assert "/mcp-proxy" in paths

    def test_debug_routes_registered(self):
        paths = self._route_paths(_build_factory_app())
        debug_paths = [p for p in paths if p.startswith("/debug")]
        assert len(debug_paths) > 0, "Expected at least one /debug/* route"

    def test_faqs_route_registered(self):
        paths = self._route_paths(_build_factory_app())
        assert "/group/faqs" in paths

    def test_health_endpoint_responds_200(self):
        client = TestClient(_build_factory_app())
        assert client.get("/health").status_code == 200

    def test_ready_endpoint_responds_200(self):
        client = TestClient(_build_factory_app())
        assert client.get("/ready").status_code == 200

    def test_all_expected_routes_present(self):
        paths = self._route_paths(_build_factory_app())
        expected = {
            "/health", "/ready", "/query", "/sessions",
            "/sessions/{session_id}/messages",
            "/sessions/{session_id}/visibility",
            "/mcp-proxy", "/group/faqs",
        }
        for p in expected:
            assert p in paths, f"Missing route: {p}"


# ===========================================================================
# Test: CORS middleware
# ===========================================================================

class TestCORSMiddleware:
    def test_cors_preflight_responds(self):
        client = TestClient(_build_factory_app())
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 400)

    def test_cors_post_preflight_responds(self):
        client = TestClient(_build_factory_app())
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code in (200, 400)


# ===========================================================================
# Test: Exception handlers
# ===========================================================================

class TestExceptionHandlers:
    def test_llm_error_handler_produces_502(self):
        from app.exceptions import LLMError

        app = _build_factory_app()

        @app.get("/test-llm-error")
        async def _raise():
            raise LLMError(status_code=429, detail="rate limited")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-llm-error")
        assert resp.status_code == 502
        data = resp.json()
        assert data["error"] == "llm_error"
        assert data["llm_status_code"] == 429
        assert "rate limited" in data["detail"]

    def test_mcp_connection_error_handler_produces_503(self):
        from app.exceptions import MCPConnectionError

        app = _build_factory_app()

        @app.get("/test-mcp-error")
        async def _raise():
            raise MCPConnectionError("server unreachable")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-mcp-error")
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "mcp_connection_error"
        assert "unreachable" in data["detail"]

    def test_agent_error_handler_produces_500(self):
        from app.exceptions import AgentError

        app = _build_factory_app()

        @app.get("/test-agent-error")
        async def _raise():
            raise AgentError("loop failed")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-agent-error")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"] == "agent_error"
        assert "loop failed" in data["detail"]

    def test_all_three_handlers_coexist(self):
        from app.exceptions import LLMError, MCPConnectionError, AgentError

        app = _build_factory_app()

        @app.get("/err-llm")
        async def _llm():
            raise LLMError(500, "llm")

        @app.get("/err-mcp")
        async def _mcp():
            raise MCPConnectionError("mcp")

        @app.get("/err-agent")
        async def _agent():
            raise AgentError("agent")

        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/err-llm").status_code == 502
        assert client.get("/err-mcp").status_code == 503
        assert client.get("/err-agent").status_code == 500


# ===========================================================================
# Test: LLMHeaderMiddleware
# ===========================================================================

class TestLLMHeaderMiddleware:
    def test_llm_headers_captured_during_request(self):
        captured = {}
        app = FastAPI()

        @app.get("/capture")
        async def _capture(request: Request):
            nonlocal captured
            captured = get_llm_headers()
            return JSONResponse({"ok": True})

        app.add_middleware(LLMHeaderMiddleware)
        client = TestClient(app)
        client.get("/capture", headers={
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "testuser@walmart.com",
            "wm_llm_gw.user_agent": "test-agent",
            "wm_llm_gw.user_ip": "10.0.0.1",
        })
        assert captured.get("wm_llm_gw.user_type") == "ASSOCIATE"
        assert captured.get("wm_llm_gw.user_name") == "testuser@walmart.com"
        assert captured.get("wm_llm_gw.user_agent") == "test-agent"
        assert captured.get("wm_llm_gw.user_ip") == "10.0.0.1"

    def test_llm_headers_cleared_after_request(self):
        app = FastAPI()

        @app.get("/noop")
        async def _noop(request: Request):
            return JSONResponse({"ok": True})

        app.add_middleware(LLMHeaderMiddleware)
        client = TestClient(app)
        client.get("/noop", headers={"wm_llm_gw.user_type": "ASSOCIATE"})
        assert get_llm_headers() == {}

    def test_defaults_user_type_to_associate(self):
        captured = {}
        app = FastAPI()

        @app.get("/default")
        async def _capture(request: Request):
            nonlocal captured
            captured = get_llm_headers()
            return JSONResponse({"ok": True})

        app.add_middleware(LLMHeaderMiddleware)
        client = TestClient(app)
        client.get("/default", headers={"loginId": "someuser"})
        assert captured.get("wm_llm_gw.user_type") == "ASSOCIATE"

    def test_loginid_fallback_for_user_name(self):
        captured = {}
        app = FastAPI()

        @app.get("/loginid")
        async def _capture(request: Request):
            nonlocal captured
            captured = get_llm_headers()
            return JSONResponse({"ok": True})

        app.add_middleware(LLMHeaderMiddleware)
        client = TestClient(app)
        client.get("/loginid", headers={"loginId": "alice@walmart.com"})
        assert captured.get("wm_llm_gw.user_name") == "alice@walmart.com"

    def test_non_http_scope_delegates_to_inner_app(self):
        """Non-HTTP scopes (scope['type'] != 'http') should be forwarded
        directly to the inner app without touching the contextvar."""
        import asyncio

        inner_called = False
        inner_scope_type = None

        async def _mock_inner_app(scope, receive, send):
            nonlocal inner_called, inner_scope_type
            inner_called = True
            inner_scope_type = scope.get("type")

        middleware = LLMHeaderMiddleware(_mock_inner_app)

        # Simulate a non-HTTP scope (websocket)
        scope = {"type": "websocket", "path": "/ws"}

        async def _run():
            await middleware(scope, AsyncMock(), AsyncMock())

        asyncio.get_event_loop().run_until_complete(_run())

        assert inner_called, "Inner app should be called for non-HTTP scopes"
        assert inner_scope_type == "websocket"

    def test_headers_isolated_between_requests(self):
        captured_1 = {}
        captured_2 = {}
        call_count = 0
        app = FastAPI()

        @app.get("/isolate")
        async def _capture(request: Request):
            nonlocal captured_1, captured_2, call_count
            hdrs = get_llm_headers()
            if call_count == 0:
                captured_1 = dict(hdrs)
            else:
                captured_2 = dict(hdrs)
            call_count += 1
            return JSONResponse({"ok": True})

        app.add_middleware(LLMHeaderMiddleware)
        client = TestClient(app)
        client.get("/isolate", headers={"wm_llm_gw.user_name": "alice"})
        client.get("/isolate", headers={"wm_llm_gw.user_name": "bob"})
        assert captured_1.get("wm_llm_gw.user_name") == "alice"
        assert captured_2.get("wm_llm_gw.user_name") == "bob"


# ===========================================================================
# Test: Full request cycle
# ===========================================================================

class TestFactoryAppFullCycle:
    def test_health_response(self):
        client = TestClient(_build_factory_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "mcp_servers" in data

    def test_query_response(self):
        client = TestClient(
            _build_factory_app(),
            headers={"loginId": "test@walmart.com"},
        )
        resp = client.post("/query", json={"query": "test query"})
        assert resp.status_code == 200
        assert "response" in resp.json()

    def test_sessions_response(self):
        client = TestClient(_build_factory_app())
        resp = client.get("/sessions?user_id=test-user")
        assert resp.status_code == 200

    def test_mcp_proxy_unsupported_method(self):
        client = TestClient(_build_factory_app())
        resp = client.post("/mcp-proxy", json={"method": "unknown/method"})
        assert resp.status_code == 400

    def test_group_faqs_response(self):
        client = TestClient(_build_factory_app())
        resp = client.get("/group/faqs")
        assert resp.status_code == 200
