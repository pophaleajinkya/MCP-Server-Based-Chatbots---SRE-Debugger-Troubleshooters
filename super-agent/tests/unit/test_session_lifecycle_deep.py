"""Comprehensive tests for _stream_id_lt, trim_session_history, and
request_context event bridge lifecycle patterns.

Covers edge cases, boundary conditions, and concurrency scenarios.
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(role="user", text="hello", has_content=True):
    """Build a lightweight mock ADK Event."""
    if not has_content:
        return MagicMock(content=None)
    content = MagicMock()
    content.role = role
    content.parts = [MagicMock(text=text)]
    return MagicMock(content=content)


def _make_event_no_role(text="hello"):
    """Build a mock Event whose content exists but has no role attribute."""
    content = MagicMock(spec=[])  # empty spec means no attributes
    content.parts = [MagicMock(text=text)]
    # getattr(content, "role", None) will return None
    return MagicMock(content=content)


def _make_callback_context(events, state=None):
    """Build a mock CallbackContext wrapping the given events list."""
    ctx = MagicMock()
    session = MagicMock()
    session.events = events
    ctx._invocation_context.session = session
    ctx.state = state if state is not None else {}
    return ctx


# ============================================================================
# _stream_id_lt tests
# ============================================================================

class TestStreamIdLt:
    """Tests for app.hooks.session_hooks._stream_id_lt."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.hooks.session_hooks import _stream_id_lt
        self._fn = _stream_id_lt

    # 1. Different millis
    def test_different_millis_less(self):
        assert self._fn("100-0", "200-0") is True

    # 2. Same millis, different seq
    def test_same_millis_less_seq(self):
        assert self._fn("100-0", "100-1") is True

    # 3. Reverse order millis
    def test_reverse_millis(self):
        assert self._fn("200-0", "100-0") is False

    # 4. Reverse seq
    def test_reverse_seq(self):
        assert self._fn("100-1", "100-0") is False

    # 5. Equal IDs
    def test_equal_ids(self):
        assert self._fn("100-0", "100-0") is False

    # 6. Initial marker equal
    def test_initial_marker_equal(self):
        assert self._fn("0-0", "0-0") is False

    # 7. First vs any real ID
    def test_zero_vs_real(self):
        assert self._fn("0-0", "1-0") is True

    # 8. Zero millis different seq
    def test_zero_millis_diff_seq(self):
        assert self._fn("0-0", "0-1") is True

    # 9. Large numbers
    def test_large_numbers(self):
        assert self._fn("9999999999999-99", "9999999999999-100") is True

    # 10. Non-numeric millis
    def test_non_numeric_millis(self):
        assert self._fn("abc-0", "100-0") is False

    # 11. Non-numeric seq
    def test_non_numeric_seq(self):
        assert self._fn("100-abc", "100-0") is False

    # 12. Empty string left
    def test_empty_left(self):
        assert self._fn("", "100-0") is False

    # 13. Empty string right
    def test_empty_right(self):
        assert self._fn("100-0", "") is False

    # 14. String with dash but non-numeric parts
    def test_dash_non_numeric_parts(self):
        assert self._fn("no-dash", "100-0") is False

    # 15. No dash at all
    def test_no_dash(self):
        assert self._fn("100", "200-0") is False

    # 16. Empty millis (leading dash)
    def test_empty_millis_leading_dash(self):
        assert self._fn("-0", "100-0") is False

    # 17. Empty seq (trailing dash)
    def test_empty_seq_trailing_dash(self):
        assert self._fn("100-", "200-0") is False

    # 18. Extra dash segments
    def test_extra_dash_segments(self):
        # split("-", 1) gives ("100", "0-extra"), int("0-extra") fails
        assert self._fn("100-0-extra", "200-0") is False

    # 19. None inputs
    def test_none_left(self):
        assert self._fn(None, "100-0") is False

    def test_none_right(self):
        assert self._fn("100-0", None) is False

    def test_both_none(self):
        assert self._fn(None, None) is False


# ============================================================================
# trim_session_history tests
# ============================================================================

