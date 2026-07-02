"""Unit tests for app.factory module.

Covers:
  - _log_mcp_summary
  - _validate_tool_schemas
  - _validate_guide_adk_safety
  - _a2a_friendly_message
  - _MCPErrorInterceptQueue
  - LLMHeaderMiddleware
  - create_app
"""

import sys
import types
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio  # noqa: F401 — ensures pytest-asyncio is available


# ---------------------------------------------------------------------------
# Stub out heavy A2A / ADK imports that factory.py requires at module level.
# IMPORTANT: Only install stubs when the real packages are NOT installed.
# When real packages ARE present (e.g. project .venv), unconditional stubs
# corrupt sys.modules and cause failures in other test files.
# ---------------------------------------------------------------------------

def _ensure_stub(dotted_name: str):
    """Create an empty stub module (and all parents) if absent."""
    parts = dotted_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
            if depth > 1:
                parent = ".".join(parts[:depth - 1])
                setattr(sys.modules[parent], parts[depth - 1], mod)


# google.adk stubs — only when the real package is not installed
try:
    from google.adk.runners import Runner  # noqa: F401
    from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor  # noqa: F401
    _HAS_ADK = True
except (ImportError, ModuleNotFoundError):
    _HAS_ADK = False

if not _HAS_ADK:
    for _stub in (
        "google.adk.runners",
        "google.adk.a2a",
        "google.adk.a2a.executor",
        "google.adk.a2a.executor.a2a_agent_executor",
        "google.adk.a2a.executor.config",
        "google.adk.artifacts",
        "google.adk.skills",
        "google.adk.skills._utils",
        "google.adk.tools.skill_toolset",
    ):
        _ensure_stub(_stub)

    sys.modules["google.adk.runners"].Runner = MagicMock
    sys.modules["google.adk.a2a.executor.a2a_agent_executor"].A2aAgentExecutor = MagicMock
    sys.modules["google.adk.a2a.executor.a2a_agent_executor"].A2aAgentExecutorConfig = MagicMock
    sys.modules["google.adk.a2a.executor.config"].ExecuteInterceptor = MagicMock
    sys.modules["google.adk.a2a.executor.config"].ExecutorContext = MagicMock
    sys.modules["google.adk.artifacts"].InMemoryArtifactService = MagicMock
    sys.modules["google.adk.skills._utils"]._load_skill_from_dir = MagicMock
    sys.modules["google.adk.tools.skill_toolset"].SkillToolset = MagicMock

# a2a SDK stubs — only when the real package is not installed
try:
    from a2a.types import TaskState as _RealTaskState  # noqa: F401
    _HAS_A2A = True
except (ImportError, ModuleNotFoundError):
    _HAS_A2A = False

if not _HAS_A2A:
    for _stub in (
        "a2a",
        "a2a.server",
        "a2a.server.apps",
        "a2a.server.apps.jsonrpc",
        "a2a.server.apps.jsonrpc.jsonrpc_app",
        "a2a.server.context",
        "a2a.server.request_handlers",
        "a2a.server.tasks",
        "a2a.server.agent_execution",
        "a2a.server.agent_execution.context",
        "a2a.types",
    ):
        _ensure_stub(_stub)

    sys.modules["a2a.server.apps"].A2AStarletteApplication = MagicMock
    sys.modules["a2a.server.apps.jsonrpc.jsonrpc_app"].CallContextBuilder = type("CallContextBuilder", (), {})
    sys.modules["a2a.server.context"].ServerCallContext = MagicMock
    sys.modules["a2a.server.request_handlers"].DefaultRequestHandler = MagicMock
    sys.modules["a2a.server.tasks"].InMemoryTaskStore = MagicMock
    sys.modules["a2a.server.tasks"].InMemoryPushNotificationConfigStore = MagicMock
    sys.modules["a2a.server.agent_execution.context"].RequestContext = MagicMock
    sys.modules["a2a.types"].AgentCard = MagicMock

    # TaskState needs a real .failed attribute — factory.py compares event.status.state == TaskState.failed
    _TaskState = type("TaskState", (), {"failed": "failed", "submitted": "submitted", "working": "working"})
    sys.modules["a2a.types"].TaskState = _TaskState
    # TaskStatusUpdateEvent must be a real class so isinstance() checks work
    _TaskStatusUpdateEvent = type("TaskStatusUpdateEvent", (), {})
    sys.modules["a2a.types"].TaskStatusUpdateEvent = _TaskStatusUpdateEvent
    sys.modules["a2a.types"].TaskArtifactUpdateEvent = type("TaskArtifactUpdateEvent", (), {})

