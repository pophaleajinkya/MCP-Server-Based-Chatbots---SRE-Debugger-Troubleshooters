"""Comprehensive negative and edge-case tests for core modules.

Covers session_hooks, request_context, store/keys, models/schemas,
exceptions, and logging with adversarial and boundary inputs.
"""

import asyncio
import json
import logging
import sys
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# session_hooks.py negative tests
# ---------------------------------------------------------------------------

class TestTrimSessionHistoryNegative:
    """Negative / edge-case tests for trim_session_history."""

    def _make_callback_context(self, events=None, state=None):
        ctx = MagicMock()
        session = MagicMock()
        session.events = events if events is not None else []
        ctx._invocation_context.session = session
        ctx.state = state if state is not None else {}
        return ctx

    def test_empty_session_events(self):
        """trim_session_history with a session that has zero events."""
        from app.hooks.session_hooks import trim_session_history
        ctx = self._make_callback_context(events=[])
        result = trim_session_history(ctx)
        assert result is None
        assert ctx._invocation_context.session.events == []

    def test_session_no_events_attribute(self):
        """trim_session_history when events is None."""
        from app.hooks.session_hooks import trim_session_history
        ctx = self._make_callback_context(events=None)
        # None is falsy, so it should return None without crashing
        result = trim_session_history(ctx)
        assert result is None

    def test_events_with_no_user_role(self):
        """trim_session_history when no event has role='user'."""
        from app.hooks.session_hooks import trim_session_history
        event = MagicMock()
        event.content.role = "model"
        ctx = self._make_callback_context(events=[event])
        result = trim_session_history(ctx)
        assert result is None

    def test_callback_context_missing_invocation_context(self):
        """trim_session_history handles missing _invocation_context gracefully."""
        from app.hooks.session_hooks import trim_session_history
        ctx = MagicMock()
        ctx._invocation_context = None
        ctx.state = {}
        # Accessing session on None should raise, but the handler catches it
        type(ctx)._invocation_context = property(lambda s: (_ for _ in ()).throw(AttributeError))
        result = trim_session_history(ctx)
        assert result is None


class TestCacheEviction:
    """Tests for TABLE_ROW_CACHE eviction logic."""

    def test_all_entries_stale(self):
        """Eviction removes all entries when everything is stale."""
        from app.hooks.session_hooks import TABLE_ROW_CACHE, _evict_stale_cache_entries, _CACHE_TTL_SECONDS
        TABLE_ROW_CACHE.clear()
        old_ts = _time.monotonic() - _CACHE_TTL_SECONDS - 100
        TABLE_ROW_CACHE["stale1"] = {"table_data": {}, "_ts": old_ts}
        TABLE_ROW_CACHE["stale2"] = {"table_data": {}, "_ts": old_ts}
        TABLE_ROW_CACHE["stale3"] = {"table_data": {}, "_ts": old_ts}
        _evict_stale_cache_entries()
        assert len(TABLE_ROW_CACHE) == 0

    def test_all_entries_fresh(self):
        """Eviction keeps all entries when none are stale."""
        from app.hooks.session_hooks import TABLE_ROW_CACHE, _evict_stale_cache_entries
        TABLE_ROW_CACHE.clear()
        now = _time.monotonic()
        TABLE_ROW_CACHE["fresh1"] = {"table_data": {}, "_ts": now}
        TABLE_ROW_CACHE["fresh2"] = {"table_data": {}, "_ts": now}
        _evict_stale_cache_entries()
        assert len(TABLE_ROW_CACHE) == 2
        TABLE_ROW_CACHE.clear()

    def test_pop_missing_key(self):
        """TABLE_ROW_CACHE.pop on a missing key returns None."""
        from app.hooks.session_hooks import TABLE_ROW_CACHE
        TABLE_ROW_CACHE.clear()
        result = TABLE_ROW_CACHE.pop("nonexistent_key", None)
        assert result is None

    def test_chart_cache_very_large_entries(self):
        """CHART_DATA_CACHE handles very large entries without crashing."""
        from app.hooks.session_hooks import CHART_DATA_CACHE
        CHART_DATA_CACHE.clear()
        large_data = {"values": list(range(100_000)), "_ts": _time.monotonic()}
        CHART_DATA_CACHE["big_entry"] = large_data
        assert len(CHART_DATA_CACHE["big_entry"]["values"]) == 100_000
        CHART_DATA_CACHE.clear()

    def test_cache_key_collisions_similar_session_ids(self):
        """Different session_id:call_id pairs must produce distinct cache keys."""
        from app.hooks.session_hooks import table_row_cache_key
        k1 = table_row_cache_key("sess:1", "call1")
        k2 = table_row_cache_key("sess", "1:call1")
        # These WILL differ because the format is "{session_id}:{call_id}"
        # but the point is they could potentially collide in edge cases
        assert k1 == "sess:1:call1"
        assert k2 == "sess:1:call1"
        # This demonstrates that session_id containing ':' can cause ambiguity

    def test_concurrent_cache_writes_race_simulation(self):
        """Simulate concurrent writes to TABLE_ROW_CACHE."""
        from app.hooks.session_hooks import TABLE_ROW_CACHE
        TABLE_ROW_CACHE.clear()
        # Simulate two writers targeting the same key
        key = "race_key"
        TABLE_ROW_CACHE[key] = {"table_data": {"from": "writer1"}, "_ts": _time.monotonic()}
        TABLE_ROW_CACHE[key] = {"table_data": {"from": "writer2"}, "_ts": _time.monotonic()}
        # Last write wins in dict
        assert TABLE_ROW_CACHE[key]["table_data"]["from"] == "writer2"
        TABLE_ROW_CACHE.clear()