class TestTrimSessionHistory:
    """Tests for app.hooks.session_hooks.trim_session_history."""

    # 20. Empty events list
    def test_empty_events_returns_none(self):
        from app.hooks.session_hooks import trim_session_history
        ctx = _make_callback_context([])
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            result = trim_session_history(ctx)
        assert result is None

    # 21. Events is None
    def test_none_events_returns_none(self):
        from app.hooks.session_hooks import trim_session_history
        ctx = _make_callback_context(None)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            result = trim_session_history(ctx)
        assert result is None

    # 22. MAX=0, single event preserved
    def test_max0_single_event_preserved(self):
        from app.hooks.session_hooks import trim_session_history
        events = [_make_event("user", "q1")]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 0):
            result = trim_session_history(ctx)
        assert result is None
        assert len(events) == 1

    # 23. MAX=0, multiple events, all but last deleted
    def test_max0_multiple_events_keeps_last(self):
        from app.hooks.session_hooks import trim_session_history
        last = _make_event("user", "latest")
        events = [_make_event("user", "old1"), _make_event("model", "resp"), last]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 0):
            trim_session_history(ctx)
        assert len(events) == 1
        assert events[0] is last

    # 24. MAX=0, 100 events, only last preserved
    def test_max0_100_events_keeps_last(self):
        from app.hooks.session_hooks import trim_session_history
        events = [_make_event("user", f"q{i}") for i in range(100)]
        last = events[-1]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 0):
            trim_session_history(ctx)
        assert len(events) == 1
        assert events[0] is last

    # 25. MAX=1, 1 user turn, nothing trimmed
    def test_max1_single_turn_no_trim(self):
        from app.hooks.session_hooks import trim_session_history
        events = [_make_event("user", "q1"), _make_event("model", "a1")]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 2

    # 26. MAX=1, 2 user turns, first removed
    def test_max1_two_turns_first_removed(self):
        from app.hooks.session_hooks import trim_session_history
        e1 = _make_event("user", "q1")
        e2 = _make_event("model", "a1")
        e3 = _make_event("user", "q2")
        e4 = _make_event("model", "a2")
        events = [e1, e2, e3, e4]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 2
        assert events[0] is e3
        assert events[1] is e4

    # 27. MAX=1, 5 user turns, only last kept
    def test_max1_five_turns_keeps_last(self):
        from app.hooks.session_hooks import trim_session_history
        events = []
        for i in range(5):
            events.append(_make_event("user", f"q{i}"))
            events.append(_make_event("model", f"a{i}"))
        last_user = events[-2]
        last_model = events[-1]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 2
        assert events[0] is last_user
        assert events[1] is last_model

    # 28. MAX=3, exactly 3 turns, nothing trimmed
    def test_max3_exact_no_trim(self):
        from app.hooks.session_hooks import trim_session_history
        events = []
        for i in range(3):
            events.append(_make_event("user", f"q{i}"))
            events.append(_make_event("model", f"a{i}"))
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            trim_session_history(ctx)
        assert len(events) == 6

    # 29. MAX=3, 4 turns, first removed
    def test_max3_four_turns_first_removed(self):
        from app.hooks.session_hooks import trim_session_history
        events = []
        for i in range(4):
            events.append(_make_event("user", f"q{i}"))
            events.append(_make_event("model", f"a{i}"))
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            trim_session_history(ctx)
        # First turn (2 events) removed, 6 remain
        assert len(events) == 6

    # 30. MAX=3, 10 turns, 7 turns removed
    def test_max3_ten_turns_seven_removed(self):
        from app.hooks.session_hooks import trim_session_history
        events = []
        for i in range(10):
            events.append(_make_event("user", f"q{i}"))
            events.append(_make_event("model", f"a{i}"))
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            trim_session_history(ctx)
        # 7 user turns removed = 14 events removed, 6 remain
        assert len(events) == 6

    # 31. No user-role events, nothing trimmed
    def test_no_user_role_events_no_trim(self):
        from app.hooks.session_hooks import trim_session_history
        events = [_make_event("model", f"a{i}") for i in range(5)]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 5

    # 32. Only model-role events, nothing trimmed
    def test_only_model_role_events(self):
        from app.hooks.session_hooks import trim_session_history
        events = [_make_event("model", "resp1"), _make_event("model", "resp2")]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 2

    # 33. Mixed roles, correct turn detection
    def test_mixed_roles_correct_detection(self):
        from app.hooks.session_hooks import trim_session_history
        e_u1 = _make_event("user", "q1")
        e_m1 = _make_event("model", "a1")
        e_u2 = _make_event("user", "q2")
        e_m2 = _make_event("model", "a2")
        events = [e_u1, e_m1, e_u2, e_m2]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 2
        assert events[0] is e_u2

    # 34. active_context not in state -> initialized
    def test_active_context_initialized(self):
        from app.hooks.session_hooks import trim_session_history
        state = {}
        ctx = _make_callback_context([_make_event()], state=state)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            trim_session_history(ctx)
        assert state["active_context"] == ""

    # 35. active_context already in state -> not overwritten
    def test_active_context_not_overwritten(self):
        from app.hooks.session_hooks import trim_session_history
        state = {"active_context": "some_value"}
        ctx = _make_callback_context([_make_event()], state=state)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 3):
            trim_session_history(ctx)
        assert state["active_context"] == "some_value"

    # 36. Exception during trimming -> caught, returns None
    def test_exception_caught_returns_none(self):
        from app.hooks.session_hooks import trim_session_history
        ctx = MagicMock()
        # Make accessing session raise an exception
        ctx._invocation_context.session = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        type(ctx._invocation_context).session = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        result = trim_session_history(ctx)
        assert result is None

    # 37. In-place modification
    def test_in_place_modification(self):
        from app.hooks.session_hooks import trim_session_history
        events = []
        for i in range(4):
            events.append(_make_event("user", f"q{i}"))
            events.append(_make_event("model", f"a{i}"))
        original_id = id(events)
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        # Same list object, modified in place
        assert id(events) == original_id
        assert len(events) == 2

    # 38. Turn boundary: event with content.role == "user" counts as turn
    def test_turn_boundary_user_role(self):
        from app.hooks.session_hooks import trim_session_history
        events = [
            _make_event("user", "q1"),
            _make_event("model", "a1"),
            _make_event("model", "a1b"),
            _make_event("user", "q2"),
            _make_event("model", "a2"),
        ]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        # Keep from index 3 (second user turn)
        assert len(events) == 2

    # 39. Event with content but no role -> not counted as turn
    def test_content_no_role_not_counted(self):
        from app.hooks.session_hooks import trim_session_history
        events = [
            _make_event("user", "q1"),
            _make_event_no_role("data"),
            _make_event("user", "q2"),
        ]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        # Only 2 user turns detected; keeps from second user turn
        assert len(events) == 1
        assert events[0].content.parts[0].text == "q2"

    # 40. Event with no content -> not counted as turn
    def test_no_content_not_counted(self):
        from app.hooks.session_hooks import trim_session_history
        events = [
            _make_event("user", "q1"),
            _make_event(has_content=False),
            _make_event("user", "q2"),
            _make_event("model", "a2"),
        ]
        ctx = _make_callback_context(events)
        with patch("app.hooks.session_hooks._MAX_HISTORY_TURNS", 1):
            trim_session_history(ctx)
        assert len(events) == 2


