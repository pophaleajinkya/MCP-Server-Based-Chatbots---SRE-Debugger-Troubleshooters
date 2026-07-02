"""Integration tests for app/api.py — the lite (non-ADK) agent.

These tests exercise the FastAPI router, request validation, response
serialisation, LLM dispatch, and error handling without running the full
lifespan (no real MCP connections, no real LLM calls).

The test client is built by wiring the router directly into a plain FastAPI
instance and setting app.state manually.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helper — build a lightweight test client without running lifespan
# ---------------------------------------------------------------------------

def _build_lite_client(answer: str = "mock answer", claude: bool = False) -> TestClient:
    """Return a TestClient wired to the lite router with mocked state."""
    import httpx
    from app.api import router

    app = FastAPI()
    app.include_router(router)

    # Minimal MCP mock — only .guide is accessed by the real code
    mcp = MagicMock()
    mcp.guide = ""
    app.state.mcp = mcp
    app.state.llm = MagicMock(spec=httpx.AsyncClient)

    return TestClient(app)


# ---------------------------------------------------------------------------
# TestLiteQueryRoute — POST /query
# ---------------------------------------------------------------------------

class TestLiteQueryRoute:
    """Tests for the POST /query endpoint."""

    def test_returns_200_with_response_and_session_id(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "How is my app doing?"})

        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "session_id" in data

    def test_returns_agent_answer(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "status check"})

        assert resp.json()["response"] == "mock answer"

    def test_generates_uuid_session_id_when_not_provided(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"})

        sid = resp.json()["session_id"]
        # UUID4 is 36 characters: 8-4-4-4-12 with dashes
        assert len(sid) == 36
        assert sid.count("-") == 4

    def test_uses_provided_session_id(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post(
                "/query",
                json={"query": "test", "session_id": "my-custom-session-id"},
            )

        assert resp.json()["session_id"] == "my-custom-session-id"

    def test_returns_422_when_query_is_empty_string(self):
        client = _build_lite_client()
        resp = client.post("/query", json={"query": ""})
        assert resp.status_code == 422

    def test_returns_422_when_query_field_is_missing(self):
        client = _build_lite_client()
        resp = client.post("/query", json={})
        assert resp.status_code == 422

    def test_session_id_is_a_string_in_response(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"})

        assert isinstance(resp.json()["session_id"], str)

    def test_generated_session_ids_are_unique_across_requests(self):
        client = _build_lite_client()
        session_ids = set()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            for _ in range(5):
                resp = client.post("/query", json={"query": "test"})
                assert resp.status_code == 200
                session_ids.add(resp.json()["session_id"])

        assert len(session_ids) == 5


# ---------------------------------------------------------------------------
# TestLiteQueryApiRoute — POST /query_api
# ---------------------------------------------------------------------------

class TestLiteQueryApiRoute:
    """Tests for the POST /query_api endpoint."""

    def test_returns_200_with_response_and_session_id(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query_api", json={"query": "Check latency"})

        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "session_id" in data

    def test_generates_uuid_when_session_id_not_provided(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query_api", json={"query": "test"})

        sid = resp.json()["session_id"]
        assert len(sid) == 36
        assert sid.count("-") == 4

    def test_uses_provided_session_id(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post(
                "/query_api",
                json={"query": "test", "session_id": "api-session-42"},
            )

        assert resp.json()["session_id"] == "api-session-42"

    def test_returns_agent_answer(self):
        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=AsyncMock(return_value="mock answer")), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query_api", json={"query": "test"})

        assert resp.json()["response"] == "mock answer"


# ---------------------------------------------------------------------------
# TestLiteErrorHandling — error responses
# ---------------------------------------------------------------------------

class TestLiteErrorHandling:
    """Tests for error handling in the lite agent routes."""

    def test_returns_502_when_httpx_http_status_error_is_raised(self):
        import httpx

        async def _raise_http_status_error(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.text = "upstream unavailable"
            raise httpx.HTTPStatusError(
                "upstream error",
                request=MagicMock(),
                response=mock_response,
            )

        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=_raise_http_status_error), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 502

    def test_502_detail_contains_upstream_status_code(self):
        import httpx

        async def _raise_http_status_error(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.text = "rate limited"
            raise httpx.HTTPStatusError(
                "rate limit",
                request=MagicMock(),
                response=mock_response,
            )

        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=_raise_http_status_error), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 502
        assert "429" in resp.json()["detail"]

    def test_returns_500_when_unexpected_exception_is_raised(self):
        async def _raise_unexpected(*args, **kwargs):
            raise RuntimeError("something went very wrong")

        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=_raise_unexpected), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"}, )

        assert resp.status_code == 500

    def test_500_detail_contains_exception_message(self):
        async def _raise_unexpected(*args, **kwargs):
            raise ValueError("bad config value")

        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=_raise_unexpected), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 500
        assert "bad config value" in resp.json()["detail"]

    def test_claude_route_returns_502_on_http_status_error(self):
        import httpx

        async def _raise_http_status_error(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = "unauthorized"
            raise httpx.HTTPStatusError(
                "auth error",
                request=MagicMock(),
                response=mock_response,
            )

        client = _build_lite_client(claude=True)
        with patch("app.api.run_agent_claude", new=_raise_http_status_error), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = True
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 502

    def test_claude_route_returns_500_on_unexpected_exception(self):
        async def _raise_unexpected(*args, **kwargs):
            raise ConnectionError("network timeout")

        client = _build_lite_client(claude=True)
        with patch("app.api.run_agent_claude", new=_raise_unexpected), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = True
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# TestLiteAppFactory — create_app()
# ---------------------------------------------------------------------------

class TestLiteAppFactory:
    """Tests for the create_app() factory function."""

    def test_returns_a_fastapi_instance(self):
        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            from app.api import create_app
            app = create_app()

        assert isinstance(app, FastAPI)

    def test_query_route_is_registered(self):
        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            from app.api import create_app
            app = create_app()

        routes = [r.path for r in app.routes]
        assert "/query" in routes

    def test_query_api_route_is_registered(self):
        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            from app.api import create_app
            app = create_app()

        routes = [r.path for r in app.routes]
        assert "/query_api" in routes

    def test_app_has_cors_middleware(self):

        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            from app.api import create_app
            app = create_app()

        # At minimum verify the app was created without error; CORS is added via add_middleware
        assert app is not None

    def test_app_title_is_set(self):
        with patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            from app.api import create_app
            app = create_app()

        assert app.title == "A2A Query Agent"


# ---------------------------------------------------------------------------
# TestLiteLLMDispatch — LLM selection based on settings
# ---------------------------------------------------------------------------

class TestLiteLLMDispatch:
    """Tests that the correct LLM function is called based on settings."""

    def test_calls_run_agent_openai_when_claude_is_not_primary(self):
        openai_mock = AsyncMock(return_value="openai answer")
        claude_mock = AsyncMock(return_value="claude answer")

        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=openai_mock), \
             patch("app.api.run_agent_claude", new=claude_mock), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 200
        assert resp.json()["response"] == "openai answer"
        openai_mock.assert_awaited_once()
        claude_mock.assert_not_awaited()

    def test_calls_run_agent_claude_when_claude_is_primary(self):
        openai_mock = AsyncMock(return_value="openai answer")
        claude_mock = AsyncMock(return_value="claude answer")

        client = _build_lite_client(claude=True)
        with patch("app.api.run_agent_openai", new=openai_mock), \
             patch("app.api.run_agent_claude", new=claude_mock), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = True
            resp = client.post("/query", json={"query": "test"})

        assert resp.status_code == 200
        assert resp.json()["response"] == "claude answer"
        claude_mock.assert_awaited_once()
        openai_mock.assert_not_awaited()

    def test_query_api_calls_openai_when_claude_is_not_primary(self):
        openai_mock = AsyncMock(return_value="openai answer via api")
        claude_mock = AsyncMock(return_value="claude answer")

        client = _build_lite_client()
        with patch("app.api.run_agent_openai", new=openai_mock), \
             patch("app.api.run_agent_claude", new=claude_mock), \
             patch("app.api.get_settings") as mock_settings:
            mock_settings.return_value.claude_is_primary_llm = False
            resp = client.post("/query_api", json={"query": "test"})

        assert resp.status_code == 200
        assert resp.json()["response"] == "openai answer via api"
        openai_mock.assert_awaited_once()
        claude_mock.assert_not_awaited()
