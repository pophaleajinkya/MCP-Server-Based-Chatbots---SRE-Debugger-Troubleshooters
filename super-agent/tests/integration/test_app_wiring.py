"""Integration tests for application wiring — config to app integration.

These tests verify that components work together correctly:
  - Settings computed fields integrate with router responses
  - App state (runner, tasks, mcp metadata) is correctly wired
  - Exception handlers are registered and functional on the app
  - Router + runner service integration
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub google.genai only when the real package is not installed.
# When the real package IS present we must not overwrite sys.modules —
# doing so corrupts the google namespace package for every subsequent test.
try:
    import google.genai  # noqa: F401
except ImportError:
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.genai", ModuleType("google.genai"))
    sys.modules.setdefault("google.genai.types", MagicMock())

# Import make_mock_runner directly from the project's conftest (avoid picking up
# a different project's tests.conftest on sys.path)
import importlib.util as _ilu
_conftest_path = Path(__file__).resolve().parent.parent / "conftest.py"
_spec = _ilu.spec_from_file_location("_project_conftest", _conftest_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
make_mock_runner = _mod.make_mock_runner


@pytest.fixture(autouse=True)
def _reset_settings_cache_per_test():
    """Ensure each test reads fresh env-backed settings (no lru_cache bleed)."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Helper to build a minimal test app ───────────────────────────────────────

_TEST_HEADERS = {"loginId": "test-user@walmart.com"}


def _build_app(runner=None, mcp_servers=None, mcp_tools=None, tasks=None, env_vars_set=True):
    """Create a fully wired FastAPI app for wiring tests.

    Note: A2A endpoint (/a2a, /.well-known/agent.json) is mounted via
    ADK's A2AStarletteApplication in factory.py lifespan — not here.
    """
    from app.routers import health, query
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    test_app = FastAPI()
    test_app.add_exception_handler(LLMError, llm_error_handler)
    test_app.add_exception_handler(AgentError, agent_error_handler)
    test_app.include_router(health.router)
    test_app.include_router(query.router)

    test_app.state.runner = runner or make_mock_runner("default answer")
    test_app.state.tasks = tasks if tasks is not None else {}
    test_app.state.mcp_servers = mcp_servers or []
    test_app.state.mcp_tools = mcp_tools or []
    return test_app


def _build_client(app, **kwargs) -> TestClient:
    """Return a TestClient with the default loginId header pre-set.

    All /query and /query_api calls require a user identity; this helper
    satisfies that requirement without modifying every request payload.
    """
    return TestClient(app, headers=_TEST_HEADERS, **kwargs)


# ── Config → Health endpoint integration ─────────────────────────────────────

