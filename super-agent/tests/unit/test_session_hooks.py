"""
Unit tests for src/app/hooks/session_hooks.py — trim_session_history callback.

These tests verify the in-memory session-event trimming logic without requiring
a live ADK runtime, Redis connection, or Google GenAI credentials.

The module-level constant ``_MAX_HISTORY_TURNS`` is patched via monkeypatch so
every test is hermetically isolated from the process environment.
"""

import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Path setup — make the src package importable when running from the repo root.
# ---------------------------------------------------------------------------
sys.path.insert(0, "/Users/m0c00jt/git/health-agent/src")

# ---------------------------------------------------------------------------
# Stub out heavy Google ADK / GenAI imports ONLY when the real packages are
# not installed.  When google.adk IS present (e.g. local dev venv) we must
# not touch sys.modules — doing so corrupts google.adk for every other test
# collected in the same pytest session.
# ---------------------------------------------------------------------------

def _ensure_stub(dotted_name: str):
    """Create an empty stub module (and all parent packages) if not present."""
    parts = dotted_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
            if depth > 1:
                parent_name = ".".join(parts[: depth - 1])
                setattr(sys.modules[parent_name], parts[depth - 1], mod)


try:
    import google.adk  # noqa: F401
    # Real google.adk is available — no stubbing required.
    # session_hooks will import the real types; tests work via duck-typing
    # because all test helpers pass MagicMock objects, not real ADK instances.
except ImportError:
    # google.adk is absent — create lightweight stubs so the module under
    # test can be imported without the full Google ADK installation.
    for _stub in (
        "google",
        "google.adk",
        "google.adk.agents",
        "google.adk.agents.callback_context",
        "google.genai",
        "google.genai.types",
    ):
        _ensure_stub(_stub)

    # Provide the specific names the module imports.
    sys.modules["google.adk.agents.callback_context"].CallbackContext = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.genai.types"].Content = MagicMock  # type: ignore[attr-defined]

# Now we can safely import the module under test.
import app.hooks.session_hooks as session_hooks
from app.hooks.session_hooks import trim_session_history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(role: str) -> MagicMock:
    """Return a MagicMock ADK event whose ``content.role`` is *role*.

    The function mirrors the attribute chain that ``trim_session_history``
    inspects: ``event.content.role``.
    """
    event = MagicMock()
    event.content = MagicMock()
    event.content.role = role
    return event


def make_callback_context(events: list) -> MagicMock:
    """Return a MagicMock ``CallbackContext`` backed by the supplied *events* list.

    The returned object satisfies the attribute chain::

        callback_context._invocation_context.session.events

    Note: the source code accesses ``_invocation_context`` (with leading
    underscore) as the ADK 1.3.0 internal attribute name.  The ``events``
    list is assigned by reference, so mutations performed by
    ``trim_session_history`` are reflected in the original list — allowing
    assertions to check the final state.
    """
    ctx = MagicMock()
    ctx._invocation_context.session.events = events
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrimSessionHistoryEmptyEvents:
    """Behaviour when the session has no prior events."""

    def test_empty_events_returns_none(self, monkeypatch):
        """trim_session_history must return None when the events list is empty.

        An empty events list means this is a brand-new session.  The function
        should short-circuit with None and perform no further work.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 2)

        events = []
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert events == [], "events list must remain empty — nothing to trim"


class TestTrimSessionHistoryZeroTurns:
    """Behaviour when LLM_HISTORY_TURNS is 0 (fresh context per query)."""

    def test_zero_turns_clears_all_events(self, monkeypatch):
        """When _MAX_HISTORY_TURNS == 0 all prior history is removed except the current user message.

        ADK 1.3.0 appends the new user message to session.events BEFORE
        before_agent_callback fires, so the last event is the current user
        turn and must be preserved.  All preceding events are discarded so
        the LLM only receives the current query.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 0)

        current_user = make_event("user")  # ADK 1.3.0: current query already appended
        events = [
            make_event("user"),
            make_event("model"),
            current_user,
        ]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 1, "all prior events must be cleared; only the current user message is kept"
        assert events[0] is current_user, "the preserved event must be the current user message (last event)"

    def test_zero_turns_with_no_events(self, monkeypatch):
        """When _MAX_HISTORY_TURNS == 0 and the list is already empty, return None.

        The early-return guard for an empty list fires *before* the zero-turns
        branch, so ``events.clear()`` must never be called on an empty list
        (though it would be a no-op either way).
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 0)

        events = []
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert events == []


class TestTrimSessionHistoryOneTurn:
    """Behaviour when _MAX_HISTORY_TURNS == 1."""

    def test_one_turn_keeps_last_turn(self, monkeypatch):
        """With _MAX_HISTORY_TURNS=1 only events from the final user turn survive.

        Layout used in this test::

            index  role
            0      user   ← turn 0 start  (must be trimmed)
            1      model
            2      user   ← turn 1 start  (must be trimmed)
            3      model
            4      user   ← turn 2 start  (kept — last 1 turn)
            5      model

        After trimming, only indices 4 and 5 (turn 2) should remain.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 1)

        turn0_user  = make_event("user")
        turn0_model = make_event("model")
        turn1_user  = make_event("user")
        turn1_model = make_event("model")
        turn2_user  = make_event("user")
        turn2_model = make_event("model")

        events = [turn0_user, turn0_model, turn1_user, turn1_model, turn2_user, turn2_model]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 2, f"expected 2 events (turn 2 only), got {len(events)}"
        assert events[0] is turn2_user
        assert events[1] is turn2_model


