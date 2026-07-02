"""Unit tests for the debug router and prompt-caching logic.

Covers:
  - _parse_tool_calls()         — helper that pairs function_call / function_response events
  - _HeaderInjectingClient._inject_cache_control() — system-prompt cache_control injection
  - _HeaderInjectingClient._log_caching_status()   — per-call caching diagnostics
  - GET /debug/llm              — LLM config + caching status endpoint
"""

import logging
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch as _patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub google.adk / google.genai when the real packages are absent.
try:
    import google.adk
except ImportError:
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.adk", ModuleType("google.adk"))

# Always ensure every ADK submodule used by agent.agent and session_hooks is
# present in sys.modules.  setdefault leaves real installed packages untouched
# while providing stubs in environments where the package is absent or partially
# replaced (e.g. when another test file already installed a stub).
for _mod_name in (
    "google.adk.runners",
    "google.adk.agents",
    "google.adk.agents.callback_context",
    "google.adk.tools",
    "google.adk.tools.base_tool",
    "google.adk.tools.tool_context",
    "google.adk.tools.mcp_tool",
    "google.adk.tools.mcp_tool.mcp_toolset",
    "google.adk.models",
    "google.adk.models.lite_llm",
    "google.adk.events",
    "google.adk.events.event",
    "google.adk.sessions",
    "google.adk.sessions.base_session_service",
    "google.adk.sessions.session",
    "google.adk.sessions.state",
):
    sys.modules.setdefault(_mod_name, MagicMock())

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(claude_primary: bool = False, cache_enabled: bool = False,
                   cache_extended: bool = False):
    """Return a fresh Settings-like MagicMock with the given caching flags.

    Using a mock instead of env var + cache_clear avoids lru_cache contamination
    from other test files that run before this one in the full suite.
    """
    from app.config import Settings
    s = MagicMock(spec=Settings)
    s.claude_is_primary_llm = claude_primary
    s.llm_prompt_cache_enabled = cache_enabled
    s.llm_prompt_cache_extended = cache_extended
    s.claude_model = "claude-test"
    s.openai_model = "gpt-4-test"
    s.claude_gateway_url = "https://claude.test.com/messages"
    s.element_gateway_base_url = "https://llm.test.com/openai"
    s.active_llm = "claude" if claude_primary else "openai"
    return s


def _make_debug_app(extra_headers: dict | None = None, monkeypatch=None,
                    claude_primary: bool = False, cache_enabled: bool = False,
                    cache_extended: bool = False) -> tuple:
    """Build a minimal FastAPI app wired with only the debug router.

    Returns (app, patch_context) — the patch_context must be used as a context
    manager by the caller to keep the get_settings patch active during the request.

    Uses unittest.mock.patch on app.routers.debug.get_settings to avoid any
    lru_cache contamination from other test files.
    """
    from app.routers import debug

    mock_model = MagicMock()
    mock_model._additional_args = {"extra_headers": extra_headers or {}}
    mock_agent = MagicMock()
    mock_agent.model = mock_model
    mock_runner = MagicMock()
    mock_runner.agent = mock_agent

    app = FastAPI()
    app.include_router(debug.router)
    app.state.runner = mock_runner

    settings = _make_settings(claude_primary=claude_primary,
                               cache_enabled=cache_enabled,
                               cache_extended=cache_extended)
    ctx = _patch("app.routers.debug.get_settings", return_value=settings)
    return app, ctx


# ── _parse_tool_calls ──────────────────────────────────────────────────────────