# litellm stubs (needed by agent.agent) — only when not installed
try:
    import litellm as _real_litellm  # noqa: F401
    _HAS_LITELLM = True
except ImportError:
    _HAS_LITELLM = False

if not _HAS_LITELLM:
    _ensure_stub("litellm")
    sys.modules["litellm"].ssl_verify = False
    sys.modules["litellm"].ContextWindowExceededError = type("ContextWindowExceededError", (Exception,), {})
    sys.modules["litellm"].BadRequestError = type("BadRequestError", (Exception,), {})


# ---------------------------------------------------------------------------
# Helpers — lightweight fakes for MCP pool / session objects
# ---------------------------------------------------------------------------

def _make_session(name: str, url: str, tools: list[dict] | None = None,
                  guide: str = "", sid: str = "sid-1"):
    s = MagicMock()
    s._name = name
    s._url = url
    s.tools = tools or []
    s.guide = guide
    s.sid = sid
    return s


def _make_pool(sessions: list, failed: list[dict] | None = None):
    pool = MagicMock()
    pool._sessions = sessions
    pool.failed_servers = failed or []
    return pool


# ===========================================================================
# 1. _log_mcp_summary
# ===========================================================================

class TestLogMcpSummary:

    def test_logs_connected_servers_tools_and_resources(self, caplog):
        from app.factory import _log_mcp_summary

        sess = _make_session(
            "health-mcp", "http://localhost:8999/mcp",
            tools=[{"name": "check_health", "description": "Run health check"}],
            guide="Some guide text with 100 chars",
        )
        pool = _make_pool([sess])

        with caplog.at_level(logging.INFO, logger="app.factory"):
            _log_mcp_summary(pool)

        combined = "\n".join(caplog.messages)
        assert "Total MCP servers connected: 1" in combined
        assert "health-mcp" in combined
        assert "check_health" in combined
        assert "wcnp://agent-guide" in combined

    def test_logs_failed_servers(self, caplog):
        from app.factory import _log_mcp_summary

        failed_sess = _make_session("broken-mcp", "http://broken:9000/mcp")
        pool = _make_pool(
            [failed_sess],
            failed=[{"name": "broken-mcp", "url": "http://broken:9000/mcp",
                      "error": "Connection refused"}],
        )

        with caplog.at_level(logging.INFO, logger="app.factory"):
            _log_mcp_summary(pool)

        combined = "\n".join(caplog.messages)
        assert "Failed MCP servers (1):" in combined
        assert "broken-mcp" in combined
        assert "Connection refused" in combined

    def test_no_resources_label(self, caplog):
        from app.factory import _log_mcp_summary

        sess = _make_session("plain", "http://localhost/mcp", guide="")
        pool = _make_pool([sess])

        with caplog.at_level(logging.INFO, logger="app.factory"):
            _log_mcp_summary(pool)

        combined = "\n".join(caplog.messages)
        assert "Resources: (none)" in combined


# ===========================================================================
# 2. _validate_tool_schemas
# ===========================================================================

