"""
Unit tests for the after_tool_callback (after_tool_handler) in session_hooks.py.

Covers:
  - after_tool_handler()    — ADK after_tool_callback that persists args to
                              session state and strips large table rows
  - _strip_large_table_rows — row stripping for any MCP tool response
  - _tcp_keepalive_options  — returns int-keyed dict of available OS socket options
"""

import json
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── helpers ────────────────────────────────────────────────────────────────────

def _tool_response(result_dict: dict) -> dict:
    """Wrap a result dict in the ADK MCP TextContent envelope."""
    return {"content": [{"type": "text", "text": json.dumps(result_dict)}]}


def _mock_tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


# ── _tcp_keepalive_options ─────────────────────────────────────────────────────

class TestTcpKeepaliveOptions:

    def test_returns_dict(self):
        from app.store.redis_session_service import _tcp_keepalive_options
        result = _tcp_keepalive_options()
        assert isinstance(result, dict)

    def test_keys_are_integers(self):
        from app.store.redis_session_service import _tcp_keepalive_options
        opts = _tcp_keepalive_options()
        for key in opts:
            assert isinstance(key, int), f"key {key!r} should be int"

    def test_values_are_positive_integers(self):
        from app.store.redis_session_service import _tcp_keepalive_options
        opts = _tcp_keepalive_options()
        for val in opts.values():
            assert isinstance(val, int) and val > 0

    def test_only_available_options_included(self):
        """No option should be in the dict if the OS does not have the socket constant."""
        from app.store.redis_session_service import _tcp_keepalive_options
        opts = _tcp_keepalive_options()
        known_names = ["TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT"]
        expected_keys = {getattr(socket, n) for n in known_names if hasattr(socket, n)}
        assert set(opts.keys()) == expected_keys

    def test_result_is_json_safe(self):
        """Dict must serialize to JSON without error (used in Redis connection)."""
        from app.store.redis_session_service import _tcp_keepalive_options
        opts = _tcp_keepalive_options()
        json.dumps(opts)  # must not raise


# ── after_tool_handler — generic post-processing ─────────────────────────────