class TestTrimSessionHistoryTwoTurns:
    """Behaviour when _MAX_HISTORY_TURNS == 2."""

    def test_two_turns_keeps_last_two(self, monkeypatch):
        """With _MAX_HISTORY_TURNS=2 the last two user turns and their responses survive.

        Layout::

            index  role
            0      user   ← turn 0 (trimmed)
            1      model
            2      user   ← turn 1 (kept)
            3      model
            4      user   ← turn 2 (kept)
            5      model

        After trimming events at indices 0 and 1 are removed; 2–5 remain.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 2)

        turn0_user  = make_event("user")
        turn0_model = make_event("model")
        turn1_user  = make_event("user")
        turn1_model = make_event("model")
        turn2_user  = make_event("user")
        turn2_model = make_event("model")

        events = [turn0_user, turn0_model, turn1_user, turn1_model, turn2_user, turn2_model]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 4, f"expected 4 events (turns 1 and 2), got {len(events)}"
        assert events[0] is turn1_user
        assert events[1] is turn1_model
        assert events[2] is turn2_user
        assert events[3] is turn2_model


class TestTrimSessionHistoryNoTrimNeeded:
    """Behaviour when the history already fits within the configured limit."""

    def test_fewer_turns_than_max_no_trim(self, monkeypatch):
        """No trimming when the number of user turns is below _MAX_HISTORY_TURNS.

        With _MAX_HISTORY_TURNS=2 but only 1 user turn present the condition
        ``len(turn_starts) > _MAX_HISTORY_TURNS`` is False — all events stay.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 2)

        user_event  = make_event("user")
        model_event = make_event("model")

        events = [user_event, model_event]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 2, "events must not be trimmed when under the turn limit"
        assert events[0] is user_event
        assert events[1] is model_event

    def test_exactly_max_turns_no_trim(self, monkeypatch):
        """No trimming when the number of user turns equals _MAX_HISTORY_TURNS exactly.

        With _MAX_HISTORY_TURNS=2 and exactly 2 user turns the trim condition
        ``len(turn_starts) > _MAX_HISTORY_TURNS`` evaluates to False.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 2)

        turn0_user  = make_event("user")
        turn0_model = make_event("model")
        turn1_user  = make_event("user")
        turn1_model = make_event("model")

        events = [turn0_user, turn0_model, turn1_user, turn1_model]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 4, "no events must be removed when turns == _MAX_HISTORY_TURNS"
        assert events[0] is turn0_user
        assert events[3] is turn1_model


class TestTrimSessionHistoryReturnValue:
    """trim_session_history must always return None to avoid short-circuiting ADK."""

    def test_always_returns_none(self, monkeypatch):
        """Verify that None is returned across a representative range of inputs.

        ADK interprets a non-None return value as a response override that
        short-circuits normal agent execution.  The hook must never do that.
        """
        scenarios = [
            # (description, _MAX_HISTORY_TURNS, events)
            ("empty events",        2, []),
            ("zero turns 3 events", 0, [make_event("user"), make_event("model"), make_event("user")]),
            ("trim needed",         1, [make_event("user"), make_event("model"), make_event("user"), make_event("model")]),
            ("no trim needed",      5, [make_event("user"), make_event("model")]),
        ]

        for description, max_turns, events in scenarios:
            monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", max_turns)
            ctx = make_callback_context(events)
            result = trim_session_history(ctx)
            assert result is None, (
                f"expected None for scenario '{description}', got {result!r}"
            )


class TestTrimSessionHistoryExceptionHandling:
    """Resilience: a bad context must never propagate an exception."""

    def test_exception_does_not_raise(self, monkeypatch):
        """trim_session_history swallows all exceptions and returns None.

        If the callback_context is malformed (e.g., ``invocation_context`` is
        absent), the function must log a warning and return None rather than
        propagating the AttributeError and blocking the user's query.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 2)

        bad_ctx = MagicMock(spec=[])  # spec=[] → no attributes allowed → AttributeError on access

        result = trim_session_history(bad_ctx)

        assert result is None, "must return None even when an exception is raised internally"