class TestValidateToolSchemas:

    def test_valid_tool_passes_silently(self, caplog):
        from app.factory import _validate_tool_schemas

        tools = [
            {"name": "good_tool", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}
        ]
        with caplog.at_level(logging.WARNING, logger="app.factory"):
            _validate_tool_schemas(tools)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 0

    def test_non_dict_input_schema_logs_error(self, caplog):
        from app.factory import _validate_tool_schemas

        tools = [{"name": "bad_tool", "input_schema": "not-a-dict"}]
        with caplog.at_level(logging.ERROR, logger="app.factory"):
            _validate_tool_schemas(tools)

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) >= 1
        assert "not-a-dict" in errors[0].message or "str" in errors[0].message

    def test_definitions_key_logs_warning(self, caplog):
        from app.factory import _validate_tool_schemas

        tools = [{"name": "legacy_tool", "input_schema": {
            "type": "object",
            "definitions": {"Foo": {"type": "string"}},
            "properties": {},
        }}]
        with caplog.at_level(logging.WARNING, logger="app.factory"):
            _validate_tool_schemas(tools)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("legacy keys" in w.message for w in warnings)

    def test_non_object_type_logs_warning(self, caplog):
        from app.factory import _validate_tool_schemas

        tools = [{"name": "array_tool", "input_schema": {"type": "array", "items": {"type": "string"}}}]
        with caplog.at_level(logging.WARNING, logger="app.factory"):
            _validate_tool_schemas(tools)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("type=" in w.message and "array" in w.message for w in warnings)

    @patch("app.factory.find_suspicious_fields", return_value=["input_schema.default='foo'"])
    def test_suspicious_fields_logs_warning(self, mock_find, caplog):
        from app.factory import _validate_tool_schemas

        tools = [{"name": "sus_tool", "input_schema": {
            "type": "object", "properties": {"x": {"type": "string", "default": "foo"}}
        }}]
        with caplog.at_level(logging.WARNING, logger="app.factory"):
            _validate_tool_schemas(tools)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("suspicious" in w.message for w in warnings)

    def test_non_serializable_input_schema_logs_error(self, caplog):
        from app.factory import _validate_tool_schemas

        # set() is not JSON-serializable
        tools = [{"name": "bad_json", "input_schema": {"type": "object", "properties": set()}}]
        with caplog.at_level(logging.ERROR, logger="app.factory"):
            _validate_tool_schemas(tools)

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) >= 1


# ===========================================================================
# 3. _validate_guide_adk_safety
# ===========================================================================

class TestValidateGuideAdkSafety:

    def test_clean_guide_passes(self):
        from app.factory import _validate_guide_adk_safety

        sess = _make_session("safe", "http://safe/mcp",
                             guide="Use <namespace> and {optional?} params.")
        pool = _make_pool([sess])

        # Should not raise
        _validate_guide_adk_safety(pool)

    def test_bare_identifier_raises_runtime_error(self):
        from app.factory import _validate_guide_adk_safety

        sess = _make_session("unsafe", "http://unsafe/mcp",
                             guide="Check {namespace} health now.")
        pool = _make_pool([sess])

        with pytest.raises(RuntimeError, match="ADK template conflict"):
            _validate_guide_adk_safety(pool)

    def test_safe_optional_identifier_passes(self):
        from app.factory import _validate_guide_adk_safety

        sess = _make_session("ok", "http://ok/mcp",
                             guide="Use {namespace?} or <namespace> safely.")
        pool = _make_pool([sess])

        _validate_guide_adk_safety(pool)

    def test_no_guide_passes(self):
        from app.factory import _validate_guide_adk_safety

        sess = _make_session("empty", "http://empty/mcp", guide="")
        pool = _make_pool([sess])

        _validate_guide_adk_safety(pool)


# ===========================================================================
# 4. _a2a_friendly_message
# ===========================================================================