class TestParseToolCalls:
    """Unit tests for the _parse_tool_calls helper."""

    def _invoke(self, events):
        from app.routers.debug import _parse_tool_calls
        return _parse_tool_calls(events)

    def test_empty_events_returns_empty_list(self):
        assert self._invoke([]) == []

    def test_single_call_without_response(self):
        events = [
            {"content": {"role": "model", "parts": [
                {"function_call": {"name": "check_health", "args": {"ns": "foo"}, "id": "c1"}}
            ]}, "timestamp": 1.0}
        ]
        calls = self._invoke(events)
        assert len(calls) == 1
        assert calls[0]["tool"] == "check_health"
        assert calls[0]["args"] == {"ns": "foo"}
        assert calls[0]["response"] is None
        assert calls[0]["ts_call"] == 1.0
        assert calls[0]["ts_response"] is None

    def test_matched_call_and_response(self):
        events = [
            {"content": {"role": "model", "parts": [
                {"function_call": {"name": "check_health", "args": {"ns": "foo"}, "id": "c1"}}
            ]}, "timestamp": 1.0},
            {"content": {"role": "tool", "parts": [
                {"function_response": {"name": "check_health", "response": {"status": "ok"}, "id": "c1"}}
            ]}, "timestamp": 2.0},
        ]
        calls = self._invoke(events)
        assert len(calls) == 1
        assert calls[0]["response"] == {"status": "ok"}
        assert calls[0]["ts_response"] == 2.0

    def test_multiple_tool_calls_in_one_turn(self):
        events = [
            {"content": {"role": "model", "parts": [
                {"function_call": {"name": "tool_a", "args": {}, "id": "a1"}},
                {"function_call": {"name": "tool_b", "args": {}, "id": "b1"}},
            ]}, "timestamp": 1.0},
            {"content": {"role": "tool", "parts": [
                {"function_response": {"name": "tool_a", "response": {"r": 1}, "id": "a1"}},
                {"function_response": {"name": "tool_b", "response": {"r": 2}, "id": "b1"}},
            ]}, "timestamp": 2.0},
        ]
        calls = self._invoke(events)
        assert len(calls) == 2
        names = {c["tool"] for c in calls}
        assert names == {"tool_a", "tool_b"}

    def test_turn_counter_increments_on_user_messages(self):
        events = [
            {"content": {"role": "user", "parts": [{"text": "first"}]}, "timestamp": 0.5},
            {"content": {"role": "model", "parts": [
                {"function_call": {"name": "t1", "args": {}, "id": "i1"}}
            ]}, "timestamp": 1.0},
            {"content": {"role": "user", "parts": [{"text": "second"}]}, "timestamp": 1.5},
            {"content": {"role": "model", "parts": [
                {"function_call": {"name": "t2", "args": {}, "id": "i2"}}
            ]}, "timestamp": 2.0},
        ]
        calls = self._invoke(events)
        assert len(calls) == 2
        assert calls[0]["turn"] == 1
        assert calls[1]["turn"] == 2

    def test_orphan_response_without_call_is_included(self):
        """A function_response with no prior call should still appear in results."""
        events = [
            {"content": {"role": "tool", "parts": [
                {"function_response": {"name": "orphan_tool", "response": {"x": 1}, "id": "o1"}}
            ]}, "timestamp": 3.0},
        ]
        calls = self._invoke(events)
        assert len(calls) == 1
        assert calls[0]["tool"] == "orphan_tool"
        assert calls[0]["args"] is None

    def test_events_without_content_are_skipped(self):
        events = [{"timestamp": 1.0}, {"content": None, "timestamp": 2.0}]
        calls = self._invoke(events)
        assert calls == []

    def test_call_id_falls_back_to_name_when_id_absent(self):
        events = [
            {"content": {"role": "model", "parts": [
                {"function_call": {"name": "no_id_tool", "args": {}}}
            ]}, "timestamp": 1.0},
        ]
        calls = self._invoke(events)
        assert calls[0]["call_id"] == "no_id_tool"


# ── _inject_cache_control ─────────────────────────────────────────────────────