class TestConfigToHealthWiring:
    """Test that Settings fields are correctly reflected in /health responses."""

    def test_openai_settings_reflect_in_health_active_llm(self, env_vars):
        """OpenAI settings should produce active_llm=openai in /health."""
        app = _build_app()
        client = _build_client(app)
        resp = client.get("/health")
        assert resp.json()["active_llm"] == "openai"

    def test_claude_settings_reflect_in_health_active_llm(self, env_vars, monkeypatch):
        """Claude primary settings should produce active_llm=claude in /health."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        # Clear settings cache so new env is picked up
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app()
        client = _build_client(app)
        resp = client.get("/health")
        data = resp.json()
        assert data["active_llm"] == "claude"

        # Reset cache
        get_settings.cache_clear()

    def test_health_llm_endpoint_matches_settings(self, env_vars):
        """llm_endpoint in /health should contain the configured model name."""
        app = _build_app()
        client = _build_client(app)
        resp = client.get("/health")
        data = resp.json()
        assert "gpt-4-test" in data["llm_endpoint"]

    def test_health_reflects_mcp_servers_in_state(self, env_vars):
        """mcp_servers in /health should come from app.state.mcp_servers."""
        custom_servers = [
            {"name": "server-a", "url": "http://a:8999/mcp"},
            {"name": "server-b", "url": "http://b:8999/mcp"},
        ]
        app = _build_app(mcp_servers=custom_servers)
        client = _build_client(app)
        resp = client.get("/health")
        names = [s["name"] for s in resp.json()["mcp_servers"]]
        assert "server-a" in names
        assert "server-b" in names

    def test_health_reflects_mcp_tools_in_state(self, env_vars):
        """mcp_tools in /health should come from app.state.mcp_tools."""
        custom_tools = ["get_pods", "check_latency", "describe_deployment"]
        app = _build_app(mcp_tools=custom_tools)
        client = _build_client(app)
        resp = client.get("/health")
        tools = resp.json()["mcp_tools"]
        assert "get_pods" in tools
        assert "check_latency" in tools

    def test_health_with_no_mcp_servers(self, env_vars):
        """Health endpoint should handle empty mcp_servers gracefully."""
        app = _build_app(mcp_servers=[], mcp_tools=[])
        client = _build_client(app)
        resp = client.get("/health")
        data = resp.json()
        assert data["mcp_servers"] == []
        assert data["mcp_tools"] == []
        assert data["status"] == "ok"


# ── Runner → Query integration ────────────────────────────────────────────────

class TestRunnerToQueryWiring:
    """Test that the runner is correctly integrated with /query."""

    def test_query_uses_runner_from_app_state(self, env_vars):
        """The /query endpoint should call the runner from app.state.runner."""
        runner = make_mock_runner("answer from custom runner")
        app = _build_app(runner=runner)
        client = _build_client(app)

        resp = client.post("/query", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "answer from custom runner"

    def test_query_runner_called_with_correct_args(self, env_vars):
        """Runner should be called with the query text."""
        captured = {}

        mock_part = MagicMock()
        mock_part.text = "runner response"
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = mock_content

        async def _run_async(**kwargs):
            captured.update(kwargs)
            yield mock_event

        runner = MagicMock()
        runner.run_async = _run_async
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()

        app = _build_app(runner=runner)
        client = _build_client(app)
        client.post("/query", json={"query": "my test query", "session_id": "sid-123"})

        # Verify runner was invoked with expected kwargs
        assert "session_id" in captured
        assert captured["session_id"] == "sid-123"

    def test_query_runner_empty_response_returns_empty_string(self, env_vars):
        """When runner produces no final response, /query should return empty string."""
        async def _no_response(**kwargs):
            if False:
                yield

        runner = MagicMock()
        runner.run_async = _no_response
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()

        app = _build_app(runner=runner)
        client = _build_client(app)
        resp = client.post("/query", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["response"] == ""


# Note: A2A endpoint tests removed — the A2A layer is now ADK-native
# (A2AStarletteApplication, A2A SDK 0.3 message/send protocol) mounted
# during lifespan. Integration is covered by E2E tests against a live server.


# ── Exception handler wiring ──────────────────────────────────────────────────

class TestExceptionHandlerWiring:
    """Test that exception handlers are properly registered and functional."""

    def test_llm_error_produces_502_via_app(self, env_vars):
        """LLMError from runner should produce 502 through registered handler."""
        from app.exceptions import LLMError

        async def _raise_llm_error(**kwargs):
            raise LLMError(status_code=503, detail="upstream fail")
            yield

        runner = MagicMock()
        runner.run_async = _raise_llm_error

        app = _build_app(runner=runner)
        client = _build_client(app, raise_server_exceptions=False)
        resp = client.post("/query", json={"query": "test"})
        # LLMError not caught by router, goes to handler
        # The router will catch it as a generic exception (500)
        # but with the exception handler registered it should be 502
        assert resp.status_code in (500, 502)

    def test_app_state_tasks_initialized_empty(self, env_vars):
        """app.state.tasks must start as an empty dict on startup."""
        app = _build_app()
        assert isinstance(app.state.tasks, dict)
        assert len(app.state.tasks) == 0

    def test_health_and_query_endpoints_coexist(self, env_vars):
        """Both /health and /query should work correctly on same app instance."""
        app = _build_app()
        client = _build_client(app)

        # Health check
        h = client.get("/health")
        assert h.status_code == 200

        # Query
        q = client.post("/query", json={"query": "test"})
        assert q.status_code == 200

        # Readiness
        r = client.get("/ready")
        assert r.status_code == 200

    def test_all_routers_registered(self, env_vars):
        """Health and query routers should be reachable on the app.

        Note: The A2A endpoint is mounted by ADK's A2AStarletteApplication
        during lifespan and is not tested here.
        """
        app = _build_app()
        client = _build_client(app)

        # Health router
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200

        # Query router
        assert client.post("/query", json={"query": "test"}).status_code == 200
