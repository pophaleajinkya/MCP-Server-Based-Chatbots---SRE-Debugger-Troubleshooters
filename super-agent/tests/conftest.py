"""
Shared fixtures for the entire test suite.

Provides reusable mocks and configured test objects for:
  - Settings (with safe defaults via monkeypatched env vars)
  - A mocked ADK Runner (simulates run_agent behaviour)
  - FastAPI TestClient with mocked app state (no lifespan)
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Stub out heavy Google ADK imports when the real package is not installed.
# When google.adk IS present (e.g. inside the project .venv) we must NOT
# touch sys.modules — doing so corrupts the real package for every other
# test collected in the same pytest session.
# ---------------------------------------------------------------------------

def _ensure_stub(dotted_name: str):
    """Create an empty stub module (and all parent packages) if absent."""
    parts = dotted_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
            if depth > 1:
                parent_name = ".".join(parts[:depth - 1])
                setattr(sys.modules[parent_name], parts[depth - 1], mod)


try:
    import google.adk  # noqa: F401  – real package present, nothing to do
    import google.genai  # noqa: F401
except ImportError:
    # Provide lightweight stubs so agent/__init__.py and agent/agent.py
    # can be imported without the full Google ADK installation.
    for _stub in (
        "google",
        "google.adk",
        "google.adk.agents",
        "google.adk.agents.callback_context",
        "google.adk.agents.invocation_context",
        "google.adk.agents.readonly_context",
        "google.adk.a2a",
        "google.adk.a2a.executor",
        "google.adk.a2a.executor.a2a_agent_executor",
        "google.adk.a2a.executor.config",
        "google.adk.artifacts",
        "google.adk.code_executors",
        "google.adk.code_executors.code_execution_utils",
        "google.adk.events",
        "google.adk.events.event",
        "google.adk.models",
        "google.adk.models.lite_llm",
        "google.adk.runners",
        "google.adk.sessions",
        "google.adk.sessions.base_session_service",
        "google.adk.sessions.session",
        "google.adk.sessions.state",
        "google.adk.skills",
        "google.adk.skills._utils",
        "google.adk.tools",
        "google.adk.tools.base_tool",
        "google.adk.tools.mcp_tool",
        "google.adk.tools.mcp_tool.mcp_toolset",
        "google.adk.tools.skill_toolset",
        "google.adk.tools.tool_context",
    ):
        _ensure_stub(_stub)

    # Names consumed by agent/__init__.py and agent/agent.py
    sys.modules["google.adk.agents"].Agent = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.agents.callback_context"].CallbackContext = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.agents.invocation_context"].InvocationContext = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.agents.readonly_context"].ReadonlyContext = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.a2a.executor.a2a_agent_executor"].A2aAgentExecutor = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.a2a.executor.a2a_agent_executor"].A2aAgentExecutorConfig = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.a2a.executor.config"].ExecuteInterceptor = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.a2a.executor.config"].ExecutorContext = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.artifacts"].InMemoryArtifactService = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.code_executors"].UnsafeLocalCodeExecutor = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.code_executors.code_execution_utils"].CodeExecutionInput = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.code_executors.code_execution_utils"].CodeExecutionResult = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.events.event"].Event = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.runners"].Runner = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.sessions.base_session_service"].BaseSessionService = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.sessions.base_session_service"].GetSessionConfig = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.sessions.base_session_service"].ListSessionsConfig = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.sessions.base_session_service"].ListSessionsResponse = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.sessions.session"].Session = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.sessions.state"].State = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].MCPToolset = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].SseConnectionParams = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].StreamableHTTPConnectionParams = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.skills._utils"]._load_skill_from_dir = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.tools.base_tool"].BaseTool = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.tools.skill_toolset"].SkillToolset = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.tools.tool_context"].ToolContext = MagicMock  # type: ignore[attr-defined]

    # a2ui stubs (used by agent/a2ui.py)
    for _stub in (
        "a2ui",
        "a2ui.basic_catalog",
        "a2ui.basic_catalog.provider",
        "a2ui.core",
        "a2ui.core.parser",
        "a2ui.core.parser.parser",
        "a2ui.core.parser.response_part",
        "a2ui.core.schema",
        "a2ui.core.schema.constants",
        "a2ui.core.schema.manager",
    ):
        _ensure_stub(_stub)
    sys.modules["a2ui.basic_catalog.provider"].BasicCatalog = MagicMock  # type: ignore[attr-defined]
    sys.modules["a2ui.core.parser.parser"].has_a2ui_parts = MagicMock  # type: ignore[attr-defined]
    sys.modules["a2ui.core.parser.parser"].parse_response = MagicMock  # type: ignore[attr-defined]
    sys.modules["a2ui.core.parser.response_part"].ResponsePart = MagicMock  # type: ignore[attr-defined]
    sys.modules["a2ui.core.schema.constants"].VERSION_0_9 = "0.9"  # type: ignore[attr-defined]
    sys.modules["a2ui.core.schema.manager"].A2uiSchemaManager = MagicMock  # type: ignore[attr-defined]

    # google.genai stubs (used by session_hooks.py, runner.py)
    _ensure_stub("google.genai")
    _ensure_stub("google.genai.types")
    sys.modules["google.genai.types"].Content = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.genai.types"].Part = MagicMock  # type: ignore[attr-defined]

    # Names consumed by agent/agent.py — LiteLLMClient must be a real class
    # so _HeaderInjectingClient can subclass it.
    class _StubLiteLLMClient:  # noqa: N801
        """Minimal stand-in for google.adk.models.lite_llm.LiteLLMClient."""

    sys.modules["google.adk.models.lite_llm"].LiteLlm = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.adk.models.lite_llm"].LiteLLMClient = _StubLiteLLMClient  # type: ignore[attr-defined]

# Stub litellm if not installed (used by agent/agent.py)
try:
    import litellm  # noqa: F401
except ImportError:
    _ensure_stub("litellm")

# Stub mcp client if not installed (used by agent/agent.py)
try:
    import mcp  # noqa: F401
except ImportError:
    for _stub in (
        "mcp",
        "mcp.client",
        "mcp.client.sse",
        "mcp.client.session",
        "mcp.client.streamable_http",
        "mcp.types",
    ):
        _ensure_stub(_stub)
    sys.modules["mcp.client.sse"].sse_client = MagicMock  # type: ignore[attr-defined]
    sys.modules["mcp.client.session"].ClientSession = MagicMock  # type: ignore[attr-defined]
    sys.modules["mcp.client.streamable_http"].streamablehttp_client = MagicMock  # type: ignore[attr-defined]


# ── Environment / Settings fixtures ──────────────────────────────────────────

@pytest.fixture
def env_vars(monkeypatch):
    """Set all required environment variables for Settings."""
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


@pytest.fixture
def settings(env_vars):
    """Return a fresh Settings instance (bypasses lru_cache)."""
    from app.config import Settings
    return Settings()


@pytest.fixture
def claude_settings(env_vars, monkeypatch):
    """Return Settings configured for Claude as primary LLM."""
    monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
    from app.config import Settings
    return Settings()


# ── Runner / Agent mock fixtures ──────────────────────────────────────────────

def make_mock_runner(answer: str = "Test response from agent"):
    """Build a mock ADK Runner that yields a single final-response event."""
    mock_part = MagicMock()
    mock_part.text = answer

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content = mock_content

    async def _fake_run_async(**kwargs):
        yield mock_event

    mock_runner = MagicMock()
    mock_runner.run_async = _fake_run_async
    mock_runner.session_service = MagicMock()
    mock_runner.session_service.get_session = AsyncMock(return_value=None)
    mock_runner.session_service.create_session = AsyncMock()
    # Patch __aenter__ and __aexit__ for context manager compatibility
    mock_runner.__aenter__ = AsyncMock(return_value=mock_runner)
    mock_runner.__aexit__ = AsyncMock(return_value=None)
    return mock_runner


@pytest.fixture
def mock_runner():
    """Return a mock ADK Runner that produces a simple final response."""
    return make_mock_runner("Test response from agent")


# ── FastAPI app fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def app(mock_runner, env_vars):
    """Return a FastAPI app with mocked state (no lifespan)."""
    from app.routers import health, query
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    test_app = FastAPI()
    test_app.add_exception_handler(LLMError, llm_error_handler)
    test_app.add_exception_handler(AgentError, agent_error_handler)
    test_app.include_router(health.router)
    test_app.include_router(query.router)
    # Note: A2A endpoint is mounted via ADK's A2AStarletteApplication
    # in factory.py lifespan — not included in test fixture.

    test_app.state.runner = mock_runner
    test_app.state.tasks = {}
    test_app.state.mcp_servers = [{"name": "test-mcp", "url": "http://localhost:8999/mcp"}]
    test_app.state.mcp_tools = ["check_health", "get_metrics"]

    return test_app


@pytest.fixture
def client(app):
    """Return a synchronous TestClient for the FastAPI app.

    Includes a default ``loginId`` header so that existing tests satisfy
    the user-identity requirement on POST /query and POST /query_api without
    having to pass ``user_id`` in every request body.
    """
    return TestClient(app, headers={"loginId": "test-user@walmart.com"})