class TestInjectCacheControl:
    """Unit tests for _HeaderInjectingClient._inject_cache_control."""

    def _invoke(self, messages):
        # Import is deferred to avoid ADK module load issues at collection time
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient._inject_cache_control(messages)

    def test_plain_string_system_becomes_list_with_cache_control(self):
        msgs = [{"role": "system", "content": "You are helpful."}]
        result = self._invoke(msgs)
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "You are helpful."
        assert content[0]["cache_control"] == {"type": "ephemeral"}

    def test_empty_string_system_content_is_not_transformed(self):
        """Empty system content should be left as-is (nothing to cache)."""
        msgs = [{"role": "system", "content": ""}]
        result = self._invoke(msgs)
        assert result[0]["content"] == ""

    def test_list_system_content_gets_cache_control_on_last_block(self):
        msgs = [{"role": "system", "content": [
            {"type": "text", "text": "block one"},
            {"type": "text", "text": "block two"},
        ]}]
        result = self._invoke(msgs)
        content = result[0]["content"]
        assert content[-1]["cache_control"] == {"type": "ephemeral"}
        assert content[-1]["text"] == "block two"
        # First block untouched
        assert "cache_control" not in content[0]

    def test_list_system_already_has_cache_control_is_not_duplicated(self):
        msgs = [{"role": "system", "content": [
            {"type": "text", "text": "already cached", "cache_control": {"type": "ephemeral"}}
        ]}]
        result = self._invoke(msgs)
        content = result[0]["content"]
        # Should remain a single block, not grow
        assert len(content) == 1
        assert content[0]["cache_control"] == {"type": "ephemeral"}

    def test_non_system_messages_last_user_is_transformed(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result = self._invoke(msgs)
        # Last (and only) user message gets cache_control
        user_content = result[0]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["text"] == "hello"
        assert user_content[0]["cache_control"] == {"type": "ephemeral"}
        # Assistant message is untouched
        assert result[1]["content"] == "world"

    def test_mixed_messages_transforms_system_and_last_user(self):
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user message"},
        ]
        result = self._invoke(msgs)
        # system → transformed
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # last user → also transformed
        user_content = result[1]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["text"] == "user message"
        assert user_content[0]["cache_control"] == {"type": "ephemeral"}

    def test_original_messages_list_is_not_mutated(self):
        original = [{"role": "system", "content": "original text"}]
        import copy
        before = copy.deepcopy(original)
        self._invoke(original)
        assert original == before

    def test_empty_messages_list_returns_empty(self):
        assert self._invoke([]) == []

    def test_multiple_system_messages_all_transformed(self):
        msgs = [
            {"role": "system", "content": "part one"},
            {"role": "system", "content": "part two"},
        ]
        result = self._invoke(msgs)
        for msg in result:
            assert isinstance(msg["content"], list)
            assert msg["content"][0]["cache_control"] == {"type": "ephemeral"}


# ── _log_caching_status ───────────────────────────────────────────────────────

