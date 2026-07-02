# Note: A2A endpoint tests removed — the A2A layer is now handled by ADK's
# A2AStarletteApplication (A2A SDK 0.3). It uses message/send protocol,
# not the legacy tasks/send. A2A integration is covered by E2E tests.

"""Integration tests for FastAPI routers — health, query, a2a.

These tests use the FastAPI TestClient with a mocked ADK runner to verify
HTTP routing, request validation, response serialisation, and exception
handling across the router boundaries.

The runner is mocked via conftest fixtures — no real ADK or LLM calls.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub google.adk / google.genai only when the real packages are not installed.
# When the real packages ARE present we must not overwrite sys.modules —
# doing so corrupts the google namespace package for every subsequent test.
try:
    import google.adk
except ImportError:
    mock_adk = ModuleType("google.adk")
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.adk", mock_adk)
    sys.modules.setdefault("google.adk.runners", MagicMock())
    sys.modules.setdefault("google.adk.sessions.in_memory_session_service", MagicMock())
    sys.modules.setdefault("google.adk.agents", MagicMock())
    sys.modules.setdefault("google.adk.agents.callback_context", MagicMock())
    sys.modules.setdefault("google.adk.tools.mcp_tool.mcp_toolset", MagicMock())
    sys.modules.setdefault("google.adk.models.lite_llm", MagicMock())

try:
    import google.genai  # noqa: F401
except ImportError:
    mock_genai = ModuleType("google.genai")
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.genai", mock_genai)
    sys.modules.setdefault("google.genai.some_submodule", MagicMock())


from pathlib import Path

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


# ── Health router ─────────────────────────────────────────────────────────────

class TestHealthRouter:
    """Test GET /health and GET /ready endpoints."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_returns_version(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["version"] == "2.0.0"

    def test_health_includes_active_llm(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "active_llm" in data
        assert data["active_llm"] in ("openai", "claude")

    def test_health_includes_llm_endpoint(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "llm_endpoint" in data
        assert len(data["llm_endpoint"]) > 0

    def test_health_includes_mcp_servers(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "mcp_servers" in data
        assert len(data["mcp_servers"]) == 1
        assert data["mcp_servers"][0]["name"] == "test-mcp"
        assert "url" in data["mcp_servers"][0]

    def test_health_includes_mcp_tools(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "mcp_tools" in data
        assert "check_health" in data["mcp_tools"]
        assert "get_metrics" in data["mcp_tools"]

    def test_health_full_response_structure(self, client):
        resp = client.get("/health")
        data = resp.json()
        required_fields = {"status", "version", "active_llm", "llm_endpoint", "mcp_servers", "mcp_tools"}
        assert required_fields.issubset(data.keys())

    def test_ready_returns_200(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200

    def test_ready_returns_status_ready(self, client):
        resp = client.get("/ready")
        assert resp.json() == {"status": "ready"}

    def test_health_active_llm_openai_when_not_claude(self, app, env_vars):
        """When CLAUDE_IS_PRIMARY_LLM is false, active_llm should be openai."""
        test_client = _build_client(app)
        resp = test_client.get("/health")
        data = resp.json()
        assert data["active_llm"] == "openai"


# ── Query router ──────────────────────────────────────────────────────────────

class TestQueryRouter:
    """Test POST /query endpoint."""

    def test_query_success(self, client):
        """Successful query should return 200 with response and session_id."""
        resp = client.post("/query", json={"query": "Check health of intl-sre"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "session_id" in data

    def test_query_returns_runner_answer(self, client):
        """Query response should match what the mock runner returns."""
        resp = client.post("/query", json={"query": "test"})
        data = resp.json()
        assert data["response"] == "Test response from agent"

    def test_query_with_session_id(self, client):
        """Custom session_id should be echoed back."""
        resp = client.post("/query", json={
            "query": "test",
            "session_id": "custom-session-42",
        })
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "custom-session-42"

    def test_query_generates_session_id_when_missing(self, client):
        """When no session_id is provided, a UUID should be generated."""
        resp = client.post("/query", json={"query": "test"})
        sid = resp.json()["session_id"]
        assert len(sid) == 36  # UUID4 format: 8-4-4-4-12

    def test_query_empty_body_rejected(self, client):
        """Missing query field should return 422."""
        resp = client.post("/query", json={})
        assert resp.status_code == 422

    def test_query_empty_string_rejected(self, client):
        """Empty query string should return 422."""
        resp = client.post("/query", json={"query": ""})
        assert resp.status_code == 422

    def test_query_no_body_rejected(self, client):
        """Missing request body should return 422."""
        resp = client.post("/query")
        assert resp.status_code == 422

    def test_query_max_length_accepted(self, app):
        """Query at max length (4096 chars) should be accepted."""
        app.state.runner = make_mock_runner("processed long query")
        test_client = _build_client(app)
        resp = test_client.post("/query", json={"query": "x" * 4096})
        assert resp.status_code == 200

    def test_query_exceeds_max_length_rejected(self, client):
        """Query exceeding max length (4097 chars) should be rejected."""
        resp = client.post("/query", json={"query": "x" * 4097})
        assert resp.status_code == 422

    def test_query_session_ids_are_unique(self, client):
        """Multiple queries without session_id should get different UUIDs."""
        session_ids = set()
        for _ in range(5):
            resp = client.post("/query", json={"query": "test"})
            assert resp.status_code == 200
            session_ids.add(resp.json()["session_id"])
        assert len(session_ids) == 5

    def test_query_runner_error_propagates_as_500(self, app):
        """If runner raises an exception, it should return 500."""
        async def _failing_run_async(**kwargs):
            raise RuntimeError("runner crashed")
            yield  # make it a generator

        failing_runner = MagicMock()
        failing_runner.run_async = _failing_run_async
        app.state.runner = failing_runner

        test_client = _build_client(app, raise_server_exceptions=False)
        resp = test_client.post("/query", json={"query": "test"})
        assert resp.status_code == 500

    def test_query_response_contains_both_fields(self, client):
        """Query response must always have both 'response' and 'session_id'."""
        resp = client.post("/query", json={"query": "test"})
        data = resp.json()
        assert "response" in data
        assert "session_id" in data