class TestA2aFriendlyMessage:

    def test_returns_specific_server_name_when_url_in_registry(self):
        from app.factory import _a2a_friendly_message
        import app.factory as factory_mod

        registry = factory_mod._a2a_server_registry
        original = dict(registry)
        try:
            registry.clear()
            registry["http://health-mcp:8999/mcp"] = "health-mcp"
            registry["http://deploy-mcp:9000/mcp"] = "deploy-mcp"

            msg = _a2a_friendly_message(
                "Failed to connect to MCP server at http://health-mcp:8999/mcp"
            )
            assert "health-mcp" in msg
            assert "temporarily unavailable" in msg
        finally:
            registry.clear()
            registry.update(original)

    def test_falls_back_to_all_server_names(self):
        from app.factory import _a2a_friendly_message
        import app.factory as factory_mod

        registry = factory_mod._a2a_server_registry
        original = dict(registry)
        try:
            registry.clear()
            registry["http://health-mcp:8999/mcp"] = "health-mcp"
            registry["http://deploy-mcp:9000/mcp"] = "deploy-mcp"

            msg = _a2a_friendly_message("Some unknown error with no matching URL")
            assert "health-mcp" in msg
            assert "deploy-mcp" in msg
            assert "temporarily unavailable" in msg
        finally:
            registry.clear()
            registry.update(original)

    def test_falls_back_to_generic_when_no_servers(self):
        from app.factory import _a2a_friendly_message
        import app.factory as factory_mod

        registry = factory_mod._a2a_server_registry
        original = dict(registry)
        try:
            registry.clear()

            msg = _a2a_friendly_message("Something broke")
            assert "temporarily unavailable" in msg
            assert "backend services" in msg
        finally:
            registry.clear()
            registry.update(original)


# ===========================================================================
# 5. _MCPErrorInterceptQueue
# ===========================================================================

def _ensure_a2a_types_stubs():
    """Re-apply a2a.types stubs — other test files may have overwritten them.

    No-op when the real a2a package is installed.
    """
    if _HAS_A2A:
        return
    _ensure_stub("a2a.types")
    mod = sys.modules["a2a.types"]
    if not isinstance(getattr(mod, "TaskStatusUpdateEvent", None), type):
        mod.TaskStatusUpdateEvent = type("TaskStatusUpdateEvent", (), {})
    if not hasattr(getattr(mod, "TaskState", None), "failed"):
        mod.TaskState = type("TaskState", (), {"failed": "failed", "submitted": "submitted"})


class TestMCPErrorInterceptQueue:

    @pytest.mark.asyncio
    async def test_non_failed_events_pass_through(self):
        from app.factory import _MCPErrorInterceptQueue

        inner = AsyncMock()
        queue = _MCPErrorInterceptQueue(inner)

        # Plain object — not a TaskStatusUpdateEvent instance
        event = object()

        await queue.enqueue_event(event)
        inner.enqueue_event.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_failed_mcp_event_gets_rewritten(self):
        _ensure_a2a_types_stubs()
        from app.factory import _MCPErrorInterceptQueue, _a2a_friendly_message
        import app.factory as factory_mod

        # Temporarily populate server registry for friendly message
        registry = factory_mod._a2a_server_registry
        original = dict(registry)
        registry.clear()
        registry["http://mcp:8999/mcp"] = "test-server"

        try:
            inner = AsyncMock()
            queue = _MCPErrorInterceptQueue(inner)

            # Build event using the ACTUAL class from the a2a.types module
            # as seen by factory.py at import time.  Use MagicMock(spec=...)
            # so isinstance() passes without needing Pydantic field values.
            a2a_types = sys.modules["a2a.types"]
            TaskStatusUpdateEvent = a2a_types.TaskStatusUpdateEvent
            TaskState = a2a_types.TaskState

            event = MagicMock(spec=TaskStatusUpdateEvent)

            part_root = MagicMock()
            part_root.text = "Failed to connect to MCP server at http://mcp:8999/mcp"
            part = MagicMock()
            part.root = part_root

            status = MagicMock()
            status.state = getattr(TaskState, "failed", "failed")
            message = MagicMock()
            message.parts = [part]
            status.message = message
            event.status = status

            await queue.enqueue_event(event)

            # The text should have been rewritten to a friendly message
            assert "test-server" in part_root.text
            assert "temporarily unavailable" in part_root.text
            inner.enqueue_event.assert_awaited_once()
        finally:
            registry.clear()
            registry.update(original)

    @pytest.mark.asyncio
    async def test_non_mcp_failure_passes_through_unchanged(self):
        _ensure_a2a_types_stubs()
        from app.factory import _MCPErrorInterceptQueue

        a2a_types = sys.modules["a2a.types"]
        TaskStatusUpdateEvent = a2a_types.TaskStatusUpdateEvent
        TaskState = a2a_types.TaskState

        inner = AsyncMock()
        queue = _MCPErrorInterceptQueue(inner)

        event = MagicMock(spec=TaskStatusUpdateEvent)

        part_root = MagicMock()
        part_root.text = "Some generic Python error — not MCP related"
        part = MagicMock()
        part.root = part_root

        status = MagicMock()
        status.state = getattr(TaskState, "failed", "failed")
        message = MagicMock()
        message.parts = [part]
        status.message = message
        event.status = status

        await queue.enqueue_event(event)

        # Text should remain unchanged since it has no MCP signatures
        assert part_root.text == "Some generic Python error — not MCP related"
        inner.enqueue_event.assert_awaited_once_with(event)

    def test_getattr_forwards_to_inner(self):
        from app.factory import _MCPErrorInterceptQueue

        inner = MagicMock()
        inner.some_attribute = "hello"
        queue = _MCPErrorInterceptQueue(inner)

        assert queue.some_attribute == "hello"


