"""Comprehensive tests for event emission patterns in runner.py.

Covers:
  - _sse() formatting
  - _persist() fire-and-forget semantics
  - Event bridge lifecycle (init / push / teardown)
  - _drain_llm_events() async generator
  - Event emission ordering in run_agent_with_events()
  - Edge cases (unicode, overflow, NaN, empty query, etc.)
"""

import asyncio
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers to build mock ADK events
# ---------------------------------------------------------------------------

def _make_part(text=None, thought=None, function_call=None, function_response=None):
    """Build a mock Part with the attributes runner.py inspects."""
    p = MagicMock()
    # text
    if text is not None:
        p.text = text
    else:
        p.text = None
    # thought flag
    p.thought = thought
    # function_call / function_response
    if function_call is not None:
        p.function_call = function_call
    else:
        p.function_call = None
    if function_response is not None:
        p.function_response = function_response
    else:
        p.function_response = None
    return p


def _make_event(parts, is_final=False):
    """Build a mock ADK Event."""
    ev = MagicMock()
    content = MagicMock()
    content.parts = parts
    ev.content = content
    ev.is_final_response = MagicMock(return_value=is_final)
    return ev


def _make_function_call(name, call_id=None, args=None):
    fc = MagicMock()
    fc.name = name
    fc.id = call_id or name
    fc.args = args
    return fc


def _make_function_response(name, call_id=None, response=None):
    fr = MagicMock()
    fr.name = name
    fr.id = call_id or name
    fr.response = response
    return fr


def _mock_runner(events_sequence, session_exists=True):
    """Build a mock runner that yields the given events from run_async."""
    async def _fake_run_async(**kwargs):
        for ev in events_sequence:
            yield ev

    runner = MagicMock()
    runner.app_name = "test_app"
    runner.run_async = _fake_run_async

    redis_mock = AsyncMock()
    redis_mock.rpush = AsyncMock()
    redis_mock.expire = AsyncMock()

    runner.session_service = MagicMock()
    runner.session_service._redis = redis_mock
    runner.session_service._ttl = 3600

    if session_exists:
        runner.session_service.get_session = AsyncMock(return_value=MagicMock())
    else:
        runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()

    return runner


async def _collect(async_gen):
    """Collect all items from an async generator."""
    items = []
    async for item in async_gen:
        items.append(item)
    return items


def _parse_sse(sse_line: str) -> dict:
    """Parse 'data: {...}\n\n' into a dict."""
    assert sse_line.startswith("data: "), f"Not SSE format: {sse_line!r}"
    assert sse_line.endswith("\n\n"), f"Missing trailing newlines: {sse_line!r}"
    return json.loads(sse_line[6:-2])


# ═══════════════════════════════════════════════════════════════════════════
# _sse() FORMAT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSseFormat:
    """Tests for the _sse() inner function formatting."""

    def _sse(self, data: dict) -> str:
        """Mirror the runner's _sse closure."""
        return f"data: {json.dumps(data)}\n\n"

    def test_simple_dict(self):
        result = self._sse({"type": "test"})
        assert result == 'data: {"type": "test"}\n\n'

    def test_unicode_values(self):
        result = self._sse({"type": "test", "text": "Hello \u4e16\u754c \U0001f680"})
        parsed = _parse_sse(result)
        assert parsed["text"] == "Hello \u4e16\u754c \U0001f680"

    def test_nested_objects(self):
        data = {"type": "graph", "args": {"labels": ["a", "b"], "datasets": [{"data": [1, 2]}]}}
        result = self._sse(data)
        parsed = _parse_sse(result)
        assert parsed["args"]["datasets"][0]["data"] == [1, 2]

    def test_empty_dict(self):
        result = self._sse({})
        assert result == "data: {}\n\n"

    def test_special_json_chars(self):
        data = {"text": 'He said "hello\\world"'}
        result = self._sse(data)
        parsed = _parse_sse(result)
        assert parsed["text"] == 'He said "hello\\world"'

    def test_large_dict(self):
        data = {"text": "x" * 50_000}
        result = self._sse(data)
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        parsed = _parse_sse(result)
        assert len(parsed["text"]) == 50_000

    def test_none_values(self):
        data = {"type": "test", "value": None}
        result = self._sse(data)
        parsed = _parse_sse(result)
        assert parsed["value"] is None

    def test_nan_sanitized_upstream(self):
        """NaN/Inf should be sanitized before _sse; _sanitize_floats does this."""
        from app.services.runner import _sanitize_floats
        data = {"val": float("nan"), "inf": float("inf")}
        sanitized = _sanitize_floats(data)
        result = self._sse(sanitized)
        parsed = _parse_sse(result)
        assert parsed["val"] is None
        assert parsed["inf"] is None


