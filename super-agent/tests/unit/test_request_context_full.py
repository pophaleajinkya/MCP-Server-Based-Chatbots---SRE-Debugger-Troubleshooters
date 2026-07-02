"""
Comprehensive unit tests for app.request_context — covers event bridge,
user time context, and all previously untested paths.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.request_context import (
    LLM_HEADER_KEYS,
    _DEFAULT_USER_TYPE,
    _normalize_user_type,
    clear_llm_headers,
    extract_llm_headers,
    get_llm_headers,
    get_user_time_context,
    init_llm_event_bridge,
    push_llm_event,
    set_llm_headers,
    set_user_time_context,
    teardown_llm_event_bridge,
)


# ── Event Bridge Tests ────────────────────────────────────────────────────────

class TestInitLlmEventBridge:

    def test_returns_empty_list(self):
        events = init_llm_event_bridge()
        assert events == []
        teardown_llm_event_bridge()

    def test_returns_mutable_list(self):
        events = init_llm_event_bridge()
        events.append({"type": "test"})
        assert len(events) == 1
        teardown_llm_event_bridge()


class TestPushLlmEvent:

    def test_push_appends_to_bridge(self):
        events = init_llm_event_bridge()
        push_llm_event({"type": "progress", "tool": "test"})
        assert len(events) == 1
        assert events[0]["type"] == "progress"
        teardown_llm_event_bridge()

    def test_push_multiple_events(self):
        events = init_llm_event_bridge()
        push_llm_event({"type": "a"})
        push_llm_event({"type": "b"})
        push_llm_event({"type": "c"})
        assert len(events) == 3
        teardown_llm_event_bridge()

    def test_push_noop_when_bridge_not_initialized(self):
        """When bridge not initialized, push is a silent no-op."""
        teardown_llm_event_bridge()  # ensure None
        push_llm_event({"type": "should_be_ignored"})
        # No exception raised

    def test_push_noop_after_teardown(self):
        init_llm_event_bridge()
        teardown_llm_event_bridge()
        push_llm_event({"type": "should_be_ignored"})
        # No exception raised


class TestTeardownLlmEventBridge:

    def test_teardown_sets_none(self):
        init_llm_event_bridge()
        teardown_llm_event_bridge()
        # After teardown, push should be a no-op
        push_llm_event({"type": "after_teardown"})
        # No exception

    def test_teardown_idempotent(self):
        """Calling teardown multiple times is safe."""
        teardown_llm_event_bridge()
        teardown_llm_event_bridge()
        # No exception


class TestEventBridgeIsolation:

    @pytest.mark.asyncio
    async def test_bridge_isolated_between_tasks(self):
        """Event bridges are per-task via contextvars."""
        results = {}

        async def task_a():
            events = init_llm_event_bridge()
            push_llm_event({"source": "a"})
            await asyncio.sleep(0.01)
            results["a"] = list(events)
            teardown_llm_event_bridge()

        async def task_b():
            events = init_llm_event_bridge()
            push_llm_event({"source": "b"})
            await asyncio.sleep(0.01)
            results["b"] = list(events)
            teardown_llm_event_bridge()

        await asyncio.gather(task_a(), task_b())
        assert len(results["a"]) == 1
        assert results["a"][0]["source"] == "a"
        assert len(results["b"]) == 1
        assert results["b"][0]["source"] == "b"


# ── User Time Context Tests ──────────────────────────────────────────────────

class TestSetUserTimeContext:

    def test_set_and_get(self):
        set_user_time_context("America/Chicago", "1743494400000")
        tz, epoch = get_user_time_context()
        assert tz == "America/Chicago"
        assert epoch == "1743494400000"

    def test_default_values(self):
        """Default values are empty strings when not set."""
        # Reset by setting empty
        set_user_time_context("", "")
        tz, epoch = get_user_time_context()
        assert tz == ""
        assert epoch == ""

    def test_overwrite_values(self):
        set_user_time_context("UTC", "1000")
        set_user_time_context("Asia/Kolkata", "2000")
        tz, epoch = get_user_time_context()
        assert tz == "Asia/Kolkata"
        assert epoch == "2000"

    def test_returns_tuple(self):
        set_user_time_context("US/Pacific", "999")
        result = get_user_time_context()
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestTimeContextIsolation:

    @pytest.mark.asyncio
    async def test_time_context_isolated_between_tasks(self):
        results = {}

        async def task_a():
            set_user_time_context("America/New_York", "1111")
            await asyncio.sleep(0.01)
            results["a"] = get_user_time_context()

        async def task_b():
            set_user_time_context("Asia/Tokyo", "2222")
            await asyncio.sleep(0.01)
            results["b"] = get_user_time_context()

        await asyncio.gather(task_a(), task_b())
        assert results["a"] == ("America/New_York", "1111")
        assert results["b"] == ("Asia/Tokyo", "2222")


# ── Normalize User Type (edge cases) ─────────────────────────────────────────

class TestNormalizeUserType:

    @pytest.mark.parametrize("value,expected", [
        ("ASSOCIATE", "ASSOCIATE"),
        ("RETAIL_CUSTOMER", "RETAIL_CUSTOMER"),
        ("VENDOR", "VENDOR"),
        ("TECH_DEVELOPMENT", "TECH_DEVELOPMENT"),
        ("NO_END_USER", "NO_END_USER"),
    ])
    def test_valid_types_pass_through(self, value, expected):
        assert _normalize_user_type(value) == expected

    @pytest.mark.parametrize("legacy", ["S", "H", "SALARIED", "HOURLY", "STANDARD"])
    def test_legacy_types_map_to_associate(self, legacy):
        assert _normalize_user_type(legacy) == "ASSOCIATE"

    def test_case_insensitive(self):
        assert _normalize_user_type("associate") == "ASSOCIATE"
        assert _normalize_user_type("Vendor") == "VENDOR"

    def test_whitespace_stripped(self):
        assert _normalize_user_type("  ASSOCIATE  ") == "ASSOCIATE"
        assert _normalize_user_type(" S ") == "ASSOCIATE"

    def test_unknown_defaults_to_associate(self):
        assert _normalize_user_type("ROBOT") == _DEFAULT_USER_TYPE
        assert _normalize_user_type("") == _DEFAULT_USER_TYPE

    def test_empty_string_defaults(self):
        assert _normalize_user_type("") == "ASSOCIATE"


# ── Extract LLM Headers (edge cases) ─────────────────────────────────────────

class TestExtractLlmHeaders:

    def _make_request(self, headers: dict) -> MagicMock:
        mock = MagicMock()
        mock.headers = headers
        return mock

    def test_all_headers_present(self):
        req = self._make_request({
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "alice",
            "wm_llm_gw.user_agent": "Chrome/120",
            "wm_llm_gw.user_ip": "10.0.0.1",
        })
        h = extract_llm_headers(req)
        assert h["wm_llm_gw.user_type"] == "ASSOCIATE"
        assert h["wm_llm_gw.user_name"] == "alice"
        assert h["wm_llm_gw.user_agent"] == "Chrome/120"
        assert h["wm_llm_gw.user_ip"] == "10.0.0.1"

    def test_missing_user_type_defaults(self):
        req = self._make_request({"wm_llm_gw.user_name": "bob"})
        h = extract_llm_headers(req)
        assert h["wm_llm_gw.user_type"] == "ASSOCIATE"

    def test_missing_user_name_falls_back_to_loginid(self):
        req = self._make_request({"loginId": "charlie@walmart.com"})
        h = extract_llm_headers(req)
        assert h["wm_llm_gw.user_name"] == "charlie@walmart.com"

    def test_missing_user_name_falls_back_to_lowercase_loginid(self):
        req = self._make_request({"loginid": "dave@walmart.com"})
        h = extract_llm_headers(req)
        assert h["wm_llm_gw.user_name"] == "dave@walmart.com"

    def test_no_headers_at_all(self):
        req = self._make_request({})
        h = extract_llm_headers(req)
        assert h["wm_llm_gw.user_type"] == "ASSOCIATE"
        assert "wm_llm_gw.user_name" not in h

    def test_legacy_user_type_normalized(self):
        req = self._make_request({"wm_llm_gw.user_type": "H"})
        h = extract_llm_headers(req)
        assert h["wm_llm_gw.user_type"] == "ASSOCIATE"

    def test_header_keys_constant(self):
        assert len(LLM_HEADER_KEYS) == 4
        assert "wm_llm_gw.user_type" in LLM_HEADER_KEYS
        assert "wm_llm_gw.user_name" in LLM_HEADER_KEYS


# ── Set/Get/Clear round-trip ──────────────────────────────────────────────────

class TestLlmHeadersRoundTrip:

    def test_set_and_get(self):
        headers = {"wm_llm_gw.user_name": "test"}
        set_llm_headers(headers)
        assert get_llm_headers() == headers
        clear_llm_headers()

    def test_clear_resets_to_empty(self):
        set_llm_headers({"key": "val"})
        clear_llm_headers()
        assert get_llm_headers() == {}

    def test_default_is_empty_dict(self):
        clear_llm_headers()
        assert get_llm_headers() == {}

    @pytest.mark.asyncio
    async def test_headers_isolated_between_tasks(self):
        results = {}

        async def task_a():
            set_llm_headers({"task": "a"})
            await asyncio.sleep(0.01)
            results["a"] = get_llm_headers()
            clear_llm_headers()

        async def task_b():
            set_llm_headers({"task": "b"})
            await asyncio.sleep(0.01)
            results["b"] = get_llm_headers()
            clear_llm_headers()

        await asyncio.gather(task_a(), task_b())
        assert results["a"]["task"] == "a"
        assert results["b"]["task"] == "b"