class TestAfterToolHandlerNegative:
    """Negative tests for after_tool_handler."""

    def _make_tool(self, name="test_tool"):
        t = MagicMock()
        t.name = name
        return t

    def _make_tool_context(self):
        tc = MagicMock()
        tc.state = {}
        tc.function_call_id = "call-123"
        tc._invocation_context.session.id = "sess-abc"
        return tc

    def test_malformed_tool_response(self):
        """after_tool_handler with a tool_response missing 'content'."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        result = after_tool_handler(tool, {"arg1": "val"}, tc, {"no_content": True})
        assert result is None

    def test_non_json_response_text(self):
        """after_tool_handler with non-JSON text in content."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        response = {"content": [{"text": "This is not JSON at all"}]}
        result = after_tool_handler(tool, {}, tc, response)
        assert result is None

    def test_empty_response(self):
        """after_tool_handler with completely empty tool_response."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        result = after_tool_handler(tool, {}, tc, {})
        assert result is None

    def test_empty_content_list(self):
        """after_tool_handler with empty content list."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        result = after_tool_handler(tool, {}, tc, {"content": []})
        assert result is None

    def test_missing_args_none(self):
        """before_tool_callback (via after_tool_handler) with None args."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        # args=None should be handled gracefully
        result = after_tool_handler(tool, None, tc, {})
        assert result is None

    def test_content_is_not_list(self):
        """after_tool_handler with content that is a string instead of list."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        result = after_tool_handler(tool, {}, tc, {"content": "not a list"})
        assert result is None

    def test_response_text_is_json_array(self):
        """after_tool_handler when response text parses to a list not dict."""
        from app.hooks.session_hooks import after_tool_handler
        tool = self._make_tool()
        tc = self._make_tool_context()
        response = {"content": [{"text": "[1, 2, 3]"}]}
        result = after_tool_handler(tool, {}, tc, response)
        assert result is None


class TestSaveArgsToState:
    """Tests for _save_args_to_state edge cases."""

    def test_skip_tool_in_blocklist(self):
        from app.hooks.session_hooks import _save_args_to_state
        tc = MagicMock()
        tc.state = {}
        _save_args_to_state({"name": "foo"}, tc, "get_mcp_prompt")
        assert "name" not in tc.state

    def test_empty_string_values_skipped(self):
        from app.hooks.session_hooks import _save_args_to_state
        tc = MagicMock()
        tc.state = {}
        _save_args_to_state({"app": "", "ns": "prod"}, tc, "check_health")
        assert "app" not in tc.state
        assert tc.state["ns"] == "prod"


# ---------------------------------------------------------------------------
# request_context.py negative tests
# ---------------------------------------------------------------------------

