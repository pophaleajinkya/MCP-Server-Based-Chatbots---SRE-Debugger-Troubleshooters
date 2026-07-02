"""End-to-end tests for complete API flows.

These tests simulate real user journeys through the API,
exercising the full HTTP stack with a mocked ADK Runner.

All agent logic is provided by a mock ADK Runner (no real LLM / MCP calls).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Import make_mock_runner directly from the project's conftest (avoid picking up
# a different project's tests.conftest on sys.path)
import importlib.util as _ilu
_conftest_path = Path(__file__).resolve().parent.parent / "conftest.py"
_spec = _ilu.spec_from_file_location("_project_conftest", _conftest_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
make_mock_runner = _mod.make_mock_runner

_TEST_HEADERS = {"loginId": "test-user@walmart.com"}


def _build_client(app, **kwargs) -> TestClient:
    """Return a TestClient with the default loginId header pre-set."""
    return TestClient(app, headers=_TEST_HEADERS, **kwargs)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_e2e_app(runner=None, mcp_servers=None, mcp_tools=None, tasks=None):
    """Create a fully wired FastAPI app for e2e testing."""
    from app.routers import health, query
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    app = FastAPI()
    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(AgentError, agent_error_handler)
    app.include_router(health.router)
    app.include_router(query.router)
    # Note: A2A endpoint tests removed — the A2A layer is now ADK-native
    # (A2AStarletteApplication, A2A SDK 0.3 message/send). Tests rely on
    # a live server with factory.py lifespan wired up.

    app.state.runner = runner or make_mock_runner("default agent answer")
    app.state.tasks = tasks if tasks is not None else {}
    app.state.mcp_servers = mcp_servers or [{"name": "test-mcp", "url": "http://localhost:8999/mcp"}]
    app.state.mcp_tools = mcp_tools or ["check_health", "get_metrics"]
    return app


# ── Health check flows ────────────────────────────────────────────────────────

class TestHealthCheckFlow:
    """E2E: User checks if the agent is operational."""

    def test_full_health_check(self, client, env_vars):
        """GET /health → full status including servers, tools, LLM endpoint."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["mcp_tools"], list)
        assert isinstance(data["mcp_servers"], list)
        assert len(data["mcp_tools"]) > 0

    def test_readiness_probe(self, client):
        """GET /ready → simple 200 for Kubernetes."""
        resp = client.get("/ready")
        assert resp.status_code == 200

    def test_health_returns_active_llm(self, client, env_vars):
        """GET /health → active_llm field should be present."""
        resp = client.get("/health")
        data = resp.json()
        assert "active_llm" in data
        assert data["active_llm"] in ("openai", "claude")

    def test_health_returns_llm_endpoint(self, client, env_vars):
        """GET /health → llm_endpoint field should be a non-empty string."""
        resp = client.get("/health")
        data = resp.json()
        assert "llm_endpoint" in data
        assert isinstance(data["llm_endpoint"], str)

    def test_health_with_custom_mcp_state(self, env_vars):
        """GET /health → mcp_servers and mcp_tools come from app.state."""
        custom_servers = [
            {"name": "prod-mcp", "url": "http://prod:8999/mcp"},
            {"name": "staging-mcp", "url": "http://staging:8999/mcp"},
        ]
        custom_tools = ["check_health", "get_metrics", "describe_deployment"]
        app = _build_e2e_app(mcp_servers=custom_servers, mcp_tools=custom_tools)
        c = _build_client(app)
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        names = [s["name"] for s in data["mcp_servers"]]
        assert "prod-mcp" in names
        assert "staging-mcp" in names
        assert "describe_deployment" in data["mcp_tools"]


# ── Query flows ───────────────────────────────────────────────────────────────