# ═══════════════════════════════════════════════════════════════════════════
# _persist() TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPersist:
    """Tests for the fire-and-forget _persist() inner function."""

    @pytest.mark.asyncio
    async def test_persist_calls_rpush_and_expire(self):
        runner = _mock_runner([_make_event([_make_part(text="done")], is_final=True)])
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "hello"))
        redis = runner.session_service._redis
        assert redis.rpush.call_count >= 1
        assert redis.expire.call_count >= 1

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_raise(self):
        runner = _mock_runner([_make_event([_make_part(text="done")], is_final=True)])
        runner.session_service._redis.rpush = AsyncMock(side_effect=ConnectionError("down"))
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "hello"))
        # Should still get a complete event despite persist failure
        events = [_parse_sse(s) for s in collected]
        assert any(e["type"] == "complete" for e in events)

    @pytest.mark.asyncio
    async def test_redis_connection_down_silently_fails(self):
        runner = _mock_runner([_make_event([_make_part(text="answer")], is_final=True)])
        runner.session_service._redis.rpush = AsyncMock(side_effect=OSError("Connection refused"))
        runner.session_service._redis.expire = AsyncMock(side_effect=OSError("Connection refused"))
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        events = [_parse_sse(s) for s in collected]
        assert any(e["type"] == "complete" for e in events)

    @pytest.mark.asyncio
    async def test_persist_sets_ttl_via_expire(self):
        runner = _mock_runner([_make_event([_make_part(text="answer")], is_final=True)])
        from app.services.runner import run_agent_with_events
        await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        redis = runner.session_service._redis
        # expire called with the TTL value from the session service
        for call in redis.expire.call_args_list:
            assert call[0][1] == 3600

    @pytest.mark.asyncio
    async def test_multiple_persists_append_to_same_list(self):
        """With a tool call + response + complete, multiple rpush calls to same key."""
        fc = _make_function_call("check_health", call_id="c1")
        fr = _make_function_response("check_health", call_id="c1", response=None)
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(function_response=fr)]),
            _make_event([_make_part(text="All healthy")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        await _collect(run_agent_with_events(runner, "u1", "s1", "check health"))
        redis = runner.session_service._redis
        # user event + progress running + progress done + complete = at least 4 rpush calls
        assert redis.rpush.call_count >= 4
        # All rpush calls use the same key
        keys = {call[0][0] for call in redis.rpush.call_args_list}
        assert len(keys) == 1


# ═══════════════════════════════════════════════════════════════════════════
# EVENT BRIDGE LIFECYCLE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestEventBridgeLifecycle:

    def test_init_creates_fresh_list(self):
        from app.request_context import init_llm_event_bridge
        bridge = init_llm_event_bridge()
        assert isinstance(bridge, list)
        assert len(bridge) == 0

    def test_push_appends_to_bridge(self):
        from app.request_context import init_llm_event_bridge, push_llm_event
        bridge = init_llm_event_bridge()
        push_llm_event({"type": "progress", "call_id": "ctx"})
        assert len(bridge) == 1
        assert bridge[0]["call_id"] == "ctx"

    def test_push_when_not_initialized_drops(self):
        from app.request_context import push_llm_event, teardown_llm_event_bridge
        teardown_llm_event_bridge()  # ensure no bridge
        # Should not raise
        push_llm_event({"type": "progress"})

    def test_teardown_clears_contextvar(self):
        from app.request_context import (
            init_llm_event_bridge,
            push_llm_event,
            teardown_llm_event_bridge,
            _cv_llm_events,
        )
        init_llm_event_bridge()
        teardown_llm_event_bridge()
        assert _cv_llm_events.get(None) is None

    def test_multiple_pushes_ordered(self):
        from app.request_context import init_llm_event_bridge, push_llm_event
        bridge = init_llm_event_bridge()
        push_llm_event({"order": 1})
        push_llm_event({"order": 2})
        push_llm_event({"order": 3})
        assert [e["order"] for e in bridge] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_bridge_isolation_between_tasks(self):
        from app.request_context import init_llm_event_bridge, push_llm_event, teardown_llm_event_bridge

        results = {}

        async def task_a():
            bridge = init_llm_event_bridge()
            push_llm_event({"task": "a"})
            await asyncio.sleep(0.01)
            results["a"] = list(bridge)
            teardown_llm_event_bridge()

        async def task_b():
            bridge = init_llm_event_bridge()
            push_llm_event({"task": "b"})
            await asyncio.sleep(0.01)
            results["b"] = list(bridge)
            teardown_llm_event_bridge()

        await asyncio.gather(task_a(), task_b())
        # Each task should only see its own events
        assert len(results["a"]) == 1
        assert results["a"][0]["task"] == "a"
        assert len(results["b"]) == 1
        assert results["b"][0]["task"] == "b"

    def test_post_teardown_push_dropped(self):
        from app.request_context import (
            init_llm_event_bridge,
            push_llm_event,
            teardown_llm_event_bridge,
            _cv_llm_events,
        )
        bridge = init_llm_event_bridge()
        push_llm_event({"before": True})
        assert len(bridge) == 1
        teardown_llm_event_bridge()
        push_llm_event({"after": True})
        # Original bridge still only has 1 item
        assert len(bridge) == 1
        # contextvar is None
        assert _cv_llm_events.get(None) is None


# ═══════════════════════════════════════════════════════════════════════════
# _drain_llm_events() TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestDrainLlmEvents:
    """Tests for the _drain_llm_events() inner async generator."""

    @pytest.mark.asyncio
    async def test_empty_bridge_yields_nothing(self):
        runner = _mock_runner([_make_event([_make_part(text="done")], is_final=True)])
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        events = [_parse_sse(s) for s in collected]
        # Only user persist + complete; no LLM bridge events
        types = [e["type"] for e in events]
        assert "progress" not in types or all(
            e.get("call_id") != "context_shrink" for e in events
        )

    @pytest.mark.asyncio
    async def test_single_llm_event_yielded(self):
        """Push an LLM event via the bridge; it should appear in SSE output."""
        from app.request_context import init_llm_event_bridge, push_llm_event, teardown_llm_event_bridge

        fc = _make_function_call("some_tool", call_id="t1")
        fr = _make_function_response("some_tool", call_id="t1")

        # We need to push the event after init but before drain.
        # The runner inits bridge internally; we'll patch init_llm_event_bridge to
        # return a pre-populated list.
        bridge = [{"type": "progress", "call_id": "llm_evt", "status": "info"}]

        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([_make_event([_make_part(text="done")], is_final=True)])
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))

        events = [_parse_sse(s) for s in collected]
        llm_evts = [e for e in events if e.get("call_id") == "llm_evt"]
        assert len(llm_evts) == 1

    @pytest.mark.asyncio
    async def test_multiple_llm_events_ordered(self):
        bridge = [
            {"type": "progress", "call_id": "ev1", "order": 1},
            {"type": "progress", "call_id": "ev2", "order": 2},
        ]
        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([_make_event([_make_part(text="done")], is_final=True)])
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))

        events = [_parse_sse(s) for s in collected]
        ordered = [e for e in events if "order" in e]
        assert [e["order"] for e in ordered] == [1, 2]

    @pytest.mark.asyncio
    async def test_context_shrink_sets_flag(self):
        """When context_shrink event is drained, the flag should affect error handling."""
        bridge = [{"type": "progress", "call_id": "context_shrink", "status": "info"}]

        # After draining context_shrink, a BadRequestError should produce the friendly message
        class FakeBadRequest(Exception):
            pass
        FakeBadRequest.__name__ = "BadRequestError"

        async def _failing_run_async(**kwargs):
            yield _make_event([_make_part(text="interim")])
            raise FakeBadRequest("request failed")

        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([])
            runner.run_async = _failing_run_async
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))

        events = [_parse_sse(s) for s in collected]
        error_evts = [e for e in events if e.get("type") == "error"]
        assert len(error_evts) >= 1
        # Should contain friendly context-overflow message because flag was set
        assert "too long" in error_evts[-1]["message"]

    @pytest.mark.asyncio
    async def test_non_context_shrink_flag_stays_false(self):
        bridge = [{"type": "progress", "call_id": "some_other", "status": "info"}]

        class FakeBadRequest(Exception):
            pass
        FakeBadRequest.__name__ = "BadRequestError"

        async def _failing_run_async(**kwargs):
            yield _make_event([_make_part(text="interim")])
            raise FakeBadRequest("request failed")

        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([])
            runner.run_async = _failing_run_async
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))

        events = [_parse_sse(s) for s in collected]
        error_evts = [e for e in events if e.get("type") == "error"]
        assert len(error_evts) >= 1
        # Should NOT contain the friendly context-overflow message
        assert "too long" not in error_evts[-1]["message"]

    @pytest.mark.asyncio
    async def test_mixed_events_including_context_shrink(self):
        bridge = [
            {"type": "progress", "call_id": "ev1", "status": "info"},
            {"type": "progress", "call_id": "context_shrink", "status": "shrinking"},
            {"type": "progress", "call_id": "ev2", "status": "info"},
        ]
        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([_make_event([_make_part(text="done")], is_final=True)])
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))

        events = [_parse_sse(s) for s in collected]
        call_ids = [e.get("call_id") for e in events if e.get("call_id")]
        assert "ev1" in call_ids
        assert "context_shrink" in call_ids
        assert "ev2" in call_ids