# ============================================================================
# Request context event bridge lifecycle tests
# ============================================================================

class TestLLMEventBridgeLifecycle:
    """Tests for init/push/teardown of the LLM event bridge in request_context."""

    # 41. Full lifecycle
    def test_full_lifecycle(self):
        from app.request_context import (
            init_llm_event_bridge,
            push_llm_event,
            teardown_llm_event_bridge,
        )
        buf = init_llm_event_bridge()
        push_llm_event({"type": "progress", "step": 1})
        push_llm_event({"type": "progress", "step": 2})
        push_llm_event({"type": "done"})
        assert len(buf) == 3
        assert buf[0]["step"] == 1
        assert buf[2]["type"] == "done"
        teardown_llm_event_bridge()

    # 42. Push without init -> silently drops
    def test_push_without_init_drops(self):
        from app.request_context import (
            push_llm_event,
            teardown_llm_event_bridge,
            _cv_llm_events,
        )
        # Ensure bridge is torn down first
        _cv_llm_events.set(None)
        # Should not raise
        push_llm_event({"type": "orphan"})

    # 43. Init twice -> second init overwrites
    def test_init_twice_overwrites(self):
        from app.request_context import init_llm_event_bridge, push_llm_event, teardown_llm_event_bridge
        buf1 = init_llm_event_bridge()
        push_llm_event({"v": 1})
        buf2 = init_llm_event_bridge()
        push_llm_event({"v": 2})
        assert len(buf1) == 1  # old buffer untouched after overwrite
        assert len(buf2) == 1
        assert buf2[0]["v"] == 2
        teardown_llm_event_bridge()

    # 44. Teardown without init -> no error
    def test_teardown_without_init(self):
        from app.request_context import teardown_llm_event_bridge, _cv_llm_events
        _cv_llm_events.set(None)
        teardown_llm_event_bridge()  # should not raise

    # 45. Concurrent tasks have independent bridges
    @pytest.mark.asyncio
    async def test_concurrent_independent_bridges(self):
        from app.request_context import (
            init_llm_event_bridge,
            push_llm_event,
            teardown_llm_event_bridge,
            _cv_llm_events,
        )

        results = {}

        async def worker(name, count):
            buf = init_llm_event_bridge()
            for i in range(count):
                push_llm_event({"worker": name, "i": i})
                await asyncio.sleep(0)
            results[name] = list(buf)
            teardown_llm_event_bridge()

        await asyncio.gather(worker("A", 3), worker("B", 5))
        assert len(results["A"]) == 3
        assert len(results["B"]) == 5
        assert all(e["worker"] == "A" for e in results["A"])
        assert all(e["worker"] == "B" for e in results["B"])

    # 46. Push after teardown -> drops silently
    def test_push_after_teardown_drops(self):
        from app.request_context import (
            init_llm_event_bridge,
            push_llm_event,
            teardown_llm_event_bridge,
        )
        buf = init_llm_event_bridge()
        push_llm_event({"before": True})
        teardown_llm_event_bridge()
        push_llm_event({"after": True})
        # buf still has only the one event from before teardown
        assert len(buf) == 1

    # 47. Complex event dicts with nested data
    def test_complex_event_dicts(self):
        from app.request_context import init_llm_event_bridge, push_llm_event, teardown_llm_event_bridge
        buf = init_llm_event_bridge()
        complex_event = {
            "type": "tool_result",
            "tool": "check_health",
            "data": {
                "status": "ok",
                "metrics": [1.2, 3.4, 5.6],
                "nested": {"deep": {"value": 42}},
            },
            "tags": ["prod", "us-east-1"],
        }
        push_llm_event(complex_event)
        assert buf[0]["data"]["nested"]["deep"]["value"] == 42
        assert buf[0]["tags"] == ["prod", "us-east-1"]
        teardown_llm_event_bridge()

    # 48. 1000 events all preserved
    def test_thousand_events_preserved(self):
        from app.request_context import init_llm_event_bridge, push_llm_event, teardown_llm_event_bridge
        buf = init_llm_event_bridge()
        for i in range(1000):
            push_llm_event({"i": i})
        assert len(buf) == 1000
        assert buf[999]["i"] == 999
        teardown_llm_event_bridge()


