"""
Unit tests for the ``lifespan()`` context manager in app/api.py.

The lifespan does four things that need verification:
1. Reads settings (host/port) for logging
2. Creates two httpx.AsyncClient instances and an MCPPool
3. Populates ``app.state`` with mcp / http / llm references
4. On shutdown, closes both HTTP clients

All external I/O is patched so no live network connections are made.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_mock():
    """Return a minimal FastAPI-like mock that allows ``app.state.*`` assignments."""
    app = MagicMock()
    # Use a real object for state so attribute assignment works like a namespace
    from types import SimpleNamespace
    app.state = SimpleNamespace()
    return app


@pytest.fixture
def mcp_pool_mock():
    """Return a mock MCPPool with an async connect() and a list of sessions."""
    pool = MagicMock()
    pool.connect = AsyncMock()
    return pool


@pytest.fixture
def http_client_mock():
    """Return a mock httpx.AsyncClient."""
    client = MagicMock()
    client.aclose = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLifespanStartup:
    """Verify that the lifespan startup phase populates app.state correctly."""

    @pytest.mark.asyncio
    async def test_sets_mcp_on_app_state(self, env_vars, mcp_pool_mock, http_client_mock):
        """After startup, ``app.state.mcp`` must be the MCPPool instance."""
        from app.api import lifespan

        app = _make_app_mock()

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                assert app.state.mcp is mcp_pool_mock

    @pytest.mark.asyncio
    async def test_sets_http_client_on_app_state(self, env_vars, mcp_pool_mock, http_client_mock):
        """After startup, ``app.state.http`` must hold the main AsyncClient."""
        from app.api import lifespan

        app = _make_app_mock()

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                assert app.state.http is http_client_mock

    @pytest.mark.asyncio
    async def test_sets_llm_client_on_app_state(self, env_vars, mcp_pool_mock, http_client_mock):
        """After startup, ``app.state.llm`` must hold the LLM AsyncClient."""
        from app.api import lifespan

        app = _make_app_mock()

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                assert app.state.llm is http_client_mock

    @pytest.mark.asyncio
    async def test_calls_mcp_pool_connect(self, env_vars, mcp_pool_mock, http_client_mock):
        """The lifespan must call ``MCPPool.connect()`` during startup."""
        from app.api import lifespan

        app = _make_app_mock()

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                pass

        mcp_pool_mock.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mcp_connect_failure_does_not_raise(self, env_vars, http_client_mock):
        """If MCP pool connect fails the lifespan must continue, not crash."""
        from app.api import lifespan

        app = _make_app_mock()
        failing_pool = MagicMock()
        failing_pool.connect = AsyncMock(side_effect=ConnectionRefusedError("MCP down"))

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=failing_pool), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            # Should NOT raise — the lifespan catches connection errors
            async with lifespan(app):
                pass  # If we get here, the exception was correctly swallowed


class TestLifespanShutdown:
    """Verify that the lifespan shutdown phase cleans up resources."""

    @pytest.mark.asyncio
    async def test_closes_http_clients_on_shutdown(self, env_vars, mcp_pool_mock):
        """Both AsyncClient instances must have aclose() awaited after yield."""
        from app.api import lifespan

        app = _make_app_mock()
        close_mock = AsyncMock()
        client = MagicMock()
        client.aclose = close_mock

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=client):

            async with lifespan(app):
                pass  # yield point

        # Two AsyncClient instances created → aclose called twice
        assert close_mock.await_count == 2

    @pytest.mark.asyncio
    async def test_app_state_is_populated_before_yield(self, env_vars, mcp_pool_mock, http_client_mock):
        """app.state must be fully populated while inside the lifespan context."""
        from app.api import lifespan

        app = _make_app_mock()

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession"), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                # All three state keys must exist during the app's active phase
                assert hasattr(app.state, "mcp")
                assert hasattr(app.state, "http")
                assert hasattr(app.state, "llm")


class TestLifespanMCPSessions:
    """Verify that MCP server configs are translated into MCPSession objects."""

    @pytest.mark.asyncio
    async def test_creates_mcp_session_per_server_config(self, env_vars, mcp_pool_mock, http_client_mock):
        """One MCPSession must be created for each entry in the server config list."""
        from app.api import lifespan

        app = _make_app_mock()
        server1 = MagicMock()
        server1.url = "http://mcp1.test/mcp"
        server1.name = "mcp1"
        server2 = MagicMock()
        server2.url = "http://mcp2.test/mcp"
        server2.name = "mcp2"

        session_ctor = MagicMock(return_value=MagicMock())

        with patch("app.api.load_mcp_servers", return_value=[server1, server2]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession", session_ctor), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                pass

        # MCPSession called twice — once per server config
        assert session_ctor.call_count == 2

    @pytest.mark.asyncio
    async def test_no_sessions_created_when_no_server_configs(self, env_vars, mcp_pool_mock, http_client_mock):
        """When load_mcp_servers returns an empty list, MCPSession is never called."""
        from app.api import lifespan

        app = _make_app_mock()
        session_ctor = MagicMock(return_value=MagicMock())

        with patch("app.api.load_mcp_servers", return_value=[]), \
             patch("app.api.MCPPool", return_value=mcp_pool_mock), \
             patch("app.api.MCPSession", session_ctor), \
             patch("app.api.httpx.AsyncClient", return_value=http_client_mock):

            async with lifespan(app):
                pass

        session_ctor.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: /query and /query_api endpoints + _handle_query (lines 89, 104, 108-123)
# ---------------------------------------------------------------------------

import httpx as _httpx
from fastapi.testclient import TestClient as _TestClient


def _make_api_app(mcp=None, llm_client=None):
    """Build a minimal FastAPI app with only the api router, mocked state."""
    from app.api import router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.mcp = mcp or MagicMock()
    test_app.state.llm = llm_client or MagicMock()
    return test_app


class TestQueryEndpoint:
    """Tests for POST /query and POST /query_api — lines 89, 104, 108-123."""

    def test_query_returns_200_on_success(self, env_vars):
        """POST /query with a valid body must return HTTP 200."""
        from app.api import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.mcp = MagicMock()
        test_app.state.llm = MagicMock()

        with patch("app.api.run_agent_claude", new=AsyncMock(return_value="All healthy.")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = True
            resp = _TestClient(test_app).post("/query", json={"query": "Check health"})

        assert resp.status_code == 200

    def test_query_returns_response_and_session_id(self, env_vars):
        """POST /query response must contain both 'response' and 'session_id'."""
        from app.api import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.mcp = MagicMock()
        test_app.state.llm = MagicMock()

        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="OpenAI answer.")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = _TestClient(test_app).post("/query", json={"query": "test"})

        data = resp.json()
        assert "response" in data
        assert "session_id" in data

    def test_query_api_returns_200_on_success(self, env_vars):
        """POST /query_api must also return HTTP 200 — line 104."""
        from app.api import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.mcp = MagicMock()
        test_app.state.llm = MagicMock()

        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="OK")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = _TestClient(test_app).post("/query_api", json={"query": "test"})

        assert resp.status_code == 200

    def test_query_http_status_error_returns_502(self, env_vars):
        """When the LLM raises HTTPStatusError, the endpoint must return 502 — lines 114-118."""
        from app.api import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.mcp = MagicMock()
        test_app.state.llm = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        http_err = _httpx.HTTPStatusError("rate limited", request=MagicMock(), response=mock_response)

        with patch("app.api.run_agent_claude", new=AsyncMock(side_effect=http_err)), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = True
            resp = _TestClient(test_app).post("/query", json={"query": "test"})

        assert resp.status_code == 502
        assert "502" in resp.json()["detail"] or "LLM error" in resp.json()["detail"]

    def test_query_generic_exception_returns_500(self, env_vars):
        """When the LLM raises a generic Exception, the endpoint must return 500 — lines 120-122."""
        from app.api import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.mcp = MagicMock()
        test_app.state.llm = MagicMock()

        with patch("app.api.run_agent_openai", new=AsyncMock(side_effect=RuntimeError("unexpected crash"))), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = _TestClient(test_app).post("/query", json={"query": "test"})

        assert resp.status_code == 500
        assert "unexpected crash" in resp.json()["detail"]

    def test_query_with_explicit_session_id_echoes_it(self, env_vars):
        """When the caller supplies a session_id, it must be echoed in the response."""
        from app.api import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.mcp = MagicMock()
        test_app.state.llm = MagicMock()

        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="OK")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = _TestClient(test_app).post(
                "/query", json={"query": "test", "session_id": "my-custom-session"}
            )

        assert resp.json()["session_id"] == "my-custom-session"


# ---------------------------------------------------------------------------
# Tests: create_app() — lines 163-178
# ---------------------------------------------------------------------------

class TestCreateApp:
    """Tests for create_app() — verifies the app factory wires things correctly."""

    def test_create_app_returns_fastapi_instance(self, env_vars):
        """create_app() must return a FastAPI application."""
        from app.api import create_app
        from fastapi import FastAPI

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_create_app_has_cors_middleware(self, env_vars):
        """create_app() must add the CORS middleware."""
        from app.api import create_app
        from starlette.middleware.cors import CORSMiddleware

        app = create_app()
        assert any(
            (hasattr(m, "cls") and m.cls is CORSMiddleware)
            or isinstance(m, CORSMiddleware)
            for m in app.user_middleware
        )

    def test_create_app_title(self, env_vars):
        """create_app() must set the app title to 'A2A Query Agent'."""
        from app.api import create_app

        app = create_app()
        assert app.title == "A2A Query Agent"

    def test_create_app_includes_query_routes(self, env_vars):
        """The app must expose /query and /query_api routes."""
        from app.api import create_app

        app = create_app()
        paths = {route.path for route in app.routes}
        assert "/query" in paths
        assert "/query_api" in paths
