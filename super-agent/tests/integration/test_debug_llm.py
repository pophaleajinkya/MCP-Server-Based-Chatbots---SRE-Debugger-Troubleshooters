"""Integration tests for the debug router.

Tests that Settings values are correctly reflected in /debug/llm responses,
and that the endpoint behaves correctly when wired with the full router set.
"""

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub google packages when absent.
try:
    import google.adk
except ImportError:
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.adk", ModuleType("google.adk"))
    sys.modules.setdefault("google.adk.runners", MagicMock())
    sys.modules.setdefault("google.adk.agents", MagicMock())
    sys.modules.setdefault("google.adk.agents.callback_context", MagicMock())
    sys.modules.setdefault("google.adk.tools.mcp_tool.mcp_toolset", MagicMock())
    sys.modules.setdefault("google.adk.models.lite_llm", MagicMock())

try:
    import google.genai  # noqa: F401
except ImportError:
    sys.modules.setdefault("google.genai", MagicMock())


# ── App builder ───────────────────────────────────────────────────────────────

def _build_app(extra_headers: dict | None = None) -> FastAPI:
    """Build a test app with health, query, and debug routers.

    Note: A2A endpoint is mounted via ADK's A2AStarletteApplication during
    lifespan — not included here.
    """
    from app.routers import health, query, debug
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    mock_model = MagicMock()
    mock_model._additional_args = {"extra_headers": extra_headers or {}}
    mock_agent = MagicMock()
    mock_agent.model = mock_model
    mock_runner = MagicMock()
    mock_runner.agent = mock_agent
    mock_runner.session_service = MagicMock()

    app = FastAPI()
    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(AgentError, agent_error_handler)
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(debug.router)

    app.state.runner = mock_runner
    app.state.tasks = {}
    app.state.mcp_servers = [{"name": "test-mcp", "url": "http://localhost:8999/mcp"}]
    app.state.mcp_tools = ["check_health", "get_metrics"]
    return app


# ── Settings → /debug/llm wiring ─────────────────────────────────────────────

class TestSettingsToDebugLlmWiring:
    """Verify that Settings fields are correctly reflected in /debug/llm."""

    def test_openai_settings_produce_azure_provider(self, env_vars):
        app = _build_app()
        data = TestClient(app).get("/debug/llm").json()
        assert data["provider"] == "azure"
        assert data["is_primary_llm"] is False

    def test_openai_api_base_reflects_settings_url(self, env_vars):
        app = _build_app()
        data = TestClient(app).get("/debug/llm").json()
        # ELEMENT_GATEWAY_BASE_URL=https://llm.test.com/openai in env_vars fixture
        assert "llm.test.com" in data["api_base"]

    def test_openai_model_name_reflects_settings(self, env_vars):
        app = _build_app()
        data = TestClient(app).get("/debug/llm").json()
        assert "gpt-4-test" in data["model"]

    def test_claude_settings_produce_anthropic_provider(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app()
        data = TestClient(app).get("/debug/llm").json()
        assert data["provider"] == "anthropic"
        assert data["is_primary_llm"] is True

        get_settings.cache_clear()

    def test_claude_api_base_reflects_gateway_url(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app()
        data = TestClient(app).get("/debug/llm").json()
        # CLAUDE_GATEWAY_URL=https://claude.test.com/messages in env_vars fixture
        assert "claude.test.com" in data["api_base"]

        get_settings.cache_clear()

    def test_claude_model_name_reflects_settings(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app()
        data = TestClient(app).get("/debug/llm").json()
        assert "claude-test" in data["model"]

        get_settings.cache_clear()


# ── Prompt caching config wiring ─────────────────────────────────────────────

class TestPromptCachingConfigWiring:
    """Verify caching status is correctly derived from settings + model headers."""

    def test_caching_disabled_by_default(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "false")
        from app.config import get_settings
        get_settings.cache_clear()

        # No beta header on model (caching disabled)
        app = _build_app(extra_headers={"anthropic-version": "vertex-2023-10-16"})
        caching = TestClient(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["status"] == "DISABLED"
        assert caching["beta_header_present"] is False

        get_settings.cache_clear()

    def test_caching_enabled_flag_with_beta_header_shows_header_present(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app(extra_headers={
            "anthropic-version": "vertex-2023-10-16",
            "anthropic-beta": "prompt-caching-2024-07-31",
        })
        caching = TestClient(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["beta_header_present"] is True
        assert "HEADER_PRESENT" in caching["status"]
        assert caching["beta_header_value"] == "prompt-caching-2024-07-31"

        get_settings.cache_clear()

    def test_openai_provider_always_na_regardless_of_cache_flag(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "false")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app()
        caching = TestClient(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["status"] == "N/A"

        get_settings.cache_clear()

    def test_beta_header_value_matches_expected_anthropic_string(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app(extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"})
        caching = TestClient(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["beta_header_value"] == "prompt-caching-2024-07-31"

        get_settings.cache_clear()

    def test_missing_beta_header_shows_beta_header_value_null(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_app(extra_headers={"anthropic-version": "vertex-2023-10-16"})
        caching = TestClient(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["beta_header_value"] is None

        get_settings.cache_clear()


# ── Debug router coexists with other routers ─────────────────────────────────

class TestDebugRouterCoexistence:
    """Verify /debug/llm works alongside all other registered routers."""

    def test_debug_llm_and_health_both_return_200(self, env_vars):
        app = _build_app()
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        assert client.get("/debug/llm").status_code == 200

    def test_debug_llm_and_ready_both_accessible(self, env_vars):
        app = _build_app()
        client = TestClient(app)
        assert client.get("/ready").status_code == 200
        assert client.get("/debug/llm").status_code == 200

    def test_debug_prefix_does_not_conflict_with_other_routes(self, env_vars):
        """No other registered route should shadow /debug/llm."""
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/debug/llm")
        # Must be served by the debug router (200), not a 404 or redirect
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data

    def test_debug_llm_is_independent_of_query_runner_state(self, env_vars):
        """GET /debug/llm must not require the runner's run_async to be called."""
        app = _build_app()
        # Never POST /query — debug/llm should still work
        resp = TestClient(app).get("/debug/llm")
        assert resp.status_code == 200