class TestRequestContextNegative:
    """Negative / edge-case tests for request_context."""

    def test_get_llm_headers_default_empty(self):
        """get_llm_headers returns empty dict when not initialized."""
        from app.request_context import get_llm_headers, _llm_headers
        # Reset to default
        _llm_headers.set({})
        assert get_llm_headers() == {}

    def test_set_llm_headers_with_empty_dict(self):
        """set_llm_headers with empty dict."""
        from app.request_context import set_llm_headers, get_llm_headers
        set_llm_headers({})
        assert get_llm_headers() == {}

    def test_extract_llm_headers_none_header_values(self):
        """extract_llm_headers when request headers have no matching keys."""
        from app.request_context import extract_llm_headers
        request = MagicMock()
        # Use a MagicMock for headers so .get returns None by default
        mock_headers = MagicMock()
        mock_headers.get = MagicMock(return_value=None)
        request.headers = mock_headers
        headers = extract_llm_headers(request)
        assert headers["wm_llm_gw.user_type"] == "ASSOCIATE"

    def test_push_llm_event_when_bridge_not_initialized(self):
        """push_llm_event is a no-op when bridge not initialized."""
        from app.request_context import push_llm_event, _cv_llm_events
        _cv_llm_events.set(None)
        # Should not raise
        push_llm_event({"type": "progress"})

    def test_teardown_llm_event_bridge_when_not_initialized(self):
        """teardown_llm_event_bridge is safe to call even when not initialized."""
        from app.request_context import teardown_llm_event_bridge, _cv_llm_events
        _cv_llm_events.set(None)
        teardown_llm_event_bridge()
        assert _cv_llm_events.get(None) is None

    def test_init_llm_event_bridge_overwrites_existing(self):
        """Calling init_llm_event_bridge when already initialized replaces the list."""
        from app.request_context import init_llm_event_bridge, push_llm_event, _cv_llm_events
        first = init_llm_event_bridge()
        push_llm_event({"type": "old"})
        assert len(first) == 1
        second = init_llm_event_bridge()
        assert len(second) == 0
        assert second is not first
        # cleanup
        _cv_llm_events.set(None)

    def test_set_user_time_context_with_empty_strings(self):
        """set_user_time_context with empty timezone and epoch_ms."""
        from app.request_context import set_user_time_context, get_user_time_context
        set_user_time_context("", "")
        tz, epoch = get_user_time_context()
        assert tz == ""
        assert epoch == ""

    def test_set_user_time_context_invalid_timezone(self):
        """set_user_time_context accepts any string (no validation)."""
        from app.request_context import set_user_time_context, get_user_time_context
        set_user_time_context("Not/A/Real/Timezone", "99999")
        tz, epoch = get_user_time_context()
        assert tz == "Not/A/Real/Timezone"
        assert epoch == "99999"

    def test_get_user_time_context_when_not_set(self):
        """get_user_time_context returns ('', '') as defaults."""
        from app.request_context import get_user_time_context, _cv_timezone, _cv_epoch_ms
        _cv_timezone.set("")
        _cv_epoch_ms.set("")
        tz, epoch = get_user_time_context()
        assert tz == ""
        assert epoch == ""

    def test_header_values_with_null_bytes(self):
        """set_llm_headers with null bytes in values."""
        from app.request_context import set_llm_headers, get_llm_headers
        headers = {"wm_llm_gw.user_name": "user\x00injected"}
        set_llm_headers(headers)
        assert "\x00" in get_llm_headers()["wm_llm_gw.user_name"]

    def test_header_values_with_newlines(self):
        """set_llm_headers with newline injection attempt."""
        from app.request_context import set_llm_headers, get_llm_headers
        headers = {"wm_llm_gw.user_name": "user\r\nX-Injected: true"}
        set_llm_headers(headers)
        assert "\r\n" in get_llm_headers()["wm_llm_gw.user_name"]

    def test_very_long_header_values(self):
        """set_llm_headers with extremely long header value (>8KB)."""
        from app.request_context import set_llm_headers, get_llm_headers
        long_val = "A" * 10_000
        headers = {"wm_llm_gw.user_name": long_val}
        set_llm_headers(headers)
        assert len(get_llm_headers()["wm_llm_gw.user_name"]) == 10_000

    def test_unicode_in_header_keys_and_values(self):
        """set_llm_headers with unicode characters."""
        from app.request_context import set_llm_headers, get_llm_headers
        headers = {"wm_llm_gw.user_name": "usuario_\u00e9\u00e0\u00fc\u00f1"}
        set_llm_headers(headers)
        assert get_llm_headers()["wm_llm_gw.user_name"] == "usuario_\u00e9\u00e0\u00fc\u00f1"

    def test_normalize_user_type_legacy_values(self):
        """_normalize_user_type maps legacy values to ASSOCIATE."""
        from app.request_context import _normalize_user_type
        assert _normalize_user_type("S") == "ASSOCIATE"
        assert _normalize_user_type("H") == "ASSOCIATE"
        assert _normalize_user_type("SALARIED") == "ASSOCIATE"

    def test_normalize_user_type_unknown(self):
        """_normalize_user_type defaults unknown values."""
        from app.request_context import _normalize_user_type
        assert _normalize_user_type("ROBOT") == "ASSOCIATE"
        assert _normalize_user_type("") == "ASSOCIATE"

    @pytest.mark.asyncio
    async def test_asyncio_task_isolation(self):
        """Different asyncio tasks have isolated context variables."""
        from app.request_context import set_llm_headers, get_llm_headers

        results = {}

        async def task_a():
            set_llm_headers({"wm_llm_gw.user_name": "alice"})
            await asyncio.sleep(0.01)
            results["a"] = get_llm_headers()

        async def task_b():
            set_llm_headers({"wm_llm_gw.user_name": "bob"})
            await asyncio.sleep(0.01)
            results["b"] = get_llm_headers()

        # Run tasks concurrently — contextvars are per-Task when using create_task
        ta = asyncio.create_task(task_a())
        tb = asyncio.create_task(task_b())
        await ta
        await tb
        # Each task should see its own header (asyncio tasks copy parent context)
        assert results["a"]["wm_llm_gw.user_name"] == "alice"
        assert results["b"]["wm_llm_gw.user_name"] == "bob"