class TestTrimSessionHistoryMixedRoles:
    """Turn detection must use only user-role events as turn boundaries."""

    def test_events_with_mixed_roles(self, monkeypatch):
        """Only 'user' role events mark turn starts; 'model' and 'tool' are not boundaries.

        Layout with _MAX_HISTORY_TURNS=1::

            index  role
            0      user   ← turn 0 boundary (trimmed)
            1      model
            2      tool
            3      model
            4      user   ← turn 1 boundary (kept — last 1 turn)
            5      tool
            6      model

        ``turn_starts`` should be [0, 4], so ``keep_from = 4`` and events 0–3
        are removed, leaving events at original indices 4, 5, 6.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 1)

        e0_user  = make_event("user")
        e1_model = make_event("model")
        e2_tool  = make_event("tool")
        e3_model = make_event("model")
        e4_user  = make_event("user")
        e5_tool  = make_event("tool")
        e6_model = make_event("model")

        events = [e0_user, e1_model, e2_tool, e3_model, e4_user, e5_tool, e6_model]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 3, (
            f"expected 3 events from the last user turn only, got {len(events)}"
        )
        assert events[0] is e4_user,  "first remaining event must be the last user-turn start"
        assert events[1] is e5_tool,  "second remaining event must be the tool response"
        assert events[2] is e6_model, "third remaining event must be the model response"

    def test_no_user_events_no_trim(self, monkeypatch):
        """When no events have role 'user', turn_starts is empty and nothing is trimmed.

        This is an edge case where only model/tool events exist in the history.
        The condition ``len(turn_starts) > _MAX_HISTORY_TURNS`` is False (0 > N
        is always False for non-negative N), so all events are preserved.
        """
        monkeypatch.setattr(session_hooks, "_MAX_HISTORY_TURNS", 1)

        e0_model = make_event("model")
        e1_tool  = make_event("tool")

        events = [e0_model, e1_tool]
        ctx = make_callback_context(events)

        result = trim_session_history(ctx)

        assert result is None
        assert len(events) == 2, "events without user role must not be trimmed"
        assert events[0] is e0_model
        assert events[1] is e1_tool


# ---------------------------------------------------------------------------
# Tests: _save_args_to_state (lines 189, 194, 196)
# ---------------------------------------------------------------------------

class TestSaveArgsToState:
    """Tests for _save_args_to_state — state persistence and context summary."""

    def _make_tool_context(self):
        """Return a MagicMock ToolContext with a real dict for state."""
        tc = MagicMock()
        tc.state = {}
        return tc

    def _invoke(self, args: dict, tool_name: str = "some_tool"):
        from app.hooks.session_hooks import _save_args_to_state
        tc = self._make_tool_context()
        _save_args_to_state(args, tc, tool_name)
        return tc

    def test_skip_tool_returns_early_without_state_changes(self):
        """Tools in _STATE_SAVE_SKIP_TOOLS must return immediately — line 189."""
        from app.hooks.session_hooks import _save_args_to_state
        tc = self._make_tool_context()
        _save_args_to_state({"name": "my_prompt"}, tc, "get_mcp_prompt")
        # state must remain empty because the function returned early
        assert tc.state == {}

    def test_non_scalar_value_is_skipped(self):
        """List/dict values must hit the `continue` on line 194 and be excluded."""
        tc = self._invoke({"ns": "intl-sre", "checks": ["cpu", "mem"]})
        # "ns" is a string → persisted; "checks" is a list → skipped
        assert tc.state.get("ns") == "intl-sre"
        assert "checks" not in tc.state

    def test_empty_string_value_is_skipped(self):
        """Empty string values must hit the `continue` on line 196 and be excluded."""
        tc = self._invoke({"ns": "intl-sre", "app": ""})
        assert tc.state.get("ns") == "intl-sre"
        assert "app" not in tc.state

    def test_scalar_values_persisted_to_state(self):
        """Scalar str/int/float/bool args are all written to state."""
        tc = self._invoke({
            "ns": "intl-sre",
            "count": 3,
            "ratio": 0.95,
            "enabled": True,
        })
        assert tc.state["ns"] == "intl-sre"
        assert tc.state["count"] == 3
        assert tc.state["ratio"] == 0.95
        assert tc.state["enabled"] is True

    def test_active_context_set_with_summary(self):
        """active_context must be set when scalar args are present."""
        tc = self._invoke({"ns": "intl-sre", "app": "checkout"}, "some_tool")
        assert "active_context" in tc.state
        assert "some_tool" in tc.state["active_context"]

    def test_active_context_not_set_when_all_args_excluded(self):
        """active_context must NOT be set when all args are non-scalar or empty."""
        tc = self._invoke({"checks": ["cpu"], "app": ""})
        assert "active_context" not in tc.state

    def test_summary_exclude_keys_not_in_active_context(self):
        """Keys in _SUMMARY_EXCLUDE are persisted to state but omitted from active_context."""
        from app.hooks import session_hooks
        excluded_key = next(iter(session_hooks._SUMMARY_EXCLUDE))
        tc = self._invoke({"ns": "intl-sre", excluded_key: "some_value"}, "check_tool")
        # excluded key persisted to state
        assert tc.state.get(excluded_key) == "some_value"
        # but not mentioned in active_context
        assert excluded_key not in tc.state.get("active_context", "")
        # the non-excluded key IS in active_context
        assert "ns=intl-sre" in tc.state.get("active_context", "")


# ---------------------------------------------------------------------------
# Tests: on_tool_error_handler
# ---------------------------------------------------------------------------

from app.hooks.session_hooks import on_tool_error_handler, _classify_error, _ERROR_MSG_MAX_LEN


def _make_tool(name: str = "wcnp_check_app_health") -> MagicMock:
    """Return a MagicMock BaseTool with the given name."""
    tool = MagicMock()
    tool.name = name
    return tool


def _make_tool_context() -> MagicMock:
    """Return a MagicMock ToolContext."""
    return MagicMock()


class TestOnToolErrorHandlerBasic:
    """Core behavior: returns a structured dict so the LLM can degrade gracefully."""

    def test_returns_dict_on_connection_error(self):
        """ConnectionError should produce a graceful error response, not crash."""
        result = on_tool_error_handler(
            _make_tool(), {"namespace": "intl-sre"}, _make_tool_context(),
            ConnectionError("Connection refused"),
        )
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_type"] == "connection_error"
        assert result["tool_name"] == "wcnp_check_app_health"
        assert "Connection refused" in result["message"]

    def test_returns_dict_on_timeout_error(self):
        """TimeoutError should produce a graceful error response."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            TimeoutError("Read timed out after 30s"),
        )
        assert result["status"] == "error"
        assert result["error_type"] == "timeout"
        assert "timed out" in result["message"]

    def test_returns_dict_on_os_error(self):
        """OSError (network-level) should map to 'network_error'."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            OSError("Network is unreachable"),
        )
        assert result["error_type"] == "network_error"

    def test_returns_dict_on_generic_exception(self):
        """Unknown exception types fall back to class name as error_type."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ValueError("unexpected json"),
        )
        assert result["error_type"] == "ValueError"
        assert "unexpected json" in result["message"]

    def test_returns_dict_on_runtime_error(self):
        """RuntimeError is also handled gracefully."""
        result = on_tool_error_handler(
            _make_tool("fetch_incidents"), {}, _make_tool_context(),
            RuntimeError("MCP server returned 502"),
        )
        assert result["status"] == "error"
        assert result["tool_name"] == "fetch_incidents"

    def test_never_returns_none(self):
        """The handler must ALWAYS return a dict — None would re-raise the exception."""
        errors = [
            ConnectionError("refused"),
            TimeoutError("timed out"),
            OSError("unreachable"),
            ValueError("bad json"),
            RuntimeError("internal"),
            Exception("generic"),
        ]
        for err in errors:
            result = on_tool_error_handler(
                _make_tool(), {}, _make_tool_context(), err,
            )
            assert result is not None, f"returned None for {type(err).__name__}"
            assert isinstance(result, dict), f"returned non-dict for {type(err).__name__}"


