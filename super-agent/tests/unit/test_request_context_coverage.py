"""Additional unit tests for app.request_context — covers user_type normalization, time context."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestPushLlmEvent:
    def test_push_with_no_bridge_is_noop(self):
        from app.request_context import push_llm_event, _cv_llm_events
        # Ensure bridge is not initialized
        _cv_llm_events.set(None)
        # Should not raise
        push_llm_event({"type": "test"})

    def test_push_with_active_bridge(self):
        from app.request_context import push_llm_event, init_llm_event_bridge
        buf = init_llm_event_bridge()
        push_llm_event({"type": "shrink"})
        assert len(buf) == 1
        assert buf[0]["type"] == "shrink"
        # Cleanup
        from app.request_context import teardown_llm_event_bridge
        teardown_llm_event_bridge()


class TestUserTimeContext:
    def test_set_and_get(self):
        from app.request_context import set_user_time_context, get_user_time_context
        set_user_time_context("America/Los_Angeles", "1743494400000")
        tz, epoch = get_user_time_context()
        assert tz == "America/Los_Angeles"
        assert epoch == "1743494400000"

    def test_defaults_when_not_set(self):
        from app.request_context import get_user_time_context, _cv_timezone, _cv_epoch_ms
        # Reset to defaults
        _cv_timezone.set("")
        _cv_epoch_ms.set("")
        tz, epoch = get_user_time_context()
        assert tz == ""
        assert epoch == ""


class TestTeardownBridge:
    def test_teardown_clears_bridge(self):
        from app.request_context import init_llm_event_bridge, teardown_llm_event_bridge, _cv_llm_events
        init_llm_event_bridge()
        assert _cv_llm_events.get(None) is not None
        teardown_llm_event_bridge()
        assert _cv_llm_events.get(None) is None