class TestUserTimeContext:
    """Tests for set/get_user_time_context in request_context."""

    # 49. Roundtrip
    def test_roundtrip(self):
        from app.request_context import set_user_time_context, get_user_time_context
        set_user_time_context("America/Los_Angeles", "1743494400000")
        tz, epoch = get_user_time_context()
        assert tz == "America/Los_Angeles"
        assert epoch == "1743494400000"

    # 50. None timezone stored
    def test_none_timezone(self):
        from app.request_context import set_user_time_context, get_user_time_context
        set_user_time_context(None, "12345")
        tz, epoch = get_user_time_context()
        assert tz is None
        assert epoch == "12345"

    # 51. Not set -> defaults (empty strings)
    def test_defaults_when_not_set(self):
        from app.request_context import get_user_time_context, _cv_timezone, _cv_epoch_ms
        # Reset to defaults
        _cv_timezone.set("")
        _cv_epoch_ms.set("")
        tz, epoch = get_user_time_context()
        assert tz == ""
        assert epoch == ""


class TestGetLLMHeaders:
    """Tests for get/set/clear_llm_headers and extract_llm_headers."""

    # 52. Various header combinations
    def test_set_get_headers(self):
        from app.request_context import set_llm_headers, get_llm_headers, clear_llm_headers
        hdrs = {
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "test@example.com",
        }
        set_llm_headers(hdrs)
        assert get_llm_headers() == hdrs
        clear_llm_headers()
        assert get_llm_headers() == {}

    # 53. extract_llm_headers extracts wm_llm_gw.* headers
    def test_extract_llm_headers(self):
        from app.request_context import extract_llm_headers
        request = MagicMock()
        request.headers = {
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "alice",
            "wm_llm_gw.user_agent": "Mozilla/5.0",
            "wm_llm_gw.user_ip": "10.0.0.1",
            "unrelated_header": "ignored",
        }
        result = extract_llm_headers(request)
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"
        assert result["wm_llm_gw.user_name"] == "alice"
        assert result["wm_llm_gw.user_agent"] == "Mozilla/5.0"
        assert result["wm_llm_gw.user_ip"] == "10.0.0.1"
        assert "unrelated_header" not in result

    # 54. extract_llm_headers with no matching headers -> defaults
    def test_extract_no_matching_headers(self):
        from app.request_context import extract_llm_headers
        request = MagicMock()
        request.headers = {"unrelated": "value"}
        result = extract_llm_headers(request)
        # user_type defaults to ASSOCIATE
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"
        assert "wm_llm_gw.user_agent" not in result