# ===========================================================================
# 6. LLMHeaderMiddleware
# ===========================================================================

class TestLLMHeaderMiddleware:

    @pytest.mark.asyncio
    async def test_http_scope_sets_and_clears_headers(self):
        from app.factory import LLMHeaderMiddleware

        captured_headers = {}

        async def fake_app(scope, receive, send):
            from app.request_context import get_llm_headers
            captured_headers.update(get_llm_headers())

        middleware = LLMHeaderMiddleware(fake_app)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/query",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"wm_llm_gw.user_name", b"testuser@walmart.com"),
                (b"wm_llm_gw.user_type", b"ASSOCIATE"),
                (b"content-type", b"application/json"),
            ],
        }

        receive = AsyncMock(return_value={"type": "http.request", "body": b""})
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should have captured the wm_llm_gw headers
        assert "wm_llm_gw.user_name" in captured_headers
        assert captured_headers["wm_llm_gw.user_name"] == "testuser@walmart.com"
        assert captured_headers["wm_llm_gw.user_type"] == "ASSOCIATE"

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        from app.factory import LLMHeaderMiddleware

        app_called = {"value": False}

        async def fake_app(scope, receive, send):
            app_called["value"] = True

        middleware = LLMHeaderMiddleware(fake_app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        assert app_called["value"] is True


# ===========================================================================
# 7. create_app
# ===========================================================================

class TestCreateApp:

    def test_returns_fastapi_instance(self, env_vars):
        from app.factory import create_app
        app = create_app()
        assert isinstance(app, __import__("fastapi").FastAPI)

    def test_has_expected_routers(self, env_vars):
        from app.factory import create_app
        app = create_app()

        paths = {route.path for route in app.routes if hasattr(route, "path")}
        # Check for key routes from included routers
        assert "/health" in paths or "/healthz" in paths or any("/health" in p for p in paths)
        assert any("/query" in p for p in paths) or any("/sessions" in p for p in paths)

    def test_has_cors_middleware(self, env_vars):
        from app.factory import create_app
        app = create_app()

        middleware_classes = [m.cls.__name__ if hasattr(m, "cls") else type(m).__name__
                             for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_has_exception_handlers(self, env_vars):
        from app.factory import create_app
        from app.exceptions import LLMError, MCPConnectionError, AgentError
        app = create_app()

        # FastAPI stores exception handlers in a dict keyed by exception class
        handler_keys = set(app.exception_handlers.keys())
        assert LLMError in handler_keys
        assert MCPConnectionError in handler_keys
        assert AgentError in handler_keys