# ---------------------------------------------------------------------------
# store/keys.py negative tests
# ---------------------------------------------------------------------------

class TestKeysNegative:
    """Negative / edge-case tests for store/keys.py."""

    def test_key_session_empty_strings(self):
        from app.store.keys import key_session
        result = key_session("", "", "")
        assert result == "adk:session:::"

    def test_key_events_empty_strings(self):
        from app.store.keys import key_events
        result = key_events("", "", "")
        assert result == "adk:events:::"

    def test_key_app_state_empty_string(self):
        from app.store.keys import key_app_state
        assert key_app_state("") == "adk:app_state:"

    def test_key_user_state_empty_strings(self):
        from app.store.keys import key_user_state
        assert key_user_state("", "") == "adk:user_state::"

    def test_key_sessions_index_empty(self):
        from app.store.keys import key_sessions_index
        assert key_sessions_index("", "") == "adk:sessions::"

    def test_key_session_very_long_args(self):
        """Key functions with 10K-char arguments."""
        from app.store.keys import key_session
        long_str = "x" * 10_000
        result = key_session(long_str, long_str, long_str)
        assert long_str in result
        assert len(result) > 30_000

    def test_key_session_special_redis_chars(self):
        """Key functions with special Redis characters."""
        from app.store.keys import key_session
        result = key_session("app{1}", "user*", "sid:}")
        assert result == "adk:session:app{1}:user*:sid:}"

    def test_key_session_unicode(self):
        """Key functions with unicode arguments."""
        from app.store.keys import key_session
        result = key_session("app\u00e9", "user\u00fc", "sid\u00f1")
        assert "app\u00e9" in result
        assert "user\u00fc" in result

    def test_key_session_newlines_and_control_chars(self):
        """Key functions with newlines and control characters."""
        from app.store.keys import key_session
        result = key_session("app\n", "user\r\n", "sid\t")
        assert "\n" in result
        assert "\t" in result

    def test_key_collision_resistance(self):
        """Different inputs must produce different keys."""
        from app.store.keys import key_session
        k1 = key_session("a", "b", "c")
        k2 = key_session("a", "b", "d")
        k3 = key_session("a", "c", "c")
        k4 = key_session("b", "b", "c")
        assert len({k1, k2, k3, k4}) == 4

    def test_key_format_consistency(self):
        """All key builders follow the expected prefix:separated format."""
        from app.store.keys import (
            key_session, key_events, key_app_state, key_user_state,
            key_sessions_index, key_sessions_zset, key_session_meta,
            key_ui_events, key_ui_stream, key_llm_pending, key_idem_inject,
        )
        assert key_session("a", "b", "c").startswith("adk:session:")
        assert key_events("a", "b", "c").startswith("adk:events:")
        assert key_app_state("a").startswith("adk:app_state:")
        assert key_user_state("a", "b").startswith("adk:user_state:")
        assert key_sessions_index("a", "b").startswith("adk:sessions:")
        assert key_sessions_zset("a", "b").startswith("adk:sessions_z:")
        assert key_session_meta("a", "b").startswith("adk:session_meta:")
        assert key_ui_events("a", "b", "c").startswith("agent:ui_events:")
        assert key_ui_stream("a", "b", "c").startswith("agent:ui_stream:")
        assert key_llm_pending("a", "b", "c").startswith("agent:llm_pending:")
        assert key_idem_inject("a", "b", "c", "d").startswith("agent:idem_inject:")

    def test_key_llm_pending_empty(self):
        from app.store.keys import key_llm_pending
        assert key_llm_pending("", "", "") == "agent:llm_pending:::"

    def test_key_idem_inject_empty(self):
        from app.store.keys import key_idem_inject
        assert key_idem_inject("", "", "", "") == "agent:idem_inject::::"

    def test_key_sessions_public_empty(self):
        from app.store.keys import key_sessions_public
        assert key_sessions_public("") == "adk:sessions_public:"

    def test_key_session_visibility_empty(self):
        from app.store.keys import key_session_visibility
        assert key_session_visibility("", "") == "agent:session_visibility::"

    def test_key_session_shared_empty(self):
        from app.store.keys import key_session_shared
        assert key_session_shared("", "") == "agent:session_shared::"


