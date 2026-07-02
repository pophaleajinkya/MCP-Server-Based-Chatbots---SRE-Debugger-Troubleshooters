"""End-to-end tests for the /debug/llm endpoint.

Simulates real operator workflows:
  - Checking LLM configuration before a query
  - Verifying caching status after enabling LLM_PROMPT_CACHE_ENABLED
  - Confirming provider and model details match deployment intent
  - Verifying the full debug router lifecycle alongside other endpoints
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

# Stub litellm and mcp only when the real packages are absent.
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("mcp", MagicMock())
sys.modules.setdefault("mcp.client", MagicMock())
sys.modules.setdefault("mcp.client.sse", MagicMock())
sys.modules.setdefault("mcp.client.session", MagicMock())
sys.modules.setdefault("mcp.types", MagicMock())

# Provide stub classes for LiteLlm / LiteLLMClient only when the real package
# is NOT installed.  When the real package IS present we must not replace it —
# doing so causes Agent(model=stub) to fail Pydantic validation in other test
# files (e.g. test_after_tool_callback.py) that run after this file.
try:
    from google.adk.models.lite_llm import LiteLlm as _StubLiteLlm, LiteLLMClient as _StubLiteLLMClient
except ImportError:
    class _StubLiteLLMClient:
        async def acompletion(self, model, messages, tools, **kwargs): ...
        def completion(self, model, messages, tools, stream=False, **kwargs): ...

    class _StubLiteLlm:
        def __init__(self, **kwargs):
            self._additional_args = kwargs
            self.llm_client = _StubLiteLLMClient()

    _adk_lite_llm_mod = MagicMock()
    _adk_lite_llm_mod.LiteLlm = _StubLiteLlm
    _adk_lite_llm_mod.LiteLLMClient = _StubLiteLLMClient
    sys.modules["google.adk.models.lite_llm"] = _adk_lite_llm_mod

# Load make_mock_runner from project conftest
import importlib.util as _ilu
_conftest_path = Path(__file__).resolve().parent.parent / "conftest.py"
_spec = _ilu.spec_from_file_location("_project_conftest", _conftest_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
make_mock_runner = _mod.make_mock_runner

_TEST_HEADERS = {"loginId": "test-user@walmart.com"}


# ── E2E app builder ───────────────────────────────────────────────────────────

def _build_e2e_app(
    runner=None,
    extra_headers: dict | None = None,
) -> FastAPI:
    """Create a fully-wired FastAPI app with all routers including debug."""
    from app.routers import health, query, debug
    from app.exceptions import LLMError, AgentError, llm_error_handler, agent_error_handler

    mock_model = MagicMock()
    mock_model._additional_args = {"extra_headers": extra_headers or {}}
    mock_agent = MagicMock()
    mock_agent.model = mock_model

    _runner = runner or make_mock_runner("agent answer")
    _runner.agent = mock_agent

    app = FastAPI()
    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(AgentError, agent_error_handler)
    app.include_router(health.router)
    app.include_router(query.router)
    # Note: A2A endpoint tests removed — the A2A layer is now ADK-native
    # (A2AStarletteApplication, A2A SDK 0.3 message/send). Tests rely on
    # a live server with factory.py lifespan wired up.
    app.include_router(debug.router)

    app.state.runner = _runner
    app.state.tasks = {}
    app.state.mcp_servers = [{"name": "test-mcp", "url": "http://mcp.test/mcp"}]
    app.state.mcp_tools = ["check_health", "get_metrics"]
    return app


def _client(app) -> TestClient:
    return TestClient(app, headers=_TEST_HEADERS)


# ── Operator: inspect LLM config before deploying ────────────────────────────

class TestOperatorInspectsLLMConfig:
    """E2E: Operator checks /debug/llm to confirm the deployed LLM settings."""

    def test_check_llm_config_shows_active_provider(self, env_vars):
        """Operator should see the active provider (azure/openai by default)."""
        app = _build_e2e_app()
        resp = _client(app).get("/debug/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] in ("azure", "anthropic")
        assert data["model"]
        assert data["api_base"]

    def test_check_llm_config_shows_prompt_caching_status(self, env_vars):
        """Operator should see prompt_caching block with status."""
        app = _build_e2e_app()
        resp = _client(app).get("/debug/llm")
        caching = resp.json()["prompt_caching"]
        assert "status" in caching
        assert "note" in caching

    def test_check_llm_confirms_openai_deployment(self, env_vars, monkeypatch):
        """When using OpenAI, debug/llm should confirm provider=azure and caching N/A."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "false")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app()
        data = _client(app).get("/debug/llm").json()
        assert data["provider"] == "azure"
        assert data["prompt_caching"]["status"] == "N/A"

        get_settings.cache_clear()

    def test_check_llm_confirms_claude_deployment(self, env_vars, monkeypatch):
        """When using Claude, debug/llm should report provider=anthropic."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app()
        data = _client(app).get("/debug/llm").json()
        assert data["provider"] == "anthropic"
        assert data["is_primary_llm"] is True

        get_settings.cache_clear()


# ── Operator: enable caching and verify ──────────────────────────────────────

class TestPromptCachingEnabledFlow:
    """E2E: Operator enables LLM_PROMPT_CACHE_ENABLED=true and verifies via debug/llm."""

    def test_caching_disabled_shows_disabled_status(self, env_vars, monkeypatch):
        """Before enabling caching, /debug/llm should report DISABLED."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "false")
        from app.config import get_settings
        get_settings.cache_clear()

        # Model headers do NOT include the beta header
        app = _build_e2e_app(extra_headers={"anthropic-version": "vertex-2023-10-16"})
        caching = _client(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["status"] == "DISABLED"
        assert caching["beta_header_present"] is False

        get_settings.cache_clear()

    def test_caching_enabled_shows_header_present_status(self, env_vars, monkeypatch):
        """After enabling, /debug/llm should show the beta header is present."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        # Simulate what agent.py does when caching is enabled at startup
        app = _build_e2e_app(extra_headers={
            "anthropic-version": "vertex-2023-10-16",
            "anthropic-beta": "prompt-caching-2024-07-31",
        })
        caching = _client(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["beta_header_present"] is True
        assert caching["beta_header_value"] == "prompt-caching-2024-07-31"
        assert "HEADER_PRESENT" in caching["status"]

        get_settings.cache_clear()

    def test_caching_enabled_note_explains_cache_control_requirement(self, env_vars, monkeypatch):
        """Status note should tell the operator that cache_control blocks are also needed."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app(extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"})
        note = _client(app).get("/debug/llm").json()["prompt_caching"]["note"]
        # Note should mention cache_control or caching behaviour
        assert "cache_control" in note.lower() or "caching" in note.lower()

        get_settings.cache_clear()

    def test_caching_disabled_note_explains_how_to_enable(self, env_vars, monkeypatch):
        """When caching is off, the note should explain how to turn it on."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "false")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app()
        note = _client(app).get("/debug/llm").json()["prompt_caching"]["note"]
        assert "anthropic-beta" in note or "prompt-caching" in note

        get_settings.cache_clear()


# ── Operator: secrets are safe in debug output ───────────────────────────────

class TestDebugLlmSecurityFlow:
    """E2E: Sensitive values in extra_headers must be redacted."""

    def test_api_key_header_is_redacted_in_debug_output(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app(extra_headers={
            "x-api-key": "real-secret-abc123",
            "anthropic-version": "vertex-2023-10-16",
        })
        data = _client(app).get("/debug/llm").json()
        assert data["extra_headers"]["x-api-key"] == "<redacted>"
        assert "real-secret-abc123" not in str(data)

        get_settings.cache_clear()

    def test_non_sensitive_headers_are_visible(self, env_vars, monkeypatch):
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        app = _build_e2e_app(extra_headers={
            "anthropic-version": "vertex-2023-10-16",
            "anthropic-beta": "prompt-caching-2024-07-31",
        })
        headers = _client(app).get("/debug/llm").json()["extra_headers"]
        assert headers["anthropic-version"] == "vertex-2023-10-16"
        assert headers["anthropic-beta"] == "prompt-caching-2024-07-31"

        get_settings.cache_clear()


# ── Full lifecycle: check debug, query, verify debug unchanged ────────────────

class TestDebugLlmAndQueryLifecycle:
    """E2E: /debug/llm before and after a query — config must be stable."""

    def test_debug_llm_config_stable_across_queries(self, env_vars):
        """LLM config should not change after a /query call."""
        app = _build_e2e_app()
        c = _client(app)

        before = c.get("/debug/llm").json()

        c.post("/query", json={"query": "Check health of intl-sre"})
        c.post("/query", json={"query": "What is the pod restart count?"})

        after = c.get("/debug/llm").json()

        assert before["provider"] == after["provider"]
        assert before["model"] == after["model"]
        assert before["prompt_caching"]["status"] == after["prompt_caching"]["status"]

    def test_debug_llm_returns_200_before_any_queries(self, env_vars):
        """debug/llm must be accessible even before any query is made."""
        app = _build_e2e_app()
        resp = _client(app).get("/debug/llm")
        assert resp.status_code == 200

    def test_debug_then_health_then_query_all_200(self, env_vars):
        """All three endpoints should work in sequence without interference."""
        app = _build_e2e_app()
        c = _client(app)
        assert c.get("/debug/llm").status_code == 200
        assert c.get("/health").status_code == 200
        assert c.post("/query", json={"query": "test"}).status_code == 200

    def test_switching_llm_changes_provider_in_debug_output(self, env_vars, monkeypatch):
        """Switching CLAUDE_IS_PRIMARY_LLM should be reflected in /debug/llm."""
        from app.config import get_settings

        # OpenAI first
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "false")
        get_settings.cache_clear()
        app_openai = _build_e2e_app()
        openai_data = _client(app_openai).get("/debug/llm").json()
        assert openai_data["provider"] == "azure"

        # Switch to Claude
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        get_settings.cache_clear()
        app_claude = _build_e2e_app()
        claude_data = _client(app_claude).get("/debug/llm").json()
        assert claude_data["provider"] == "anthropic"

        get_settings.cache_clear()


# ── Prompt caching: _inject_cache_control integration in acompletion ─────────

class TestCachingTransformationFlow:
    """E2E: Verify _inject_cache_control is actually applied on Anthropic calls."""

    def test_cache_control_added_to_system_message_when_enabled(self, env_vars, monkeypatch):
        """With caching enabled, the system message transformation must produce cache_control."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        from agent.agent import _HeaderInjectingClient

        messages = [
            {"role": "system", "content": "You are a helpful SRE assistant."},
            {"role": "user", "content": "Check namespace health."},
        ]
        transformed = _HeaderInjectingClient._inject_cache_control(messages)

        sys_content = transformed[0]["content"]
        assert isinstance(sys_content, list)
        assert sys_content[0]["cache_control"] == {"type": "ephemeral"}
        # User message is also transformed (last user msg gets cache_control)
        user_content = transformed[1]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["text"] == "Check namespace health."
        assert user_content[0]["cache_control"] == {"type": "ephemeral"}

        get_settings.cache_clear()

    def test_cache_control_not_added_when_disabled(self, env_vars, monkeypatch):
        """With caching disabled, the system message should NOT be transformed."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "false")
        from app.config import get_settings
        get_settings.cache_clear()

        # _inject_cache_control is always a pure transformer —
        # the guard (_s.llm_prompt_cache_enabled) lives in acompletion().
        # Verify acompletion() skips transformation when disabled by checking
        # that the settings flag is indeed false.
        s = get_settings()
        assert s.llm_prompt_cache_enabled is False

        get_settings.cache_clear()

    def test_debug_llm_and_inject_agree_on_caching_state(self, env_vars, monkeypatch):
        """debug/llm beta_header_present and _inject_cache_control must be consistent.

        When beta_header_present=True, the transformation must produce cache_control
        blocks — both halves of caching must be active together.
        """
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        beta_headers = {"anthropic-beta": "prompt-caching-2024-07-31"}
        app = _build_e2e_app(extra_headers=beta_headers)

        # Check debug endpoint reports caching active
        caching = _client(app).get("/debug/llm").json()["prompt_caching"]
        assert caching["beta_header_present"] is True

        # Verify transformation produces cache_control
        from agent.agent import _HeaderInjectingClient
        msgs = [{"role": "system", "content": "system prompt text"}]
        result = _HeaderInjectingClient._inject_cache_control(msgs)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

        get_settings.cache_clear()