class TestAfterToolHandler:

    _SESSION_ID = "test-session-abc"

    def _make_context(self, call_id: str | None = None) -> MagicMock:
        ctx = MagicMock()
        ctx.state = {}
        ctx._invocation_context.session.id = self._SESSION_ID
        if call_id:
            ctx.function_call_id = call_id
        return ctx

    def _cache_key(self, call_id: str) -> str:
        return f"{self._SESSION_ID}:{call_id}"

    def test_any_tool_returns_none_when_no_table_data(self):
        """Callback is a no-op when tool response has no large table_data."""
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("wcnp_check_app_health")
        result = after_tool_handler(
            tool, {"namespace": "intl-sre", "app": "signal-api"},
            self._make_context(),
            _tool_response({"overall_status": "healthy", "checks": {"cpu": {"status": "healthy"}}})
        )
        assert result is None

    def test_args_persisted_to_state(self):
        """Scalar tool arguments must be persisted to session state."""
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("wcnp_check_app_health")
        ctx = self._make_context()
        after_tool_handler(
            tool, {"namespace": "intl-sre", "app": "signal-api"},
            ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["namespace"] == "intl-sre"
        assert ctx.state["app"] == "signal-api"

    def test_active_context_set_in_state(self):
        """active_context summary must be set after tool call."""
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("some_tool")
        ctx = self._make_context()
        after_tool_handler(
            tool, {"namespace": "prod", "app": "cart-svc"},
            ctx,
            _tool_response({"status": "ok"})
        )
        assert "some_tool" in ctx.state["active_context"]
        assert "namespace=prod" in ctx.state["active_context"]

    def test_get_mcp_prompt_args_not_persisted(self):
        """get_mcp_prompt tool args must NOT be persisted to state."""
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("get_mcp_prompt")
        ctx = self._make_context()
        after_tool_handler(
            tool, {"name": "rca-investigate", "arguments": "{}"},
            ctx,
            _tool_response({"content": "workflow steps"})
        )
        assert "name" not in ctx.state

    def test_strips_large_table_rows(self):
        """Responses with >50 rows in table_data must have rows stripped."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        tool = _mock_tool("any_mcp_tool")
        call_id = "test-call-123"
        ctx = self._make_context(call_id=call_id)

        big_rows = [{"col": i} for i in range(60)]
        response = _tool_response({
            "summary": "data",
            "table_data": {"columns": ["col"], "rows": big_rows},
        })

        result = after_tool_handler(tool, {}, ctx, response)

        assert result is not None, "should return enriched response when rows stripped"
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["table_data"]["rows"] == []
        assert parsed["table_data"]["_rows_stripped"] is True
        ck = self._cache_key(call_id)
        assert ck in TABLE_ROW_CACHE
        assert len(TABLE_ROW_CACHE[ck]["table_data"]["rows"]) == 60
        assert "_ts" in TABLE_ROW_CACHE[ck]

        # cleanup
        del TABLE_ROW_CACHE[ck]

    def test_small_table_not_stripped(self):
        """Responses with <=50 rows must NOT be stripped."""
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("any_mcp_tool")
        ctx = self._make_context(call_id="test-call-small")

        small_rows = [{"col": i} for i in range(10)]
        response = _tool_response({
            "summary": "data",
            "table_data": {"columns": ["col"], "rows": small_rows},
        })

        result = after_tool_handler(tool, {}, ctx, response)
        assert result is None, "small table should not trigger row stripping"

    def test_works_for_non_health_tools(self):
        """Row stripping must work for ANY tool, not just health tools."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        tool = _mock_tool("fetch_incident_details")
        call_id = "incident-call-456"
        ctx = self._make_context(call_id=call_id)

        big_rows = [{"inc": i} for i in range(100)]
        response = _tool_response({
            "incident": "INC123",
            "table_data": {"columns": ["inc"], "rows": big_rows},
        })

        result = after_tool_handler(tool, {"incident_id": "INC123"}, ctx, response)

        assert result is not None
        ck = self._cache_key(call_id)
        assert ck in TABLE_ROW_CACHE
        assert ctx.state["incident_id"] == "INC123"

        # cleanup
        del TABLE_ROW_CACHE[ck]

    def test_malformed_response_returns_none_silently(self):
        """Malformed tool response must not raise — returns None gracefully."""
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("any_tool")
        bad_responses = [
            {},
            {"content": []},
            {"content": [{"type": "text", "text": "not json"}]},
            {"content": [{"type": "image"}]},
        ]
        for bad in bad_responses:
            result = after_tool_handler(tool, {}, self._make_context(), bad)
            assert result is None, f"Expected None for {bad}"

    def test_health_tool_anomaly_not_intercepted(self):
        """Health tool anomalies must NOT be intercepted — LLM handles via agent-guide.

        The Super Agent is a generic orchestrator.  Health-mcp's agent-guide
        tells the LLM to call ``rca-investigate`` when anomalies are detected.
        The after_tool_handler must NOT inject directives or parse health schemas.
        """
        from app.hooks.session_hooks import after_tool_handler
        tool = _mock_tool("wcnp_check_app_health")
        health_result = {
            "overall_status": "unhealthy",
            "checks": {
                "istio_client_latency": {
                    "anomaly_detected": True,
                    "episode_start": "2026-03-15T21:00:00Z",
                    "still_active": True,
                    "peak_value": 5200,
                }
            }
        }
        result = after_tool_handler(
            tool,
            {"namespace": "intl-sre", "app": "signal-api"},
            self._make_context(),
            _tool_response(health_result),
        )
        # No directive injection — result is None (no table rows to strip)
        assert result is None
        # Verify no "ANOMALY DETECTED" directive was injected
        # (the old handle_health_check_result would have returned enriched response)


# ── Edge cases and boundary tests ─────────────────────────────────────────────

class TestAfterToolHandlerEdgeCases:
    """Exhaustive edge-case and negative tests for after_tool_handler.

    The Super Agent callback must NEVER crash regardless of input.
    Every edge case returns None or a valid enriched response.
    """

    _SESSION_ID = "edge-session-xyz"

    def _make_context(self, call_id: str | None = None) -> MagicMock:
        ctx = MagicMock()
        ctx.state = {}
        ctx._invocation_context.session.id = self._SESSION_ID
        if call_id:
            ctx.function_call_id = call_id
        else:
            # Simulate missing attribute — getattr with default returns None
            del ctx.function_call_id
        return ctx

    def _cache_key(self, call_id: str) -> str:
        return f"{self._SESSION_ID}:{call_id}"

    # ── tool_response shape edge cases ────────────────────────────────────────

    def test_tool_response_is_none(self):
        """tool_response=None must not crash — returns None."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), None)
        assert result is None

    def test_tool_response_is_string(self):
        """tool_response as raw string (not dict) must not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), "raw string")
        assert result is None

    def test_tool_response_is_list(self):
        """tool_response as list must not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), [1, 2, 3])
        assert result is None

    def test_tool_response_is_integer(self):
        """tool_response as integer must not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), 42)
        assert result is None

    def test_content_is_none(self):
        """content=None inside tool_response must not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), {"content": None})
        assert result is None

    def test_content_is_string(self):
        """content as string (not list) must not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), {"content": "text"})
        assert result is None

    def test_content_empty_list(self):
        """Empty content list — no text to parse."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), {"content": []})
        assert result is None

    def test_content_first_item_is_string(self):
        """content[0] is a string instead of dict — must not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), {"content": ["raw"]})
        assert result is None

    def test_content_first_item_missing_text_key(self):
        """content[0] is a dict without 'text' key."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(), {"content": [{"type": "image"}]}
        )
        assert result is None

    def test_content_text_is_empty_string(self):
        """content[0].text is empty string — no JSON to parse."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(), {"content": [{"text": ""}]}
        )
        assert result is None

    def test_content_text_is_whitespace_only(self):
        """content[0].text is whitespace — not valid JSON but should not crash."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(), {"content": [{"text": "   "}]}
        )
        assert result is None

    # ── JSON parsing edge cases ───────────────────────────────────────────────

    def test_json_array_response_returns_none(self):
        """Valid JSON but array (not dict) — no table_data possible, returns None."""
        from app.hooks.session_hooks import after_tool_handler
        response = {"content": [{"text": json.dumps([1, 2, 3])}]}
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), response)
        assert result is None

    def test_json_string_response_returns_none(self):
        """Valid JSON but a quoted string — not dict, returns None."""
        from app.hooks.session_hooks import after_tool_handler
        response = {"content": [{"text": json.dumps("hello")}]}
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), response)
        assert result is None

    def test_json_number_response_returns_none(self):
        """Valid JSON but a number — not dict, returns None."""
        from app.hooks.session_hooks import after_tool_handler
        response = {"content": [{"text": "42"}]}
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), response)
        assert result is None

    def test_json_null_response_returns_none(self):
        """Valid JSON null — not dict, returns None."""
        from app.hooks.session_hooks import after_tool_handler
        response = {"content": [{"text": "null"}]}
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), response)
        assert result is None

    def test_json_boolean_response_returns_none(self):
        """Valid JSON boolean — not dict, returns None."""
        from app.hooks.session_hooks import after_tool_handler
        response = {"content": [{"text": "true"}]}
        result = after_tool_handler(_mock_tool("t"), {}, self._make_context(), response)
        assert result is None

    # ── table_data shape edge cases ───────────────────────────────────────────

    def test_table_data_is_string(self):
        """table_data is a string, not dict — must not strip."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="c1"),
            _tool_response({"table_data": "not a dict"})
        )
        assert result is None

    def test_table_data_is_list(self):
        """table_data is a list — must not strip."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="c1"),
            _tool_response({"table_data": [1, 2, 3]})
        )
        assert result is None

    def test_table_data_rows_is_none(self):
        """table_data.rows is None — must not strip (falsy → 0 length)."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="c1"),
            _tool_response({"table_data": {"columns": ["a"], "rows": None}})
        )
        assert result is None

    def test_table_data_missing_rows_key(self):
        """table_data has no 'rows' key — must not strip."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="c1"),
            _tool_response({"table_data": {"columns": ["a"]}})
        )
        assert result is None

    def test_table_data_rows_empty_list(self):
        """table_data.rows is [] — below threshold, not stripped."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="c1"),
            _tool_response({"table_data": {"columns": ["a"], "rows": []}})
        )
        assert result is None

    # ── Boundary: exactly 50 rows (threshold) vs 51 ──────────────────────────

    def test_exactly_50_rows_not_stripped(self):
        """Exactly 50 rows — at threshold, NOT stripped (> 50 required)."""
        from app.hooks.session_hooks import after_tool_handler
        rows = [{"x": i} for i in range(50)]
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="boundary-50"),
            _tool_response({"table_data": {"columns": ["x"], "rows": rows}})
        )
        assert result is None

    def test_exactly_51_rows_stripped(self):
        """Exactly 51 rows — above threshold, MUST be stripped."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        call_id = "boundary-51"
        ck = self._cache_key(call_id)
        rows = [{"x": i} for i in range(51)]
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response({"table_data": {"columns": ["x"], "rows": rows}})
        )
        assert result is not None
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["table_data"]["rows"] == []
        assert parsed["table_data"]["_rows_stripped"] is True
        assert ck in TABLE_ROW_CACHE
        assert len(TABLE_ROW_CACHE[ck]["table_data"]["rows"]) == 51
        del TABLE_ROW_CACHE[ck]

    # ── call_id edge cases ────────────────────────────────────────────────────

    def test_no_call_id_large_table_not_stripped(self):
        """Large table but call_id is None — cannot cache, must NOT strip."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        ctx = self._make_context()  # no call_id
        rows = [{"x": i} for i in range(100)]
        result = after_tool_handler(
            _mock_tool("t"), {}, ctx,
            _tool_response({"table_data": {"columns": ["x"], "rows": rows}})
        )
        assert result is None
        # Verify nothing was cached with None key
        assert None not in TABLE_ROW_CACHE

    def test_empty_string_call_id_not_stripped(self):
        """call_id is empty string — falsy, must NOT strip."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        ctx = MagicMock()
        ctx.state = {}
        ctx.function_call_id = ""
        rows = [{"x": i} for i in range(100)]
        result = after_tool_handler(
            _mock_tool("t"), {}, ctx,
            _tool_response({"table_data": {"columns": ["x"], "rows": rows}})
        )
        assert result is None
        assert "" not in TABLE_ROW_CACHE

    # ── _save_args_to_state robustness ────────────────────────────────────────

    def test_args_is_none_does_not_crash(self):
        """args=None must not crash — wrapped in try/except with `or {}`."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), None, self._make_context(),
            _tool_response({"status": "ok"})
        )
        assert result is None

    def test_tool_name_attribute_error_does_not_crash(self):
        """tool.name raises AttributeError — callback must not propagate."""
        from app.hooks.session_hooks import after_tool_handler
        tool = MagicMock()
        del tool.name  # accessing tool.name will raise AttributeError
        result = after_tool_handler(
            tool, {"a": "b"}, self._make_context(),
            _tool_response({"status": "ok"})
        )
        # Must not crash — returns None (state save failed gracefully,
        # but json.loads + strip still works)
        assert result is None

    def test_state_assignment_raises_does_not_crash(self):
        """tool_context.state that rejects assignment must not crash callback."""
        from app.hooks.session_hooks import after_tool_handler

        class ReadOnlyState:
            def __setitem__(self, key, value):
                raise TypeError("read-only state")
            def __contains__(self, item):
                return False

        ctx = MagicMock()
        ctx.state = ReadOnlyState()
        result = after_tool_handler(
            _mock_tool("t"), {"ns": "prod"}, ctx,
            _tool_response({"status": "ok"})
        )
        # _save_args_to_state crashes, but it's caught — rest continues
        assert result is None

    def test_args_with_non_scalar_values_skipped(self):
        """Non-scalar args (list, dict, None) must be skipped, not persisted."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("t"),
            {"name": "app1", "tags": ["a", "b"], "meta": {"k": "v"}, "empty": None, "flag": True},
            ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["name"] == "app1"
        assert ctx.state["flag"] is True
        assert "tags" not in ctx.state
        assert "meta" not in ctx.state
        # None is not a scalar type (str/int/float/bool)
        assert "empty" not in ctx.state

    def test_empty_string_args_not_persisted(self):
        """Args with empty string value must be skipped."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("t"), {"ns": "", "app": "cart"}, ctx,
            _tool_response({"status": "ok"})
        )
        assert "ns" not in ctx.state
        assert ctx.state["app"] == "cart"

    def test_summary_exclude_keys_not_in_active_context(self):
        """Keys in _SUMMARY_EXCLUDE must be persisted to state but excluded from active_context."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("t"),
            {"app": "cart", "analysis_start_epoch": 1234567890, "checks": "cpu,mem"},
            ctx,
            _tool_response({"status": "ok"})
        )
        # All scalar args persisted to state
        assert ctx.state["app"] == "cart"
        assert ctx.state["analysis_start_epoch"] == 1234567890
        assert ctx.state["checks"] == "cpu,mem"
        # But active_context only mentions non-excluded keys
        assert "app=cart" in ctx.state["active_context"]
        assert "analysis_start_epoch" not in ctx.state["active_context"]
        assert "checks" not in ctx.state["active_context"]

    # ── Multiple content items ────────────────────────────────────────────────

    # ── Session isolation tests ─────────────────────────────────────────────

    def test_different_sessions_same_call_id_no_leakage(self):
        """Two sessions with identical call_id must NOT share cached data."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE

        call_id = "shared-call-id"
        rows_a = [{"user": "A", "x": i} for i in range(60)]
        rows_b = [{"user": "B", "x": i} for i in range(70)]

        # Session A
        ctx_a = MagicMock()
        ctx_a.state = {}
        ctx_a._invocation_context.session.id = "session-user-A"
        ctx_a.function_call_id = call_id
        after_tool_handler(
            _mock_tool("t"), {}, ctx_a,
            _tool_response({"table_data": {"columns": ["x"], "rows": rows_a}})
        )

        # Session B — same call_id, different session
        ctx_b = MagicMock()
        ctx_b.state = {}
        ctx_b._invocation_context.session.id = "session-user-B"
        ctx_b.function_call_id = call_id
        after_tool_handler(
            _mock_tool("t"), {}, ctx_b,
            _tool_response({"table_data": {"columns": ["x"], "rows": rows_b}})
        )

        # Both entries exist independently
        key_a = "session-user-A:shared-call-id"
        key_b = "session-user-B:shared-call-id"
        assert key_a in TABLE_ROW_CACHE
        assert key_b in TABLE_ROW_CACHE
        assert len(TABLE_ROW_CACHE[key_a]["table_data"]["rows"]) == 60
        assert len(TABLE_ROW_CACHE[key_b]["table_data"]["rows"]) == 70
        assert TABLE_ROW_CACHE[key_a]["table_data"]["rows"][0]["user"] == "A"
        assert TABLE_ROW_CACHE[key_b]["table_data"]["rows"][0]["user"] == "B"

        # cleanup
        del TABLE_ROW_CACHE[key_a]
        del TABLE_ROW_CACHE[key_b]

    def test_cache_entry_has_timestamp(self):
        """Every cache entry must include a monotonic _ts for TTL eviction."""
        import time
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE

        call_id = "ts-test"
        ck = self._cache_key(call_id)
        before = time.monotonic()
        after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response({"table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(60)]}})
        )
        after = time.monotonic()

        assert ck in TABLE_ROW_CACHE
        ts = TABLE_ROW_CACHE[ck]["_ts"]
        assert before <= ts <= after
        del TABLE_ROW_CACHE[ck]

    def test_stale_entries_evicted_on_write(self):
        """Entries older than _CACHE_TTL_SECONDS are evicted when a new entry is written."""
        import time
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE, _CACHE_TTL_SECONDS

        # Manually insert a stale entry with old timestamp
        stale_key = "stale-session:stale-call"
        TABLE_ROW_CACHE[stale_key] = {
            "table_data": {"rows": [{"old": True}]},
            "_ts": time.monotonic() - _CACHE_TTL_SECONDS - 10,  # expired
        }

        # Trigger a new write that will run eviction
        call_id = "trigger-eviction"
        ck = self._cache_key(call_id)
        after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response({"table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(60)]}})
        )

        assert stale_key not in TABLE_ROW_CACHE, "stale entry should have been evicted"
        assert ck in TABLE_ROW_CACHE
        del TABLE_ROW_CACHE[ck]

    def test_table_row_cache_key_format(self):
        """table_row_cache_key must produce 'session_id:call_id' format."""
        from app.hooks.session_hooks import table_row_cache_key
        assert table_row_cache_key("sess-123", "call-456") == "sess-123:call-456"
        assert table_row_cache_key("", "call") == ":call"
        assert table_row_cache_key("sess", "") == "sess:"

    def test_session_unavailable_falls_back_to_call_id(self):
        """If _invocation_context.session.id raises, call_id alone is used as fallback."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE

        class _BrokenInvCtx:
            @property
            def session(self):
                raise AttributeError("no session attached")

        ctx = MagicMock()
        ctx.state = {}
        ctx.function_call_id = "fallback-test"
        ctx._invocation_context = _BrokenInvCtx()

        rows = [{"x": i} for i in range(60)]
        result = after_tool_handler(
            _mock_tool("t"), {}, ctx,
            _tool_response({"table_data": {"columns": ["x"], "rows": rows}})
        )
        assert result is not None
        # Fallback: bare call_id used as cache key
        assert "fallback-test" in TABLE_ROW_CACHE
        del TABLE_ROW_CACHE["fallback-test"]

    def test_only_first_content_item_parsed(self):
        """Only the first content item is checked — second large table is ignored."""
        from app.hooks.session_hooks import after_tool_handler
        big_rows = [{"x": i} for i in range(100)]
        response = {
            "content": [
                {"type": "text", "text": json.dumps({"status": "ok"})},
                {"type": "text", "text": json.dumps({"table_data": {"rows": big_rows}})},
            ]
        }
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="multi"),
            response
        )
        # First item has no large table → None
        assert result is None

    # ── Falsy-but-valid scalar values ────────────────────────────────────────

    def test_integer_zero_persisted_to_state(self):
        """Integer 0 is a valid scalar — must be persisted, not treated as empty."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("t"), {"retries": 0, "app": "cart"}, ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["retries"] == 0
        assert ctx.state["app"] == "cart"

    def test_bool_false_persisted_to_state(self):
        """Bool False is a valid scalar — must be persisted, not treated as empty."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("t"), {"verbose": False, "app": "cart"}, ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["verbose"] is False
        assert ctx.state["app"] == "cart"

    def test_float_zero_persisted_to_state(self):
        """Float 0.0 is a valid scalar — must be persisted."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("t"), {"threshold": 0.0}, ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["threshold"] == 0.0

    # ── Same session overwrites cache on second call ─────────────────────────

    def test_same_session_second_call_overwrites_cache(self):
        """Second strip for same session+call_id must overwrite the first cache entry."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        call_id = "overwrite-test"
        ck = self._cache_key(call_id)

        # First call — 60 rows
        after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response({"table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(60)]}})
        )
        assert len(TABLE_ROW_CACHE[ck]["table_data"]["rows"]) == 60

        # Second call — 80 rows, same key
        after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response({"table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(80)]}})
        )
        assert len(TABLE_ROW_CACHE[ck]["table_data"]["rows"]) == 80

        del TABLE_ROW_CACHE[ck]

    # ── Cache max entries eviction ───────────────────────────────────────────

    def test_cache_max_entries_evicts_oldest(self):
        """When cache hits _CACHE_MAX_ENTRIES, the oldest entry must be evicted."""
        import time
        from app.hooks.session_hooks import (
            after_tool_handler, TABLE_ROW_CACHE,
            _CACHE_MAX_ENTRIES,
        )

        # Save and restore cache state to avoid polluting other tests
        saved_cache = dict(TABLE_ROW_CACHE)
        TABLE_ROW_CACHE.clear()

        try:
            # Fill cache to max with synthetic entries
            base_ts = time.monotonic()
            for i in range(_CACHE_MAX_ENTRIES):
                TABLE_ROW_CACHE[f"fill-session:{i}"] = {
                    "table_data": {"rows": [{"v": 1}]},
                    "_ts": base_ts + i,  # increasing timestamps
                }
            assert len(TABLE_ROW_CACHE) == _CACHE_MAX_ENTRIES

            # One more write — must evict the oldest (fill-session:0)
            call_id = "overflow"
            ck = self._cache_key(call_id)
            after_tool_handler(
                _mock_tool("t"), {}, self._make_context(call_id=call_id),
                _tool_response({"table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(60)]}})
            )

            assert ck in TABLE_ROW_CACHE
            assert "fill-session:0" not in TABLE_ROW_CACHE, "oldest entry should have been evicted"
            # Total entries: _CACHE_MAX_ENTRIES (evicted 1, added 1)
            assert len(TABLE_ROW_CACHE) == _CACHE_MAX_ENTRIES
        finally:
            TABLE_ROW_CACHE.clear()
            TABLE_ROW_CACHE.update(saved_cache)

    # ── Eviction of entries missing _ts ───────────────────────────────────────

    def test_entry_missing_ts_treated_as_stale(self):
        """Cache entry without _ts key is treated as infinitely old and evicted."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE

        # Insert entry with no _ts — will default to 0 in eviction check
        bad_key = "no-ts-session:no-ts-call"
        TABLE_ROW_CACHE[bad_key] = {"table_data": {"rows": [{"old": True}]}}

        # Trigger write → eviction runs → entry with _ts=0 is ancient → evicted
        call_id = "trigger-ts-eviction"
        ck = self._cache_key(call_id)
        after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response({"table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(60)]}})
        )

        assert bad_key not in TABLE_ROW_CACHE, "entry without _ts should be evicted"
        assert ck in TABLE_ROW_CACHE
        del TABLE_ROW_CACHE[ck]

    # ── Nested table_data (not at top level) ─────────────────────────────────

    def test_nested_table_data_not_stripped(self):
        """table_data nested inside another key is NOT stripped — only top-level."""
        from app.hooks.session_hooks import after_tool_handler
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id="nested"),
            _tool_response({
                "summary": "ok",
                "details": {
                    "table_data": {"columns": ["x"], "rows": [{"x": i} for i in range(100)]}
                }
            })
        )
        assert result is None  # nested table_data not detected

    # ── tool_response original not mutated ───────────────────────────────────

    def test_original_tool_response_not_mutated(self):
        """after_tool_handler must NOT mutate the original tool_response dict."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        call_id = "no-mutate"
        ck = self._cache_key(call_id)
        big_rows = [{"x": i} for i in range(60)]
        original_response = _tool_response({
            "table_data": {"columns": ["x"], "rows": big_rows}
        })
        # Deep-copy the original text for comparison
        original_text = original_response["content"][0]["text"]

        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            original_response
        )
        assert result is not None
        # Original response text must NOT have been modified
        assert original_response["content"][0]["text"] == original_text
        # The returned enriched response must have DIFFERENT text
        assert result["content"][0]["text"] != original_text
        del TABLE_ROW_CACHE[ck]

    # ── Multiple arg-only calls don't accumulate state pollution ──────────────

    def test_different_tools_overwrite_same_arg_key(self):
        """When two tools use the same arg name (e.g. 'app'), second call wins."""
        from app.hooks.session_hooks import after_tool_handler
        ctx = self._make_context()
        after_tool_handler(
            _mock_tool("tool_a"), {"app": "service-1"}, ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["app"] == "service-1"
        assert "tool_a" in ctx.state["active_context"]

        after_tool_handler(
            _mock_tool("tool_b"), {"app": "service-2"}, ctx,
            _tool_response({"status": "ok"})
        )
        assert ctx.state["app"] == "service-2"
        assert "tool_b" in ctx.state["active_context"]

    # ── Cache contract with runner.py ─────────────────────────────────────────

    def test_stripped_response_preserves_non_table_fields(self):
        """When rows are stripped, all other fields in the response must be preserved."""
        from app.hooks.session_hooks import after_tool_handler, TABLE_ROW_CACHE
        call_id = "preserve-fields"
        ck = self._cache_key(call_id)
        rows = [{"x": i} for i in range(60)]
        original = {
            "summary": "health report",
            "overall_status": "unhealthy",
            "table_data": {"columns": ["x"], "rows": rows, "title": "Metrics"},
        }
        result = after_tool_handler(
            _mock_tool("t"), {}, self._make_context(call_id=call_id),
            _tool_response(original)
        )
        assert result is not None
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["summary"] == "health report"
        assert parsed["overall_status"] == "unhealthy"
        assert parsed["table_data"]["columns"] == ["x"]
        assert parsed["table_data"]["title"] == "Metrics"
        assert parsed["table_data"]["rows"] == []
        assert parsed["table_data"]["_rows_stripped"] is True
        # Cache has the FULL table_data including rows, plus _ts
        cached = TABLE_ROW_CACHE[ck]
        assert len(cached["table_data"]["rows"]) == 60
        assert cached["table_data"]["title"] == "Metrics"
        assert "_ts" in cached
        del TABLE_ROW_CACHE[ck]


# ── call_prompt (MCPSession + MCPPool) ────────────────────────────────────────

class TestMCPSessionCallPrompt:

    @pytest.mark.asyncio
    async def test_call_prompt_returns_rendered_text(self):
        """call_prompt should extract and join text from messages array."""
        from app.mcp.client import MCPSession

        client = MagicMock()

        async def fake_post(url, **kwargs):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.json = MagicMock(return_value={
                "result": {
                    "messages": [
                        {"role": "user", "content": {"type": "text", "text": "Step 1: Check CPU."}},
                        {"role": "user", "content": {"type": "text", "text": "Step 2: Check memory."}},
                    ]
                }
            })
            r.headers = {}
            r.text = MagicMock(return_value='{"result": {}}')
            return r

        client.post = fake_post
        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_prompt("wcnp-full-triage", {"namespace": "intl-sre", "app": "signal-api"})
        assert "Step 1: Check CPU." in result
        assert "Step 2: Check memory." in result

    @pytest.mark.asyncio
    async def test_call_prompt_returns_error_message_on_failure(self):
        """call_prompt must not raise on error — returns an error string instead."""
        from app.mcp.client import MCPSession

        client = MagicMock()

        async def fake_post(url, **kwargs):
            raise ConnectionError("connection refused")

        client.post = fake_post
        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_prompt("wcnp-full-triage")
        assert "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_call_prompt_passes_arguments(self):
        """Arguments passed to call_prompt must appear in the RPC request."""
        from app.mcp.client import MCPSession

        captured_body = {}

        async def fake_post(url, json=None, **kwargs):
            if json:
                captured_body.update(json)
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.json = MagicMock(return_value={"result": {"messages": []}})
            r.headers = {}
            r.text = MagicMock(return_value='{"result": {}}')
            return r

        client = MagicMock()
        client.post = fake_post
        session = MCPSession(client, "http://mcp.example.com/mcp")
        await session.call_prompt("wcnp-cpu-usage", {"namespace": "intl-sre", "app": "signal-api"})
        assert captured_body.get("params", {}).get("name") == "wcnp-cpu-usage"
        assert captured_body["params"]["arguments"]["namespace"] == "intl-sre"


class TestMCPPoolCallPrompt:

    @pytest.mark.asyncio
    async def test_pool_call_prompt_uses_first_responding_session(self):
        """MCPPool.call_prompt should return the first non-error response."""
        from app.mcp.client import MCPPool, MCPSession
        from unittest.mock import AsyncMock

        s1 = MagicMock(spec=MCPSession)
        s1._name = "health-mcp"
        s1.call_prompt = AsyncMock(return_value="Prompt unavailable: error")

        s2 = MagicMock(spec=MCPSession)
        s2._name = "wcnp-mcp"
        s2.call_prompt = AsyncMock(return_value="Step 1: Run CPU query.")

        pool = MCPPool([s1, s2])
        pool.failed_servers = []

        result = await pool.call_prompt("wcnp-cpu-usage", {"namespace": "ns"})
        assert "Step 1" in result

    @pytest.mark.asyncio
    async def test_pool_call_prompt_skips_failed_servers(self):
        """MCPPool.call_prompt must not call sessions listed in failed_servers."""
        from app.mcp.client import MCPPool, MCPSession
        from unittest.mock import AsyncMock

        s1 = MagicMock(spec=MCPSession)
        s1._name = "broken-mcp"
        s1.call_prompt = AsyncMock(return_value="should not be called")

        s2 = MagicMock(spec=MCPSession)
        s2._name = "good-mcp"
        s2.call_prompt = AsyncMock(return_value="Good prompt content.")

        pool = MCPPool([s1, s2])
        pool.failed_servers = [{"name": "broken-mcp"}]

        result = await pool.call_prompt("test-prompt")
        s1.call_prompt.assert_not_called()
        assert "Good prompt content." in result

    @pytest.mark.asyncio
    async def test_pool_call_prompt_returns_not_found_when_all_fail(self):
        """When no session responds successfully, return a clear 'not found' message."""
        from app.mcp.client import MCPPool, MCPSession
        from unittest.mock import AsyncMock

        s1 = MagicMock(spec=MCPSession)
        s1._name = "s1"
        s1.call_prompt = AsyncMock(return_value="Prompt unavailable: timeout")

        pool = MCPPool([s1])
        pool.failed_servers = []

        result = await pool.call_prompt("unknown-prompt")
        assert "not found" in result.lower() or "unavailable" in result.lower()


# ── make_agent with guide injection ───────────────────────────────────────────

class TestMakeAgentInstructionInjection:

    def test_instruction_loaded_from_file(self, tmp_path):
        """_load_from_file reads from AGENT_INSTRUCTION.md when it exists."""
        import app.services.agent_instruction as ai_mod
        original_file = ai_mod._INSTRUCTION_FILE
        try:
            resources = tmp_path / "resources"
            resources.mkdir()
            (resources / "AGENT_INSTRUCTION.md").write_text("You are a test agent.")
            ai_mod._INSTRUCTION_FILE = resources / "AGENT_INSTRUCTION.md"
            instruction = ai_mod._load_from_file()
            assert "You are a test agent." in instruction
        finally:
            ai_mod._INSTRUCTION_FILE = original_file

    def test_fallback_when_file_missing(self, tmp_path):
        """_load_from_file returns hardcoded fallback when file is absent."""
        import app.services.agent_instruction as ai_mod
        original_file = ai_mod._INSTRUCTION_FILE
        try:
            ai_mod._INSTRUCTION_FILE = tmp_path / "nonexistent.md"
            instruction = ai_mod._load_from_file()
            assert len(instruction) > 0
            assert "health" in instruction.lower() or "assistant" in instruction.lower()
        finally:
            ai_mod._INSTRUCTION_FILE = original_file

    def test_guide_combined_with_base_instruction(self, tmp_path):
        """_load_from_file + guide produces combined instruction."""
        import app.services.agent_instruction as ai_mod
        original_file = ai_mod._INSTRUCTION_FILE
        try:
            resources = tmp_path / "resources"
            resources.mkdir()
            (resources / "AGENT_INSTRUCTION.md").write_text("Base instruction.")
            ai_mod._INSTRUCTION_FILE = resources / "AGENT_INSTRUCTION.md"

            base = ai_mod._load_from_file()
            guide = "## Tool Guide\n- Use wcnp_check_app_health for health checks."
            combined = f"{base}\n\n---\n\n{guide}"

            assert "Base instruction." in combined
            assert "## Tool Guide" in combined
            assert "wcnp_check_app_health" in combined
        finally:
            ai_mod._INSTRUCTION_FILE = original_file

    @pytest.mark.asyncio
    async def test_make_agent_builds_instruction_with_guide(self):
        """make_agent injects guide into the Agent's instruction string."""
        import agent as agent_mod
        from unittest.mock import patch, AsyncMock
        guide = "## Domain Guide\n- Use wcnp tools."
        with patch.object(agent_mod, "load_agent_instruction",
                          new_callable=AsyncMock, return_value="Base instruction."):
            agent = await agent_mod.make_agent([], guide=guide, mcp_pool=None)
        assert "Base instruction." in agent.instruction
        assert "## Domain Guide" in agent.instruction

    @pytest.mark.asyncio
    async def test_make_agent_without_guide_uses_base_only(self, monkeypatch):
        """Without a guide, make_agent uses only the base instruction (A2UI disabled)."""
        import agent as agent_mod
        from unittest.mock import patch, AsyncMock
        monkeypatch.setenv("A2UI_ENABLED", "false")
        with patch.object(agent_mod, "load_agent_instruction",
                          new_callable=AsyncMock, return_value="Just the base."):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)
        assert "Just the base." in agent.instruction
        assert "## Domain Guide" not in agent.instruction

    @pytest.mark.asyncio
    async def test_make_agent_adds_get_mcp_prompt_when_pool_given(self):
        """get_mcp_prompt callable is added to tools when mcp_pool is provided."""
        import agent as agent_mod
        from unittest.mock import patch, AsyncMock
        with patch.object(agent_mod, "load_agent_instruction",
                          new_callable=AsyncMock, return_value="Base."):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=MagicMock())
        tool_names = [getattr(t, "__name__", "") for t in agent.tools]
        assert any("prompt" in n.lower() for n in tool_names), \
            f"get_mcp_prompt not found in: {tool_names}"

    @pytest.mark.asyncio
    async def test_make_agent_no_prompt_tool_without_pool(self):
        """Without mcp_pool, no extra get_mcp_prompt tool is added."""
        import agent as agent_mod
        from unittest.mock import patch, AsyncMock
        with patch.object(agent_mod, "load_agent_instruction",
                          new_callable=AsyncMock, return_value="Base."):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)
        tool_names = [getattr(t, "__name__", "") for t in agent.tools]
        assert not any("prompt" in n.lower() for n in tool_names)