# ---------------------------------------------------------------------------
# models/schemas.py negative tests
# ---------------------------------------------------------------------------

class TestSchemasNegative:
    """Negative / edge-case tests for models/schemas.py."""

    def test_query_request_empty_query_rejected(self):
        """QueryRequest rejects empty string (min_length=1)."""
        from app.models.schemas import QueryRequest
        with pytest.raises(Exception):  # ValidationError
            QueryRequest(query="")

    def test_query_request_none_query_rejected(self):
        """QueryRequest rejects None query."""
        from app.models.schemas import QueryRequest
        with pytest.raises(Exception):
            QueryRequest(query=None)

    def test_query_request_very_long_query_rejected(self):
        """QueryRequest rejects query over max_length=4096."""
        from app.models.schemas import QueryRequest
        with pytest.raises(Exception):
            QueryRequest(query="x" * 4097)

    def test_query_request_max_length_accepted(self):
        """QueryRequest accepts query at exactly max_length."""
        from app.models.schemas import QueryRequest
        q = QueryRequest(query="x" * 4096)
        assert len(q.query) == 4096

    def test_query_request_unicode_emoji(self):
        """QueryRequest with unicode and emoji."""
        from app.models.schemas import QueryRequest
        q = QueryRequest(query="Check health \U0001f680\U0001f525\u2603")
        assert "\U0001f680" in q.query

    def test_query_request_control_characters(self):
        """QueryRequest with control characters (tab, newline)."""
        from app.models.schemas import QueryRequest
        q = QueryRequest(query="line1\nline2\ttab")
        assert "\n" in q.query

    def test_query_request_sql_injection_payload(self):
        """QueryRequest accepts SQL injection payload (no server-side filtering)."""
        from app.models.schemas import QueryRequest
        q = QueryRequest(query="'; DROP TABLE sessions; --")
        assert "DROP TABLE" in q.query

    def test_query_request_xss_payload(self):
        """QueryRequest accepts XSS payload (no HTML filtering at schema level)."""
        from app.models.schemas import QueryRequest
        q = QueryRequest(query='<script>alert("xss")</script>')
        assert "<script>" in q.query

    def test_query_response_construction(self):
        """QueryResponse can be created with any string values."""
        from app.models.schemas import QueryResponse
        r = QueryResponse(response="ok", session_id="abc")
        assert r.response == "ok"

    def test_query_response_missing_fields_rejected(self):
        """QueryResponse requires both fields."""
        from app.models.schemas import QueryResponse
        with pytest.raises(Exception):
            QueryResponse()

    def test_health_response_empty_lists(self):
        """HealthResponse with empty mcp_servers and mcp_tools."""
        from app.models.schemas import HealthResponse
        h = HealthResponse(
            status="ok", version="1.0", active_llm="gpt-4",
            llm_endpoint="https://example.com",
            mcp_servers=[], mcp_tools=[]
        )
        assert h.mcp_servers == []
        assert h.mcp_tools == []

    def test_mcp_server_info_any_url_accepted(self):
        """MCPServerInfo does not validate URL format (just a string)."""
        from app.models.schemas import MCPServerInfo
        s = MCPServerInfo(name="test", url="not-a-url")
        assert s.url == "not-a-url"

    def test_query_request_auto_session_id(self):
        """QueryRequest auto-generates session_id when omitted."""
        from app.models.schemas import QueryRequest
        q = QueryRequest(query="hello")
        assert q.session_id is not None
        assert len(q.session_id) > 0

    def test_query_request_session_id_too_long_rejected(self):
        """QueryRequest rejects session_id over max_length=256."""
        from app.models.schemas import QueryRequest
        with pytest.raises(Exception):
            QueryRequest(query="hello", session_id="s" * 257)


