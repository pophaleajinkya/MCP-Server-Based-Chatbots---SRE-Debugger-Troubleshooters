"""
Integration tests — verify cross-module interactions work correctly.

Tests the interaction between:
- Config → Factory → Routers
- Request Context → Runner → Agent
- Store Keys → Redis Session Service patterns
- Exceptions → Error Handlers → Router responses
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Health Endpoint Integration ───────────────────────────────────────────────

class TestHealthEndpointIntegration:
    """Verify /health, /ready, /liveness endpoints work with app state."""

    @pytest.fixture
    def app(self):
        from app.routers import health
        from app.exceptions import LLMError, llm_error_handler

        test_app = FastAPI()
        test_app.add_exception_handler(LLMError, llm_error_handler)
        test_app.include_router(health.router)
        test_app.state.mcp_servers = [
            {"name": "health-mcp", "url": "http://localhost:8999/mcp/"},
        ]
        test_app.state.mcp_tools = ["check_health", "get_metrics"]
        return test_app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_mcp_info(self, client):
        r = client.get("/health")
        data = r.json()
        assert "mcp_servers" in data
        assert "mcp_tools" in data
        assert len(data["mcp_servers"]) == 1
        assert len(data["mcp_tools"]) == 2

    def test_ready_returns_200(self, client):
        r = client.get("/ready")
        assert r.status_code == 200

    def test_liveness_returns_200(self, client):
        r = client.get("/liveness")
        assert r.status_code == 200


# ── Query Router Integration ─────────────────────────────────────────────────

class TestQueryRouterIntegration:
    """Verify POST /query correctly resolves user identity."""

    @pytest.fixture
    def app(self):
        from app.routers import query
        from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

        test_app = FastAPI()
        test_app.add_exception_handler(LLMError, llm_error_handler)
        test_app.add_exception_handler(AgentError, agent_error_handler)
        test_app.include_router(query.router)

        # Mock runner
        mock_part = MagicMock()
        mock_part.text = "answer"
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = mock_content

        async def _fake_run(**kw):
            yield mock_event

        mock_runner = MagicMock()
        mock_runner.run_async = _fake_run
        mock_runner.session_service = MagicMock()
        mock_runner.session_service.get_session = AsyncMock(return_value=None)
        mock_runner.session_service.create_session = AsyncMock()
        mock_runner.__aenter__ = AsyncMock(return_value=mock_runner)
        mock_runner.__aexit__ = AsyncMock(return_value=None)

        test_app.state.runner = mock_runner
        test_app.state.mcp_servers = []
        test_app.state.mcp_tools = []
        test_app.state.tasks = {}
        return test_app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_query_with_login_id_header(self, client):
        r = client.post(
            "/query",
            json={"query": "test"},
            headers={"loginId": "alice@walmart.com"},
        )
        assert r.status_code == 200

    def test_query_with_body_user_id(self, client):
        r = client.post(
            "/query",
            json={"query": "test", "user_id": "bob@walmart.com"},
        )
        assert r.status_code == 200

    def test_query_missing_user_returns_422(self, client):
        r = client.post(
            "/query",
            json={"query": "test"},
        )
        assert r.status_code == 422

    def test_query_api_alias_works(self, client):
        r = client.post(
            "/query_api",
            json={"query": "test"},
            headers={"loginId": "test@walmart.com"},
        )
        assert r.status_code == 200


# ── Exception Handler Integration ─────────────────────────────────────────────

class TestExceptionHandlerIntegration:
    """Verify exception handlers produce correct HTTP responses."""

    @pytest.fixture
    def app(self):
        from app.exceptions import (
            LLMError, AgentError, MCPConnectionError,
            llm_error_handler, agent_error_handler, mcp_connection_error_handler,
        )

        test_app = FastAPI()
        test_app.add_exception_handler(LLMError, llm_error_handler)
        test_app.add_exception_handler(AgentError, agent_error_handler)
        test_app.add_exception_handler(MCPConnectionError, mcp_connection_error_handler)

        @test_app.get("/raise-llm")
        async def raise_llm():
            raise LLMError(502, "LLM timeout")

        @test_app.get("/raise-agent")
        async def raise_agent():
            raise AgentError("loop crash")

        @test_app.get("/raise-mcp")
        async def raise_mcp():
            raise MCPConnectionError("server down")

        return test_app

    @pytest.fixture
    def client(self, app):
        return TestClient(app, raise_server_exceptions=False)

    def test_llm_error_returns_502(self, client):
        r = client.get("/raise-llm")
        assert r.status_code == 502
        assert "error" in r.json()

    def test_agent_error_returns_500(self, client):
        r = client.get("/raise-agent")
        assert r.status_code == 500
        assert "error" in r.json()

    def test_mcp_error_returns_503(self, client):
        r = client.get("/raise-mcp")
        assert r.status_code == 503
        assert "error" in r.json()


# ── Config & Constants Integration ────────────────────────────────────────────

class TestConfigIntegration:
    """Verify config values are consistent with constants."""

    def test_app_name_constant_is_valid(self, env_vars):
        from app.constants import APP_NAME
        assert isinstance(APP_NAME, str)
        assert len(APP_NAME) > 0

    def test_mcp_config_key_uses_env(self, env_vars, monkeypatch):
        monkeypatch.setenv("AGENT_ENV", "stage")
        monkeypatch.setenv("AGENT_GROUP", "sre")
        from app.config import Settings
        s = Settings()
        assert "stage" in s.mcp_config_key
        assert "sre" in s.mcp_config_key


# ── Store Keys Consistency ────────────────────────────────────────────────────

class TestStoreKeysConsistency:
    """Verify store keys are used consistently across modules."""

    def test_ui_events_key_matches_session_service_pattern(self):
        from app.store.keys import key_ui_events
        k = key_ui_events("health_agent", "admin", "sess-1")
        assert k.startswith("agent:ui_events:")

    def test_session_key_matches_adk_pattern(self):
        from app.store.keys import key_session
        k = key_session("health_agent", "admin", "sess-1")
        assert k.startswith("adk:session:")


# ── Request Context Pipeline ─────────────────────────────────────────────────

class TestRequestContextPipeline:
    """Verify header extraction → storage → retrieval pipeline."""

    def test_full_pipeline(self):
        from app.request_context import (
            extract_llm_headers, set_llm_headers, get_llm_headers, clear_llm_headers,
        )
        req = MagicMock()
        req.headers = {
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "pipeline-test",
        }
        headers = extract_llm_headers(req)
        set_llm_headers(headers)
        retrieved = get_llm_headers()
        assert retrieved["wm_llm_gw.user_name"] == "pipeline-test"
        clear_llm_headers()
        assert get_llm_headers() == {}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("AGENT_HOST", "127.0.0.1")
    monkeypatch.setenv("AGENT_PORT", "9999")
    monkeypatch.setenv("ELEMENT_GATEWAY_BASE_URL", "https://llm.test.com/openai")
    monkeypatch.setenv("ELEMENT_GATEWAY_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4-test")
    monkeypatch.setenv("CLAUDE_GATEWAY_URL", "https://claude.test.com/messages")
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key-claude")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-test")
    monkeypatch.setenv("CLAUDE_ANTHROPIC_VERSION", "vertex-2023-10-16")
    monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "false")
    monkeypatch.setenv("MAX_TOOL_ROUNDS", "3")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "5")