class TestLogCachingStatus:
    """Unit tests for _HeaderInjectingClient._log_caching_status logging."""

    def _client(self):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient()

    def _sys_msg(self, with_cache_control: bool = False) -> dict:
        block = {"type": "text", "text": "You are a helpful assistant."}
        if with_cache_control:
            block["cache_control"] = {"type": "ephemeral"}
        return {"role": "system", "content": [block]}

    def test_non_anthropic_model_does_not_log(self, caplog):
        c = self._client()
        with caplog.at_level(logging.DEBUG, logger="agent.agent"):
            c._log_caching_status("azure/gpt-4o", [], {})
        assert not any("caching" in r.message.lower() for r in caplog.records)

    def test_both_conditions_met_logs_info_active(self, caplog):
        c = self._client()
        messages = [self._sys_msg(with_cache_control=True)]
        kwargs = {"extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}}
        with caplog.at_level(logging.INFO, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        records = [r for r in caplog.records if "caching" in r.message.lower()]
        assert any("ACTIVE" in r.message for r in records)

    def test_beta_header_only_logs_warning(self, caplog):
        """Beta header present but no cache_control blocks → warning."""
        c = self._client()
        messages = [self._sys_msg(with_cache_control=False)]
        kwargs = {"extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}}
        with caplog.at_level(logging.WARNING, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no cache_control" in r.message.lower() for r in warnings)

    def test_cache_control_only_logs_warning(self, caplog):
        """cache_control blocks present but beta header missing → warning."""
        c = self._client()
        messages = [self._sys_msg(with_cache_control=True)]
        kwargs = {}
        with caplog.at_level(logging.WARNING, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("missing" in r.message.lower() for r in warnings)

    def test_neither_condition_logs_debug(self, caplog):
        c = self._client()
        messages = [self._sys_msg(with_cache_control=False)]
        kwargs = {}
        with caplog.at_level(logging.DEBUG, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("not active" in r.message.lower() for r in debug_records)

    def test_model_string_case_insensitive_for_anthropic_check(self, caplog):
        c = self._client()
        messages = [self._sys_msg(with_cache_control=False)]
        kwargs = {}
        with caplog.at_level(logging.DEBUG, logger="agent.agent"):
            c._log_caching_status("ANTHROPIC/claude-3-5-sonnet", messages, kwargs)
        # Should still have logged something (not silently skipped)
        assert any("caching" in r.message.lower() for r in caplog.records)

    def test_empty_messages_list_with_beta_header_warns(self, caplog):
        c = self._client()
        kwargs = {"extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}}
        with caplog.at_level(logging.WARNING, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", [], kwargs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no cache_control" in r.message.lower() for r in warnings)

    def test_extended_beta_header_with_cache_control_logs_active(self, caplog):
        """extended-cache-ttl header + cache_control blocks → ACTIVE (not just default header)."""
        c = self._client()
        messages = [self._sys_msg(with_cache_control=True)]
        kwargs = {"extra_headers": {"anthropic-beta": "extended-cache-ttl-2025-04-11"}}
        with caplog.at_level(logging.INFO, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        records = [r for r in caplog.records if "caching" in r.message.lower()]
        assert any("ACTIVE" in r.message for r in records)

    def test_extended_beta_header_without_cache_control_warns(self, caplog):
        """extended-cache-ttl header but no cache_control → warning (not silently ignored)."""
        c = self._client()
        messages = [self._sys_msg(with_cache_control=False)]
        kwargs = {"extra_headers": {"anthropic-beta": "extended-cache-ttl-2025-04-11"}}
        with caplog.at_level(logging.WARNING, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no cache_control" in r.message.lower() for r in warnings)

    def test_unknown_beta_header_value_does_not_log_active(self, caplog):
        """A made-up beta header value must not be treated as caching active."""
        c = self._client()
        messages = [self._sys_msg(with_cache_control=True)]
        kwargs = {"extra_headers": {"anthropic-beta": "some-future-feature-2099-01-01"}}
        with caplog.at_level(logging.DEBUG, logger="agent.agent"):
            c._log_caching_status("anthropic/claude-opus-4-6", messages, kwargs)
        records = [r for r in caplog.records if "caching" in r.message.lower()]
        assert not any("ACTIVE" in r.message for r in records)


# ── GET /debug/llm — endpoint tests ──────────────────────────────────────────

class TestDebugLlmEndpoint:
    """Unit tests for GET /debug/llm — shape, content, and caching status.

    All tests use _make_debug_app() which patches app.routers.debug.get_settings
    directly, avoiding any lru_cache contamination from other test files.
    """

    def _get(self, extra_headers=None, claude_primary=False,
             cache_enabled=False, cache_extended=False):
        """Build app, apply patch, make request, return response JSON."""
        app, ctx = _make_debug_app(extra_headers=extra_headers,
                                   claude_primary=claude_primary,
                                   cache_enabled=cache_enabled,
                                   cache_extended=cache_extended)
        with ctx:
            return TestClient(app).get("/debug/llm")

    def test_returns_200(self):
        assert self._get().status_code == 200

    def test_response_shape_contains_required_keys(self):
        data = self._get().json()
        for key in ("provider", "model", "api_base", "is_primary_llm", "extra_headers", "prompt_caching"):
            assert key in data, f"Missing key: {key}"

    def test_prompt_caching_shape(self):
        caching = self._get().json()["prompt_caching"]
        for key in ("beta_header_present", "beta_header_value", "status", "note"):
            assert key in caching, f"Missing prompt_caching key: {key}"

    # ── Provider = Azure / OpenAI ─────────────────────────────────────────────

    def test_openai_provider_shows_azure(self):
        data = self._get(claude_primary=False).json()
        assert data["provider"] == "azure"
        assert data["is_primary_llm"] is False

    def test_openai_model_string_contains_openai_model(self):
        data = self._get(claude_primary=False).json()
        assert "azure/" in data["model"]
        assert "gpt-4-test" in data["model"]

    def test_openai_caching_status_is_na(self):
        caching = self._get(claude_primary=False).json()["prompt_caching"]
        assert caching["status"] == "N/A"
        assert caching["beta_header_present"] is False

    # ── Provider = Anthropic / Claude ─────────────────────────────────────────

    def test_claude_provider_shows_anthropic(self):
        data = self._get(claude_primary=True).json()
        assert data["provider"] == "anthropic"
        assert data["is_primary_llm"] is True

    def test_claude_model_string_contains_claude_model(self):
        data = self._get(claude_primary=True).json()
        assert "anthropic/" in data["model"]
        assert "claude-test" in data["model"]

    def test_claude_without_caching_shows_disabled(self):
        extra = {"anthropic-version": "vertex-2023-10-16"}
        caching = self._get(extra_headers=extra, claude_primary=True,
                            cache_enabled=False).json()["prompt_caching"]
        assert caching["status"] == "DISABLED"
        assert caching["beta_header_present"] is False
        assert caching["beta_header_value"] is None

    def test_claude_with_caching_enabled_shows_header_present(self):
        extra = {
            "anthropic-version": "vertex-2023-10-16",
            "anthropic-beta": "prompt-caching-2024-07-31",
        }
        caching = self._get(extra_headers=extra, claude_primary=True,
                            cache_enabled=True).json()["prompt_caching"]
        assert caching["beta_header_present"] is True
        assert caching["beta_header_value"] == "prompt-caching-2024-07-31"
        assert "HEADER_PRESENT" in caching["status"]

    def test_caching_enabled_note_mentions_cache_control(self):
        extra = {"anthropic-beta": "prompt-caching-2024-07-31"}
        note = self._get(extra_headers=extra, claude_primary=True,
                         cache_enabled=True).json()["prompt_caching"]["note"]
        assert "cache_control" in note.lower() or "caching" in note.lower()

    def test_disabled_note_gives_enablement_instructions(self):
        note = self._get(claude_primary=True,
                         cache_enabled=False).json()["prompt_caching"]["note"]
        assert "anthropic-beta" in note or "prompt-caching" in note

    # ── Header redaction ──────────────────────────────────────────────────────

    def test_api_key_in_extra_headers_is_redacted(self):
        headers = self._get(extra_headers={"x-api-key": "super-secret-token-12345"}).json()["extra_headers"]
        assert headers["x-api-key"] == "<redacted>"

    def test_non_sensitive_header_is_not_redacted(self):
        headers = self._get(extra_headers={"anthropic-version": "vertex-2023-10-16"}).json()["extra_headers"]
        assert headers["anthropic-version"] == "vertex-2023-10-16"

    def test_multiple_sensitive_headers_all_redacted(self):
        extra = {
            "x-api-key": "key-val",
            "Authorization": "Bearer token-val",
            "anthropic-version": "vertex-2023-10-16",
        }
        headers = self._get(extra_headers=extra).json()["extra_headers"]
        assert headers["x-api-key"] == "<redacted>"
        assert headers["Authorization"] == "<redacted>"
        assert headers["anthropic-version"] == "vertex-2023-10-16"

    def test_no_extra_headers_returns_empty_dict(self):
        headers = self._get(extra_headers={}).json()["extra_headers"]
        assert headers == {}

    # ── Extended TTL (LLM_PROMPT_CACHE_EXTENDED=true) ─────────────────────────

    def test_extended_cache_beta_header_shows_header_present(self):
        """extended-cache-ttl-2025-04-11 must be recognised as a caching header."""
        extra = {"anthropic-beta": "extended-cache-ttl-2025-04-11"}
        caching = self._get(extra_headers=extra, claude_primary=True,
                            cache_enabled=True).json()["prompt_caching"]
        assert caching["beta_header_present"] is True
        assert caching["beta_header_value"] == "extended-cache-ttl-2025-04-11"
        assert "HEADER_PRESENT" in caching["status"]

    def test_extended_cache_beta_header_value_is_exact_string(self):
        extra = {"anthropic-beta": "extended-cache-ttl-2025-04-11"}
        data = self._get(extra_headers=extra, claude_primary=True, cache_enabled=True).json()
        assert data["prompt_caching"]["beta_header_value"] == "extended-cache-ttl-2025-04-11"

    def test_unknown_beta_header_shows_not_present(self):
        """A beta header that is not a caching header must not show beta_header_present=true."""
        extra = {"anthropic-beta": "some-other-feature-2099-01-01"}
        caching = self._get(extra_headers=extra, claude_primary=True,
                            cache_enabled=False).json()["prompt_caching"]
        assert caching["beta_header_present"] is False
        assert caching["status"] == "DISABLED"

    def test_model_without_additional_args_returns_empty_headers(self):
        """LiteLlm model without _additional_args should not crash the endpoint."""
        from app.routers import debug
        settings = _make_settings(claude_primary=False)

        mock_model = MagicMock(spec=[])  # no _additional_args attribute
        mock_agent = MagicMock()
        mock_agent.model = mock_model
        mock_runner = MagicMock()
        mock_runner.agent = mock_agent

        app = FastAPI()
        app.include_router(debug.router)
        app.state.runner = mock_runner

        with _patch("app.routers.debug.get_settings", return_value=settings):
            resp = TestClient(app).get("/debug/llm")
        assert resp.status_code == 200
        assert resp.json()["extra_headers"] == {}


# ── GET /debug/session/{session_id} — endpoint tests ─────────────────────────

import json as _json
from unittest.mock import AsyncMock as _AsyncMock


def _make_debug_session_app(
    session_raw=None,
    events_raw=None,
    ui_raw=None,
    app_state_raw=None,
    user_state_raw=None,
    redis_side_effect=None,
):
    """Build a minimal FastAPI app wired with only the debug router,
    with a mocked Redis that returns the given raw data.

    Returns (app, mock_redis).
    """
    from app.routers import debug

    mock_redis = MagicMock()

    if redis_side_effect is not None:
        mock_redis.get = _AsyncMock(side_effect=redis_side_effect)
        mock_redis.lrange = _AsyncMock(side_effect=redis_side_effect)
    else:
        # gather() calls: redis.get(session), redis.lrange(events), redis.lrange(ui),
        #                 redis.get(app_state), redis.get(user_state)
        # We use side_effect lists to return different values per call.
        get_returns = [session_raw, app_state_raw, user_state_raw]
        lrange_returns = [events_raw if events_raw is not None else [],
                          ui_raw if ui_raw is not None else []]

        get_iter = iter(get_returns)
        lrange_iter = iter(lrange_returns)

        async def _get(key):
            return next(get_iter, None)

        async def _lrange(key, start, end):
            return next(lrange_iter, [])

        mock_redis.get = _get
        mock_redis.lrange = _lrange

    mock_runner = MagicMock()
    mock_runner.session_service = MagicMock()
    mock_runner.session_service._redis = mock_redis

    app = FastAPI()
    app.include_router(debug.router)
    app.state.runner = mock_runner

    return app, mock_redis


class TestDebugSessionEndpoint:
    """Tests for GET /debug/session/{session_id} — lines 123-169."""

    def _make_session_doc(self, state=None, title="Test Session", last_update_time=1000.0):
        return _json.dumps({
            "state": state or {"ns": "intl-sre"},
            "title": title,
            "last_update_time": last_update_time,
        })

    def test_returns_404_when_session_not_found(self):
        """When session_raw is None, must return 404."""
        app, _ = _make_debug_session_app(session_raw=None)
        resp = TestClient(app).get("/debug/session/no-such-session")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_returns_200_for_existing_session(self):
        """When session exists, must return HTTP 200."""
        doc = self._make_session_doc()
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/my-session")
        assert resp.status_code == 200

    def test_response_contains_session_id(self):
        """Response must echo the session_id from the URL."""
        doc = self._make_session_doc()
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/abc-123")
        assert resp.json()["session_id"] == "abc-123"

    def test_response_contains_user_id(self):
        """Response must include the user_id query param."""
        doc = self._make_session_doc()
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/s?user_id=alice")
        assert resp.json()["user_id"] == "alice"

    def test_response_shape_has_required_keys(self):
        """Response must contain all required top-level keys."""
        doc = self._make_session_doc()
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/s")
        data = resp.json()
        for key in ("session_id", "user_id", "state", "event_count", "tool_calls",
                    "adk_events", "ui_events"):
            assert key in data, f"Missing key: {key}"

    def test_session_state_merged_from_doc(self):
        """State from the session doc must appear in the response state."""
        doc = self._make_session_doc(state={"ns": "my-namespace"})
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/s")
        assert resp.json()["state"]["ns"] == "my-namespace"

    def test_app_state_merged_with_prefix(self):
        """app-scoped state must appear with 'app:' prefix in merged state."""
        doc = self._make_session_doc(state={})
        app_state = _json.dumps({"version": "v2"})
        app, _ = _make_debug_session_app(session_raw=doc, app_state_raw=app_state)
        resp = TestClient(app).get("/debug/session/s")
        assert resp.json()["state"].get("app:version") == "v2"

    def test_user_state_merged_with_prefix(self):
        """user-scoped state must appear with 'user:' prefix in merged state."""
        doc = self._make_session_doc(state={})
        user_state = _json.dumps({"pref": "dark"})
        app, _ = _make_debug_session_app(session_raw=doc, user_state_raw=user_state)
        resp = TestClient(app).get("/debug/session/s")
        assert resp.json()["state"].get("user:pref") == "dark"

    def test_adk_events_returned_as_list(self):
        """adk_events must be a list matching the Redis lrange results."""
        doc = self._make_session_doc()
        evt = _json.dumps({"content": {"role": "user", "parts": []}, "timestamp": 1.0})
        app, _ = _make_debug_session_app(session_raw=doc, events_raw=[evt])
        resp = TestClient(app).get("/debug/session/s")
        adk = resp.json()["adk_events"]
        assert isinstance(adk, list)
        assert len(adk) == 1

    def test_ui_events_returned_as_list(self):
        """ui_events must be a list matching the Redis lrange results."""
        doc = self._make_session_doc()
        ui_evt = _json.dumps({"type": "user", "text": "hello", "ts": 1.0})
        app, _ = _make_debug_session_app(session_raw=doc, ui_raw=[ui_evt])
        resp = TestClient(app).get("/debug/session/s")
        ui = resp.json()["ui_events"]
        assert isinstance(ui, list)
        assert len(ui) == 1

    def test_redis_error_returns_503(self):
        """When Redis gather() raises, must return 503."""
        from app.routers import debug

        mock_redis = MagicMock()
        # Make get raise an exception to trigger the except block
        mock_redis.get = _AsyncMock(side_effect=RuntimeError("Redis down"))
        mock_redis.lrange = _AsyncMock(side_effect=RuntimeError("Redis down"))

        mock_runner = MagicMock()
        mock_runner.session_service = MagicMock()
        mock_runner.session_service._redis = mock_redis

        app = FastAPI()
        app.include_router(debug.router)
        app.state.runner = mock_runner

        resp = TestClient(app).get("/debug/session/s")
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"]

    def test_title_in_response(self):
        """The session title from the doc must appear in the response."""
        doc = self._make_session_doc(title="My Debug Session")
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/s")
        assert resp.json()["title"] == "My Debug Session"

    def test_last_update_time_in_response(self):
        """last_update_time from the doc must appear in the response."""
        doc = self._make_session_doc(last_update_time=9999.9)
        app, _ = _make_debug_session_app(session_raw=doc)
        resp = TestClient(app).get("/debug/session/s")
        assert resp.json()["last_update_time"] == pytest.approx(9999.9)

    def test_event_count_matches_adk_events_length(self):
        """event_count must equal the number of adk_events."""
        doc = self._make_session_doc()
        evt1 = _json.dumps({"content": {"role": "user", "parts": []}, "timestamp": 1.0})
        evt2 = _json.dumps({"content": {"role": "model", "parts": []}, "timestamp": 2.0})
        app, _ = _make_debug_session_app(session_raw=doc, events_raw=[evt1, evt2])
        resp = TestClient(app).get("/debug/session/s")
        data = resp.json()
        assert data["event_count"] == len(data["adk_events"])