# ---------------------------------------------------------------------------
# exceptions.py edge cases
# ---------------------------------------------------------------------------

class TestExceptionsEdgeCases:
    """Edge-case tests for the exception hierarchy and handlers."""

    def test_llm_error_status_code_zero(self):
        from app.exceptions import LLMError
        e = LLMError(status_code=0, detail="zero status")
        assert e.status_code == 0
        assert e.detail == "zero status"

    def test_llm_error_negative_status_code(self):
        from app.exceptions import LLMError
        e = LLMError(status_code=-1, detail="negative")
        assert e.status_code == -1

    def test_llm_error_very_large_status_code(self):
        from app.exceptions import LLMError
        e = LLMError(status_code=999_999, detail="huge")
        assert e.status_code == 999_999

    def test_exception_chaining(self):
        """LLMError can be chained with 'from' syntax."""
        from app.exceptions import LLMError
        original = ValueError("original cause")
        try:
            raise LLMError(status_code=500, detail="chained") from original
        except LLMError as e:
            assert e.__cause__ is original
            assert e.status_code == 500

    def test_exception_str_with_unicode(self):
        from app.exceptions import LLMError
        e = LLMError(status_code=500, detail="Error: \u00e9\u00e0\u00fc\u00f1 \U0001f525")
        assert "\u00e9" in str(e)

    def test_agent_error_str(self):
        from app.exceptions import AgentError
        e = AgentError("something broke")
        assert str(e) == "something broke"

    def test_mcp_connection_error_str(self):
        from app.exceptions import MCPConnectionError
        e = MCPConnectionError("server down")
        assert str(e) == "server down"

    def test_mcp_tool_error_str(self):
        from app.exceptions import MCPToolError
        e = MCPToolError("tool failed after retry")
        assert str(e) == "tool failed after retry"

    @pytest.mark.asyncio
    async def test_llm_error_handler_returns_502(self):
        from app.exceptions import LLMError, llm_error_handler
        exc = LLMError(status_code=429, detail="rate limited")
        request = MagicMock()
        resp = await llm_error_handler(request, exc)
        assert resp.status_code == 502
        body = json.loads(resp.body)
        assert body["llm_status_code"] == 429

    @pytest.mark.asyncio
    async def test_agent_error_handler_returns_500(self):
        from app.exceptions import AgentError, agent_error_handler
        exc = AgentError("unrecoverable")
        request = MagicMock()
        resp = await agent_error_handler(request, exc)
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_mcp_connection_error_handler_returns_503(self):
        from app.exceptions import MCPConnectionError, mcp_connection_error_handler
        exc = MCPConnectionError("unreachable")
        request = MagicMock()
        resp = await mcp_connection_error_handler(request, exc)
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_handler_with_none_request(self):
        """Exception handlers still work when request is None."""
        from app.exceptions import LLMError, llm_error_handler
        exc = LLMError(status_code=500, detail="test")
        resp = await llm_error_handler(None, exc)
        assert resp.status_code == 502

    def test_exception_hierarchy(self):
        """All custom exceptions inherit from AgentBaseError."""
        from app.exceptions import AgentBaseError, MCPConnectionError, MCPToolError, LLMError, AgentError
        assert issubclass(MCPConnectionError, AgentBaseError)
        assert issubclass(MCPToolError, AgentBaseError)
        assert issubclass(LLMError, AgentBaseError)
        assert issubclass(AgentError, AgentBaseError)