class TestOnToolErrorHandlerEdgeCases:
    """Edge cases: None tool name, None args, long messages, empty messages."""

    def test_tool_name_is_none(self):
        """When tool.name is None, fall back to 'unknown_tool'."""
        tool = MagicMock()
        tool.name = None
        result = on_tool_error_handler(
            tool, {}, _make_tool_context(), ConnectionError("down"),
        )
        assert result["tool_name"] == "unknown_tool"
        assert "unknown_tool" in result["message"]

    def test_tool_name_is_empty_string(self):
        """When tool.name is '', fall back to 'unknown_tool' (falsy check)."""
        tool = MagicMock()
        tool.name = ""
        result = on_tool_error_handler(
            tool, {}, _make_tool_context(), ConnectionError("down"),
        )
        assert result["tool_name"] == "unknown_tool"

    def test_tool_has_no_name_attribute(self):
        """When tool has no 'name' attribute at all, getattr default kicks in."""
        tool = MagicMock(spec=[])  # spec=[] → no attributes
        result = on_tool_error_handler(
            tool, {}, _make_tool_context(), ConnectionError("down"),
        )
        assert result["tool_name"] == "unknown_tool"

    def test_args_is_none(self):
        """When args is None, it should be normalised to {} without crashing."""
        result = on_tool_error_handler(
            _make_tool(), None, _make_tool_context(), ConnectionError("down"),
        )
        assert result["status"] == "error"

    def test_args_is_not_a_dict(self):
        """When args is a non-dict type, normalise to {}."""
        result = on_tool_error_handler(
            _make_tool(), "bad_args", _make_tool_context(), ConnectionError("down"),
        )
        assert result["status"] == "error"

    def test_error_message_truncated_when_very_long(self):
        """Error messages longer than _ERROR_MSG_MAX_LEN must be truncated."""
        long_msg = "x" * 2000
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            RuntimeError(long_msg),
        )
        # The truncated message ends with "…" and is bounded
        assert len(result["message"]) < 2000
        assert "…" in result["message"]

    def test_error_message_at_exactly_max_len_not_truncated(self):
        """Error message exactly at _ERROR_MSG_MAX_LEN should NOT be truncated."""
        exact_msg = "y" * _ERROR_MSG_MAX_LEN
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            RuntimeError(exact_msg),
        )
        assert "…" not in result["message"]

    def test_empty_error_message_uses_class_name(self):
        """When str(error) is empty, use the exception class name instead."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ValueError(""),
        )
        assert "ValueError" in result["message"]

    def test_whitespace_only_error_message_uses_class_name(self):
        """When str(error) is only whitespace, fall back to class name."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            RuntimeError("   "),
        )
        assert "RuntimeError" in result["message"]

    def test_tool_context_is_none(self):
        """Handler should work even if tool_context is None (defensive)."""
        result = on_tool_error_handler(
            _make_tool(), {}, None, ConnectionError("down"),
        )
        assert result["status"] == "error"