# ═══════════════════════════════════════════════════════════════════════════
# EVENT EMISSION ORDERING TESTS (run_agent_with_events)
# ═══════════════════════════════════════════════════════════════════════════

class TestEventEmissionOrdering:

    @pytest.mark.asyncio
    async def test_normal_flow_user_complete(self):
        """Simple flow: final response → user persist + complete SSE."""
        runner = _mock_runner([_make_event([_make_part(text="Answer here")], is_final=True)])
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "hello"))
        events = [_parse_sse(s) for s in collected]
        assert events[-1]["type"] == "complete"
        assert events[-1]["text"] == "Answer here"

    @pytest.mark.asyncio
    async def test_tool_call_flow(self):
        """Tool call → running progress → done progress → complete."""
        fc = _make_function_call("check_health", call_id="c1")
        fr = _make_function_response("check_health", call_id="c1")
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(function_response=fr)]),
            _make_event([_make_part(text="All good")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "check"))
        parsed = [_parse_sse(s) for s in collected]
        types_statuses = [(e["type"], e.get("status")) for e in parsed]
        assert ("progress", "running") in types_statuses
        assert ("progress", "done") in types_statuses
        assert parsed[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_multi_tool_flow(self):
        """Two tool calls → 2x running, 2x done, then complete."""
        fc1 = _make_function_call("tool_a", call_id="a1")
        fc2 = _make_function_call("tool_b", call_id="b1")
        fr1 = _make_function_response("tool_a", call_id="a1")
        fr2 = _make_function_response("tool_b", call_id="b1")
        events = [
            _make_event([_make_part(function_call=fc1)]),
            _make_event([_make_part(function_call=fc2)]),
            _make_event([_make_part(function_response=fr1)]),
            _make_event([_make_part(function_response=fr2)]),
            _make_event([_make_part(text="Done with both")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "multi"))
        parsed = [_parse_sse(s) for s in collected]
        running = [e for e in parsed if e.get("status") == "running"]
        done = [e for e in parsed if e.get("status") == "done"]
        assert len(running) == 2
        assert len(done) == 2
        assert parsed[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_thinking_event_emitted(self):
        """Part with thought=True → thinking event."""
        events = [
            _make_event([_make_part(text="Let me think...", thought=True)]),
            _make_event([_make_part(text="Final answer")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        thinking = [e for e in parsed if e["type"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["text"] == "Let me think..."

    @pytest.mark.asyncio
    async def test_reasoning_event_between_tool_calls(self):
        """Non-final text part without thought → reasoning event."""
        events = [
            _make_event([_make_part(text="Let me check the namespace...")]),
            _make_event([_make_part(text="The answer")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        reasoning = [e for e in parsed if e["type"] == "reasoning"]
        assert len(reasoning) == 1
        assert reasoning[0]["text"] == "Let me check the namespace..."

    @pytest.mark.asyncio
    async def test_empty_text_part_skipped(self):
        """Parts with empty/whitespace text should be skipped."""
        events = [
            _make_event([_make_part(text="   ")]),
            _make_event([_make_part(text="Answer")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        # No reasoning event for the whitespace-only part
        reasoning = [e for e in parsed if e["type"] == "reasoning"]
        assert len(reasoning) == 0

    @pytest.mark.asyncio
    async def test_graph_event_from_render_chart_function_call(self):
        """render_chart tool with valid args emits a graph event from function_call."""
        chart_args = {"labels": ["Jan", "Feb"], "datasets": [{"data": [10, 20]}]}
        fc = _make_function_call("render_chart", call_id="rc1", args=chart_args)
        fr = _make_function_response("render_chart", call_id="rc1", response={"content": [{"type": "text", "text": '{"rendered": true}'}], "isError": False})
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(function_response=fr)]),
            _make_event([_make_part(text="Chart rendered")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "show chart"))
        parsed = [_parse_sse(s) for s in collected]
        graph_evts = [e for e in parsed if e["type"] == "graph"]
        assert len(graph_evts) >= 1
        assert graph_evts[0]["graph_tool"] == "render_chart"

    @pytest.mark.asyncio
    async def test_graph_event_from_function_response(self):
        """Function response with chart_data → graph event extraction."""
        response_data = {
            "content": [
                {"type": "text", "text": json.dumps({"chart_data": {"labels": ["a"], "datasets": [{"data": [1]}]}})}
            ],
            "isError": False,
        }
        fc = _make_function_call("get_metrics", call_id="m1")
        fr = _make_function_response("get_metrics", call_id="m1", response=response_data)
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(function_response=fr)]),
            _make_event([_make_part(text="Here are metrics")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "metrics"))
        parsed = [_parse_sse(s) for s in collected]
        graph_evts = [e for e in parsed if e["type"] == "graph"]
        assert len(graph_evts) >= 1
        assert graph_evts[0]["graph_tool"] == "render_chart"

    @pytest.mark.asyncio
    async def test_table_data_restoration_from_cache(self):
        """Stripped table_data restored from TABLE_ROW_CACHE."""
        from app.hooks.session_hooks import TABLE_ROW_CACHE, table_row_cache_key

        cache_key = table_row_cache_key("s1", "t1")
        TABLE_ROW_CACHE[cache_key] = {
            "table_data": {"columns": ["col"], "rows": [["r1"], ["r2"]]}
        }
        try:
            response_data = {
                "content": [
                    {"type": "text", "text": json.dumps({
                        "table_data": {"columns": ["col"], "rows": [], "_rows_stripped": True}
                    })}
                ],
                "isError": False,
            }
            fc = _make_function_call("get_data", call_id="t1")
            fr = _make_function_response("get_data", call_id="t1", response=response_data)
            events = [
                _make_event([_make_part(function_call=fc)]),
                _make_event([_make_part(function_response=fr)]),
                _make_event([_make_part(text="Data")], is_final=True),
            ]
            runner = _mock_runner(events)
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "get data"))
            parsed = [_parse_sse(s) for s in collected]
            table_graph = [e for e in parsed if e["type"] == "graph" and e.get("graph_tool") == "render_table_data"]
            assert len(table_graph) >= 1
            assert len(table_graph[0]["args"]["rows"]) == 2
        finally:
            TABLE_ROW_CACHE.pop(cache_key, None)

    @pytest.mark.asyncio
    async def test_error_flow(self):
        """Generic exception → error event."""
        async def _failing_run(**kwargs):
            raise RuntimeError("something broke")
            yield  # make it a generator  # noqa: E501
        runner = _mock_runner([])
        runner.run_async = _failing_run
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        error_evts = [e for e in parsed if e["type"] == "error"]
        assert len(error_evts) >= 1
        assert "something broke" in error_evts[-1]["message"]

    @pytest.mark.asyncio
    async def test_llm_error_flow(self):
        """LLMError → progress(llm_error) + error event."""
        from app.exceptions import LLMError

        async def _llm_fail(**kwargs):
            raise LLMError(status_code=429, detail="rate limited")
            yield  # noqa: E501
        runner = _mock_runner([])
        runner.run_async = _llm_fail
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        llm_err = [e for e in parsed if e.get("tool") == "llm_error"]
        assert len(llm_err) == 1
        assert llm_err[0]["status"] == "error"
        error_evts = [e for e in parsed if e["type"] == "error"]
        assert len(error_evts) >= 1
        assert "429" in error_evts[0]["message"]

    @pytest.mark.asyncio
    async def test_mcp_connection_error_flow(self):
        """MCP connection error → progress(mcp_connection) + error."""
        async def _mcp_fail(**kwargs):
            raise ConnectionError("Failed to get tools from MCP server at http://localhost:8999")
            yield  # noqa: E501
        runner = _mock_runner([])
        runner.run_async = _mcp_fail
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        mcp_err = [e for e in parsed if e.get("tool") == "mcp_connection"]
        assert len(mcp_err) == 1
        error_evts = [e for e in parsed if e["type"] == "error"]
        assert len(error_evts) >= 1

    @pytest.mark.asyncio
    async def test_context_overflow_error_friendly_message(self):
        """Context overflow → friendly message."""
        async def _overflow(**kwargs):
            raise Exception("prompt is too long for the context length")
            yield  # noqa: E501
        runner = _mock_runner([])
        runner.run_async = _overflow
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        error_evts = [e for e in parsed if e["type"] == "error"]
        assert len(error_evts) >= 1
        assert "too long" in error_evts[0]["message"]

    @pytest.mark.asyncio
    async def test_drain_llm_events_before_final_response(self):
        """LLM bridge events are drained before the complete event."""
        bridge = [{"type": "progress", "call_id": "pre_final", "status": "info"}]
        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([_make_event([_make_part(text="answer")], is_final=True)])
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        # pre_final event should appear before complete
        call_ids = [e.get("call_id") for e in parsed]
        types = [e["type"] for e in parsed]
        pre_idx = next(i for i, cid in enumerate(call_ids) if cid == "pre_final")
        complete_idx = next(i for i, t in enumerate(types) if t == "complete")
        assert pre_idx < complete_idx

    @pytest.mark.asyncio
    async def test_drain_llm_events_before_error_response(self):
        """LLM bridge events are drained before error events on LLMError."""
        from app.exceptions import LLMError

        bridge = [{"type": "progress", "call_id": "pre_error", "status": "info"}]

        async def _llm_fail(**kwargs):
            raise LLMError(status_code=500, detail="internal")
            yield  # noqa: E501

        with patch("app.services.runner.init_llm_event_bridge", return_value=bridge):
            runner = _mock_runner([])
            runner.run_async = _llm_fail
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        call_ids = [e.get("call_id") for e in parsed]
        assert "pre_error" in call_ids


# ═══════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_query_with_unicode_emoji(self):
        runner = _mock_runner([_make_event([_make_part(text="Got it")], is_final=True)])
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "Hello \ud83d\ude80 \u4e16\u754c"))
        parsed = [_parse_sse(s) for s in collected]
        assert parsed[-1]["type"] == "complete"
        # Verify the user event was persisted with the unicode query
        redis = runner.session_service._redis
        first_rpush = redis.rpush.call_args_list[0]
        persisted = json.loads(first_rpush[0][1])
        assert "\U0001f680" in persisted["text"]

    @pytest.mark.asyncio
    async def test_empty_query_string(self):
        runner = _mock_runner([_make_event([_make_part(text="No input")], is_final=True)])
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", ""))
        parsed = [_parse_sse(s) for s in collected]
        assert parsed[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_session_not_found_creates_new(self):
        """When get_session returns None, create_session is called."""
        runner = _mock_runner(
            [_make_event([_make_part(text="answer")], is_final=True)],
            session_exists=False,
        )
        from app.services.runner import run_agent_with_events
        await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        runner.session_service.create_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_yields_no_final_event(self):
        """If runner yields events but none is final, no complete event."""
        events = [_make_event([_make_part(text="thinking...")])]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        types = [e["type"] for e in parsed]
        assert "complete" not in types

    @pytest.mark.asyncio
    async def test_very_large_answer_text(self):
        big_text = "A" * 100_000
        runner = _mock_runner([_make_event([_make_part(text=big_text)], is_final=True)])
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        complete = [e for e in parsed if e["type"] == "complete"]
        assert len(complete) == 1
        assert len(complete[0]["text"]) == 100_000

    @pytest.mark.asyncio
    async def test_thought_true_part_emits_thinking(self):
        events = [
            _make_event([_make_part(text="Deep thought", thought=True)]),
            _make_event([_make_part(text="Answer")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        thinking = [e for e in parsed if e["type"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["text"] == "Deep thought"

    @pytest.mark.asyncio
    async def test_thought_none_part_emits_reasoning(self):
        """Part with thought=None (not True) on non-final event → reasoning."""
        events = [
            _make_event([_make_part(text="Intermediate text", thought=None)]),
            _make_event([_make_part(text="Answer")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        reasoning = [e for e in parsed if e["type"] == "reasoning"]
        assert len(reasoning) == 1
        assert reasoning[0]["text"] == "Intermediate text"

    @pytest.mark.asyncio
    async def test_final_response_filters_thought_parts(self):
        """Complete event text excludes thought=True parts."""
        events = [
            _make_event([
                _make_part(text="Secret thought", thought=True),
                _make_part(text="Visible answer", thought=None),
            ], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        complete = [e for e in parsed if e["type"] == "complete"]
        assert len(complete) == 1
        assert "Visible answer" in complete[0]["text"]
        assert "Secret thought" not in complete[0]["text"]

    def test_tool_label_various_names(self):
        from app.services.runner import _tool_label
        assert _tool_label("wcnp_check_namespace_health") == "Check Namespace Health"
        assert _tool_label("prometheus_query_range") == "Prometheus Query Range"
        assert _tool_label("") == "Unknown Tool"
        assert _tool_label("mcp_get_logs") == "Get Logs"

    def test_tool_label_with_args(self):
        from app.services.runner import _tool_label
        label = _tool_label("load_skill", args={"skill_name": "health-triage"})
        assert "health-triage" in label

    @pytest.mark.asyncio
    async def test_graph_event_json_validation_failure_skipped(self):
        """If graph event JSON validation fails, the graph event is skipped."""
        # Create a response with chart_data that will cause json.dumps to fail
        # when _sanitize_floats returns something un-serializable
        response_data = {
            "content": [
                {"type": "text", "text": json.dumps({"chart_data": {"labels": ["a"], "datasets": [{"data": [1]}]}})}
            ],
            "isError": False,
        }
        fc = _make_function_call("get_metrics", call_id="m1")
        fr = _make_function_response("get_metrics", call_id="m1", response=response_data)
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(function_response=fr)]),
            _make_event([_make_part(text="Done")], is_final=True),
        ]
        runner = _mock_runner(events)

        # Patch _sanitize_floats to return non-serializable data
        with patch("app.services.runner._sanitize_floats", side_effect=ValueError("bad data")):
            from app.services.runner import run_agent_with_events
            collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))

        parsed = [_parse_sse(s) for s in collected]
        # Should still complete — graph error was caught
        assert parsed[-1]["type"] == "complete"

    @pytest.mark.asyncio
    async def test_teardown_called_in_finally(self):
        """teardown_llm_event_bridge is called even on success."""
        with patch("app.services.runner.teardown_llm_event_bridge") as mock_td:
            runner = _mock_runner([_make_event([_make_part(text="ok")], is_final=True)])
            from app.services.runner import run_agent_with_events
            await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
            mock_td.assert_called_once()

    @pytest.mark.asyncio
    async def test_teardown_called_on_error(self):
        """teardown_llm_event_bridge is called even when an exception occurs."""
        with patch("app.services.runner.teardown_llm_event_bridge") as mock_td:
            async def _fail(**kwargs):
                raise RuntimeError("boom")
                yield  # noqa: E501
            runner = _mock_runner([])
            runner.run_async = _fail
            from app.services.runner import run_agent_with_events
            await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
            mock_td.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_label_cache_reuse_on_done(self):
        """Done event reuses the richer label from the running event."""
        fc = _make_function_call("wcnp_check_health", call_id="c1", args={"namespace": "prod"})
        fr = _make_function_response("wcnp_check_health", call_id="c1")
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(function_response=fr)]),
            _make_event([_make_part(text="Healthy")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "check"))
        parsed = [_parse_sse(s) for s in collected]
        running = [e for e in parsed if e.get("status") == "running"]
        done = [e for e in parsed if e.get("status") == "done"]
        # Both should have the same label
        assert running[0]["label"] == done[0]["label"]

    @pytest.mark.asyncio
    async def test_tool_args_non_serializable_omitted(self):
        """Non-JSON-serializable tool args are omitted from the event."""
        # Create a dict-like object whose dict() produces non-serializable values.
        # We need dict(args) to succeed but json.dumps(result) to fail.
        unserializable = {"key": object()}

        fc = _make_function_call("some_tool", call_id="t1", args=unserializable)
        events = [
            _make_event([_make_part(function_call=fc)]),
            _make_event([_make_part(text="Done")], is_final=True),
        ]
        runner = _mock_runner(events)
        from app.services.runner import run_agent_with_events
        collected = await _collect(run_agent_with_events(runner, "u1", "s1", "q"))
        parsed = [_parse_sse(s) for s in collected]
        running = [e for e in parsed if e.get("status") == "running"]
        assert len(running) == 1
        # args key should not be present when serialization failed
        assert "args" not in running[0]