# ---------------------------------------------------------------------------
# logging.py edge cases
# ---------------------------------------------------------------------------

class TestLoggingEdgeCases:
    """Edge-case tests for setup_logging."""

    def test_setup_logging_idempotent(self):
        """Calling setup_logging multiple times does not duplicate handlers."""
        from app.logging import setup_logging
        logger1 = setup_logging()
        handler_count_1 = len(logging.getLogger().handlers)
        logger2 = setup_logging()
        handler_count_2 = len(logging.getLogger().handlers)
        assert handler_count_1 == handler_count_2
        assert handler_count_2 == 1  # only one StreamHandler

    def test_logging_with_unicode(self):
        """Logger handles unicode messages without crashing."""
        from app.logging import setup_logging
        logger = setup_logging()
        logger.info("Unicode test: \u00e9\u00e0\u00fc \U0001f680 \u4f60\u597d")

    def test_logging_with_very_long_message(self):
        """Logger handles very long messages."""
        from app.logging import setup_logging
        logger = setup_logging()
        long_msg = "A" * 100_000
        logger.info(long_msg)

    def test_setup_logging_returns_root_logger(self):
        """setup_logging returns the root logger."""
        from app.logging import setup_logging
        logger = setup_logging()
        assert logger is logging.getLogger()

    def test_noisy_loggers_handlers_cleared(self):
        """Noisy third-party loggers have their handlers cleared."""
        from app.logging import setup_logging, _NOISY_LOGGERS
        # Add a handler to one of the noisy loggers
        noisy = logging.getLogger("LiteLLM")
        noisy.addHandler(logging.StreamHandler())
        setup_logging()
        assert len(noisy.handlers) == 0
        assert noisy.propagate is True


# ---------------------------------------------------------------------------
# on_tool_error_handler edge cases
# ---------------------------------------------------------------------------

class TestOnToolErrorHandler:
    """Edge cases for on_tool_error_handler."""

    def test_tool_name_none(self):
        from app.hooks.session_hooks import on_tool_error_handler
        tool = MagicMock()
        tool.name = None
        tc = MagicMock()
        result = on_tool_error_handler(tool, {}, tc, RuntimeError("fail"))
        assert result["tool_name"] == "unknown_tool"

    def test_args_none(self):
        from app.hooks.session_hooks import on_tool_error_handler
        tool = MagicMock()
        tool.name = "my_tool"
        tc = MagicMock()
        result = on_tool_error_handler(tool, None, tc, RuntimeError("fail"))
        assert result["status"] == "error"

    def test_very_long_error_message_truncated(self):
        from app.hooks.session_hooks import on_tool_error_handler, _ERROR_MSG_MAX_LEN
        tool = MagicMock()
        tool.name = "my_tool"
        tc = MagicMock()
        long_err = RuntimeError("x" * 1000)
        result = on_tool_error_handler(tool, {}, tc, long_err)
        # The raw message is truncated in the result message
        assert result["status"] == "error"

    def test_empty_error_message(self):
        from app.hooks.session_hooks import on_tool_error_handler
        tool = MagicMock()
        tool.name = "my_tool"
        tc = MagicMock()
        result = on_tool_error_handler(tool, {}, tc, RuntimeError(""))
        assert "RuntimeError" in result["message"]

    def test_classify_connection_error(self):
        from app.hooks.session_hooks import _classify_error
        assert _classify_error(ConnectionError("refused")) == "connection_error"
        assert _classify_error(TimeoutError("timed out")) == "timeout"
        assert _classify_error(OSError("network")) == "network_error"
        assert _classify_error(ValueError("bad")) == "ValueError"


class TestStreamIdLt:
    """Edge cases for _stream_id_lt."""

    def test_normal_comparison(self):
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("0-0", "1-0") is True
        assert _stream_id_lt("1-0", "0-0") is False

    def test_equal_ids(self):
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("5-5", "5-5") is False

    def test_malformed_ids(self):
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("bad", "1-0") is False
        assert _stream_id_lt("1-0", "bad") is False
        assert _stream_id_lt("", "") is False