class TestOnToolErrorHandlerConnectionSubclasses:
    """ConnectionError subclasses should map to 'connection_error' via isinstance."""

    def test_connection_refused_error(self):
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ConnectionRefusedError("refused"),
        )
        assert result["error_type"] == "connection_error"

    def test_connection_reset_error(self):
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ConnectionResetError("reset by peer"),
        )
        assert result["error_type"] == "connection_error"

    def test_connection_aborted_error(self):
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ConnectionAbortedError("aborted"),
        )
        assert result["error_type"] == "connection_error"

    def test_broken_pipe_error(self):
        """BrokenPipeError is a subclass of ConnectionError."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            BrokenPipeError("broken pipe"),
        )
        assert result["error_type"] == "connection_error"


class TestOnToolErrorHandlerInternalFailure:
    """Negative case: the handler itself crashes — must still return a dict."""

    def test_handler_internal_failure_returns_fallback_dict(self, monkeypatch):
        """If _classify_error raises, the outer try/except catches it."""
        def _boom(error):
            raise RuntimeError("classify crashed")
        monkeypatch.setattr(session_hooks, "_classify_error", _boom)

        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ConnectionError("original"),
        )
        # Must get the fallback dict, not None, not an exception
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_type"] == "handler_internal_error"
        assert result["tool_name"] == "unknown"

    def test_handler_with_completely_broken_tool_object(self, monkeypatch):
        """If the tool object itself raises on any attribute access."""
        class BrokenTool:
            @property
            def name(self):
                raise AttributeError("tool is broken")

        result = on_tool_error_handler(
            BrokenTool(), {}, _make_tool_context(),
            ConnectionError("down"),
        )
        # getattr(tool, "name", None) should catch AttributeError → None → "unknown_tool"
        assert isinstance(result, dict)
        assert result["status"] == "error"


class TestOnToolErrorHandlerResponseStructure:
    """Verify the response dict has the exact keys the LLM needs."""

    def test_response_has_required_keys(self):
        result = on_tool_error_handler(
            _make_tool("my_tool"), {"ns": "prod"}, _make_tool_context(),
            ConnectionError("refused"),
        )
        assert set(result.keys()) == {"status", "error_type", "tool_name", "message"}

    def test_message_contains_tool_name(self):
        """LLM should see which tool failed in the message."""
        result = on_tool_error_handler(
            _make_tool("wcnp_chart"), {}, _make_tool_context(),
            TimeoutError("30s"),
        )
        assert "wcnp_chart" in result["message"]

    def test_message_contains_error_type(self):
        """LLM should see the error classification in the message."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ConnectionError("refused"),
        )
        assert "connection_error" in result["message"]

    def test_message_contains_retry_guidance(self):
        """LLM should get guidance on what to do next."""
        result = on_tool_error_handler(
            _make_tool(), {}, _make_tool_context(),
            ConnectionError("refused"),
        )
        assert "retry" in result["message"].lower() or "try again" in result["message"].lower()


class TestClassifyError:
    """Unit tests for _classify_error helper."""

    def test_connection_error(self):
        assert _classify_error(ConnectionError("x")) == "connection_error"

    def test_timeout_error(self):
        assert _classify_error(TimeoutError("x")) == "timeout"

    def test_os_error(self):
        assert _classify_error(OSError("x")) == "network_error"

    def test_value_error(self):
        assert _classify_error(ValueError("x")) == "ValueError"

    def test_custom_exception(self):
        class McpServerDown(Exception):
            pass
        assert _classify_error(McpServerDown("x")) == "McpServerDown"

    def test_connection_refused_is_connection_error(self):
        """ConnectionRefusedError is a subclass — isinstance check catches it."""
        assert _classify_error(ConnectionRefusedError("x")) == "connection_error"

    def test_file_not_found_is_os_error(self):
        """FileNotFoundError → OSError subclass → 'network_error'."""
        # Note: OSError mapping is intentionally broad; FileNotFoundError
        # is unlikely in MCP context but the classifier handles it.
        assert _classify_error(FileNotFoundError("x")) == "network_error"