class TestQueryFlow:
    """E2E: User submits a query, agent processes it end-to-end."""

    def test_simple_query_returns_response(self, env_vars):
        """User asks a question → agent answers directly."""
        runner = make_mock_runner("All 5 pods in intl-sre are healthy and running.")
        app = _build_e2e_app(runner=runner)
        c = _build_client(app)

        resp = c.post("/query", json={"query": "Is intl-sre healthy?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "healthy" in data["response"].lower()

    def test_query_response_contains_session_id(self, env_vars):
        """POST /query → response includes a session_id (UUID)."""
        app = _build_e2e_app()
        c = _build_client(app)

        resp = c.post("/query", json={"query": "Check pod status"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["session_id"]) == 36  # UUID format

    def test_query_with_explicit_session_id(self, env_vars):
        """User can provide their own session_id; it should be echoed back."""
        app = _build_e2e_app()
        c = _build_client(app)

        resp = c.post("/query", json={"query": "Test query", "session_id": "my-session-abc"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "my-session-abc"

    def test_query_validation_empty_string(self, client):
        """Empty query should return 422 Unprocessable Entity."""
        resp = client.post("/query", json={"query": ""})
        assert resp.status_code == 422

    def test_query_no_body(self, client):
        """Missing request body should return 422."""
        resp = client.post("/query")
        assert resp.status_code == 422

    def test_query_missing_query_field(self, client):
        """Body without 'query' field should return 422."""
        resp = client.post("/query", json={"text": "hello"})
        assert resp.status_code == 422

    def test_long_query_at_limit_accepted(self, env_vars):
        """Query at max length (4096 chars) should be accepted."""
        app = _build_e2e_app(runner=make_mock_runner("processed"))
        c = _build_client(app)
        long_query = "x" * 4096
        resp = c.post("/query", json={"query": long_query})
        assert resp.status_code == 200

    def test_query_too_long_rejected(self, client):
        """Query exceeding max length should be rejected with 422."""
        resp = client.post("/query", json={"query": "x" * 4097})
        assert resp.status_code == 422

    def test_query_runner_error_returns_500(self, env_vars):
        """When runner raises, /query should return HTTP 500."""
        async def _error_runner(**kwargs):
            raise RuntimeError("LLM timed out")
            yield  # make it a generator

        runner = MagicMock()
        runner.run_async = _error_runner
        app = _build_e2e_app(runner=runner)
        c = _build_client(app, raise_server_exceptions=False)
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 500

    def test_query_empty_runner_response(self, env_vars):
        """When runner yields no final event, response should be empty string."""
        async def _no_response(**kwargs):
            if False:
                yield
        runner = MagicMock()
        runner.run_async = _no_response
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        app = _build_e2e_app(runner=runner)
        c = _build_client(app)
        resp = c.post("/query", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["response"] == ""


# Note: A2A endpoint tests removed — the A2A layer is now ADK-native
# (A2AStarletteApplication, A2A SDK 0.3 message/send). Tests rely on
# a live server with factory.py lifespan wired up.


# ── Multiple queries: statelessness ──────────────────────────────────────────

class TestMultipleQueriesFlow:
    """E2E: Multiple sequential queries to verify per-request isolation."""

    def test_sequential_queries_get_independent_session_ids(self, env_vars):
        """Each query should get its own unique session_id."""
        app = _build_e2e_app()
        c = _build_client(app)

        session_ids = []
        for i in range(3):
            resp = c.post("/query", json={"query": f"Query number {i}"})
            assert resp.status_code == 200
            session_ids.append(resp.json()["session_id"])

        # All three session IDs should be distinct
        assert len(set(session_ids)) == 3

    def test_sequential_queries_return_runner_answer(self, env_vars):
        """Each query should return the runner's answer."""
        answers = ["Answer A", "Answer B", "Answer C"]
        idx = {"i": 0}
        async def _rotating_runner(**kwargs):
            answer = answers[idx["i"] % len(answers)]
            idx["i"] += 1
            mock_part = MagicMock()
            mock_part.text = answer
            mock_content = MagicMock()
            mock_content.parts = [mock_part]
            mock_event = MagicMock()
            mock_event.is_final_response.return_value = True
            mock_event.content = mock_content
            yield mock_event
        runner = MagicMock()
        runner.run_async = _rotating_runner
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        app = _build_e2e_app(runner=runner)
        c = _build_client(app)
        responses = []
        for i in range(3):
            resp = c.post("/query", json={"query": f"Query {i}"})
            assert resp.status_code == 200
            responses.append(resp.json()["response"])

        assert responses[0] == "Answer A"
        assert responses[1] == "Answer B"
        assert responses[2] == "Answer C"


# ── Claude LLM variant ────────────────────────────────────────────────────────

class TestClaudeLLMFlow:
    """E2E: Query flow using Claude as the primary LLM (config only)."""

    def test_health_shows_claude_when_primary(self, env_vars, monkeypatch):
        """When CLAUDE_IS_PRIMARY_LLM=true, /health should report active_llm=claude."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app()
        c = _build_client(app)
        resp = c.get("/health")
        assert resp.json()["active_llm"] == "claude"

        get_settings.cache_clear()

    def test_query_works_regardless_of_llm_config(self, env_vars, monkeypatch):
        """Queries should succeed whether OpenAI or Claude is the active LLM."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        runner = make_mock_runner("Claude-backed answer")
        app = _build_e2e_app(runner=runner)
        c = _build_client(app)
        resp = c.post("/query", json={"query": "Check health"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "Claude-backed answer"

        get_settings.cache_clear()


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """E2E: Edge cases and boundary conditions."""

    def test_health_and_query_and_ready_coexist(self, client):
        """All three main endpoints should work in the same session."""
        h = client.get("/health")
        assert h.status_code == 200

        q = client.post("/query", json={"query": "test query"})
        assert q.status_code == 200

        r = client.get("/ready")
        assert r.status_code == 200

    def test_query_special_characters_accepted(self, env_vars):
        """Queries with special characters should be processed correctly."""
        runner = make_mock_runner("Special chars processed")
        app = _build_e2e_app(runner=runner)
        c = _build_client(app)
        resp = c.post("/query", json={"query": "What's the CPU usage? (>80%)"})
        assert resp.status_code == 200

    def test_multiple_routers_all_accessible(self, env_vars):
        """All registered routers should be reachable simultaneously."""
        app = _build_e2e_app()
        c = _build_client(app)

        # Health router
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200

        # Query router
        assert c.post("/query", json={"query": "test"}).status_code == 200
