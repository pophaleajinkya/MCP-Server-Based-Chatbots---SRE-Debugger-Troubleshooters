"""
Unit tests for run_agent_with_events() in app.services.runner.

Verifies SSE event formatting, ordering, and error handling without a live
ADK runtime, Redis connection, or Google GenAI credentials.

Each test exercises the public contract: given a specific sequence of ADK
events from the runner, the generator must yield exactly the right
``data: {...}\\n\\n`` SSE lines.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect(gen) -> list[str]:
    """Drain an async generator, returning all yielded strings."""
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results


def _parse_sse(chunk: str) -> dict:
    """Parse a single ``data: {...}\\n\\n`` SSE line into a dict."""
    assert chunk.startswith("data: "), f"Expected 'data: ' prefix, got: {chunk!r}"
    assert chunk.endswith("\n\n"), f"Expected '\\n\\n' suffix, got: {chunk!r}"
    return json.loads(chunk[len("data: "):-2])


def _make_session_service():
    """Build a mock session_service with Redis stubs needed by run_agent_with_events."""
    svc = MagicMock()
    svc.get_session = AsyncMock(return_value=None)
    svc.create_session = AsyncMock()
    svc._ttl = 86400
    redis = MagicMock()
    redis.rpush = AsyncMock()
    redis.expire = AsyncMock()
    svc._redis = redis
    return svc


def _make_runner(events: list):
    """Build a mock Runner that yields the given list of events from run_async."""

    async def _run_async(**kwargs):
        for event in events:
            yield event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = _make_session_service()
    return runner


def _make_runner_raising(exc: Exception):
    """Build a mock Runner whose run_async raises *exc* when iterated."""

    async def _run_async(**kwargs):
        raise exc
        if False:  # unreachable — keeps this an async generator
            yield

    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = _make_session_service()
    return runner


def _final_event(text: str):
    """Return a mock ADK event that is_final_response() with plain text content."""
    part = MagicMock()
    part.text = text
    part.function_call = None
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.is_final_response.return_value = True
    event.content = content
    return event


def _tool_call_event(tool_name: str):
    """Return a mock ADK event representing an MCP function_call."""
    fc = MagicMock()
    fc.name = tool_name
    fc.args = {"namespace": "intl-sre"}

    part = MagicMock()
    part.function_call = fc
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


def _tool_response_event(tool_name: str):
    """Return a mock ADK event representing an MCP function_response."""
    fr = MagicMock()
    fr.name = tool_name
    fr.response = {"status": "ok"}

    part = MagicMock()
    part.function_call = None
    part.function_response = fr

    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


# ---------------------------------------------------------------------------
# Tests: final response events
# ---------------------------------------------------------------------------


class TestRunAgentWithEventsFinalResponse:
    """The generator must emit a 'complete' SSE event when the runner finishes."""

    @pytest.mark.asyncio
    async def test_emits_complete_event_with_answer_text(self):
        """A final-response event yields a single 'complete' SSE with the answer."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("All pods are healthy.")])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "check health"))

        assert len(chunks) == 1
        data = _parse_sse(chunks[0])
        assert data["type"] == "complete"
        assert data["text"] == "All pods are healthy."

    @pytest.mark.asyncio
    async def test_stream_ends_after_first_complete_event(self):
        """The generator must return after the first final response; no further events."""
        from app.services.runner import run_agent_with_events

        # Two final events — only the first should produce a complete SSE.
        runner = _make_runner([_final_event("First"), _final_event("Second — unreachable")])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 1
        assert _parse_sse(chunks[0])["type"] == "complete"
        assert _parse_sse(chunks[0])["text"] == "First"

    @pytest.mark.asyncio
    async def test_no_events_yields_nothing(self):
        """When the runner emits no events the generator yields nothing at all."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert chunks == []

    @pytest.mark.asyncio
    async def test_non_final_event_without_tool_parts_yields_nothing(self):
        """A non-final event with no function_call/function_response parts is silent."""
        from app.services.runner import run_agent_with_events

        # intermediate event with no tool call and no text — common for streaming chunks
        intermediate = MagicMock()
        intermediate.is_final_response.return_value = False
        intermediate.content = None

        runner = _make_runner([intermediate])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert chunks == []


# ---------------------------------------------------------------------------
# Tests: tool call / response progress events
# ---------------------------------------------------------------------------


class TestRunAgentWithEventsToolProgress:
    """MCP tool-call and tool-response events must yield 'progress' SSE lines."""

    @pytest.mark.asyncio
    async def test_tool_call_emits_running_progress(self):
        """An MCP function_call part should produce a progress event with status=running."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_check_namespace_health"),
            _final_event("Done"),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 2
        progress = _parse_sse(chunks[0])
        assert progress["type"] == "progress"
        assert progress["status"] == "running"
        assert progress["tool"] == "wcnp_check_namespace_health"

    @pytest.mark.asyncio
    async def test_tool_response_emits_done_progress(self):
        """An MCP function_response part should produce a progress event with status=done."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_check_app_health"),
            _tool_response_event("wcnp_check_app_health"),
            _final_event("App healthy"),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 3
        done_progress = _parse_sse(chunks[1])
        assert done_progress["type"] == "progress"
        assert done_progress["status"] == "done"
        assert done_progress["tool"] == "wcnp_check_app_health"

    @pytest.mark.asyncio
    async def test_known_tool_receives_human_readable_label(self):
        """Tool names with a vendor prefix are stripped and title-cased dynamically."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_query_prometheus"),
            _final_event("metrics"),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        progress = _parse_sse(chunks[0])
        assert progress["label"] == "Query Prometheus"

    @pytest.mark.asyncio
    async def test_known_tool_check_namespace_health_label(self):
        """wcnp_check_namespace_health strips the wcnp_ prefix and title-cases the rest."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_check_namespace_health"),
            _final_event("ok"),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert _parse_sse(chunks[0])["label"] == "Check Namespace Health"

    @pytest.mark.asyncio
    async def test_unknown_tool_gets_title_cased_name(self):
        """Unknown tool names fall back to a title-cased, underscore-replaced label."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("my_custom_analysis_tool"),
            _final_event("done"),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        progress = _parse_sse(chunks[0])
        assert progress["label"] == "My Custom Analysis Tool"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_emit_separate_events(self):
        """Each tool invocation produces its own pair of running/done progress events."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_check_namespace_health"),
            _tool_response_event("wcnp_check_namespace_health"),
            _tool_call_event("wcnp_query_prometheus"),
            _tool_response_event("wcnp_query_prometheus"),
            _final_event("All good."),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        # 2 running + 2 done + 1 complete = 5 total events
        assert len(chunks) == 5
        statuses = [_parse_sse(c).get("status") for c in chunks[:-1]]
        assert statuses == ["running", "done", "running", "done"]
        assert _parse_sse(chunks[-1])["type"] == "complete"


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestRunAgentWithEventsErrors:
    """Exceptions from the runner must be surfaced as error SSE events."""

    @pytest.mark.asyncio
    async def test_llm_error_yields_typed_error_event(self):
        """An LLMError from the runner must produce a progress event + error SSE with status code."""
        from app.services.runner import run_agent_with_events
        from app.exceptions import LLMError

        runner = _make_runner_raising(LLMError(status_code=429, detail="rate limited"))
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        # Runner now emits a progress event (llm_error) followed by the error event
        assert len(chunks) == 2
        progress = _parse_sse(chunks[0])
        assert progress["type"] == "progress"
        assert progress["tool"] == "llm_error"
        assert progress["status"] == "error"
        assert "429" in progress["label"]

        data = _parse_sse(chunks[1])
        assert data["type"] == "error"
        assert "429" in data["message"]
        assert "rate limited" in data["message"]

    @pytest.mark.asyncio
    async def test_generic_exception_yields_error_event(self):
        """Any non-LLM exception from the runner should yield an error SSE event."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner_raising(RuntimeError("unexpected service failure"))
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 1
        data = _parse_sse(chunks[0])
        assert data["type"] == "error"
        assert "unexpected service failure" in data["message"]

    @pytest.mark.asyncio
    async def test_every_chunk_is_valid_sse_format(self):
        """All emitted chunks must follow the ``data: {...}\\n\\n`` SSE wire format."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_check_app_health"),
            _tool_response_event("wcnp_check_app_health"),
            _final_event("healthy"),
        ])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 3
        for chunk in chunks:
            assert chunk.startswith("data: "), f"Bad SSE prefix: {chunk!r}"
            assert chunk.endswith("\n\n"), f"Bad SSE suffix: {chunk!r}"
            # Payload must be valid JSON
            json.loads(chunk[len("data: "):-2])

    @pytest.mark.asyncio
    async def test_complete_event_payload_is_json_serializable(self):
        """The 'complete' event payload must be JSON-serialisable (no raw Mocks)."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("serialisable answer")])
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 1
        # _parse_sse will raise if the payload is not valid JSON
        data = _parse_sse(chunks[0])
        assert isinstance(data["text"], str)


# ---------------------------------------------------------------------------
# Tests: UI event persistence (event-sourcing)
# ---------------------------------------------------------------------------


class TestRunAgentWithEventsUiPersistence:
    """Every SSE event must be persisted to the ui_events Redis list."""

    @pytest.mark.asyncio
    async def test_user_message_persisted_before_any_tool_call(self):
        """The user query must be the first entry pushed to the ui_events key."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("ok")])
        await _collect(run_agent_with_events(runner, "admin", "sess-1", "my query"))

        calls = runner.session_service._redis.rpush.call_args_list
        assert len(calls) >= 1
        first_payload = json.loads(calls[0][0][1])
        assert first_payload["type"] == "user"
        assert first_payload["text"] == "my query"

    @pytest.mark.asyncio
    async def test_complete_event_persisted_to_redis(self):
        """The 'complete' event must be written to Redis after being yielded."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("answer text")])
        await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        all_payloads = [
            json.loads(call[0][1])
            for call in runner.session_service._redis.rpush.call_args_list
        ]
        complete_events = [p for p in all_payloads if p["type"] == "complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["text"] == "answer text"

    @pytest.mark.asyncio
    async def test_progress_running_event_persisted(self):
        """Each tool-call 'running' progress event must be written to Redis."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_tool_call_event("wcnp_check_app_health"), _final_event("ok")])
        await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        all_payloads = [
            json.loads(call[0][1])
            for call in runner.session_service._redis.rpush.call_args_list
        ]
        progress_running = [p for p in all_payloads if p.get("type") == "progress" and p.get("status") == "running"]
        assert len(progress_running) == 1
        assert progress_running[0]["tool"] == "wcnp_check_app_health"

    @pytest.mark.asyncio
    async def test_progress_done_event_persisted(self):
        """Each tool-response 'done' progress event must be written to Redis."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _tool_call_event("wcnp_check_app_health"),
            _tool_response_event("wcnp_check_app_health"),
            _final_event("ok"),
        ])
        await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        all_payloads = [
            json.loads(call[0][1])
            for call in runner.session_service._redis.rpush.call_args_list
        ]
        progress_done = [p for p in all_payloads if p.get("type") == "progress" and p.get("status") == "done"]
        assert len(progress_done) == 1
        assert progress_done[0]["tool"] == "wcnp_check_app_health"

    @pytest.mark.asyncio
    async def test_every_persisted_event_has_ts_field(self):
        """Every Redis-persisted event must have a numeric 'ts' timestamp field."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_tool_call_event("wcnp_list_deployments"), _final_event("done")])
        await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        for call in runner.session_service._redis.rpush.call_args_list:
            payload = json.loads(call[0][1])
            assert "ts" in payload, f"Missing 'ts' in {payload}"
            assert isinstance(payload["ts"], float)

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_stop_sse_stream(self):
        """A Redis write error must not interrupt the SSE event stream."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("still works")])
        runner.session_service._redis.rpush = AsyncMock(side_effect=Exception("redis down"))

        # Stream must still complete and yield the complete event
        chunks = await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        assert len(chunks) == 1
        assert _parse_sse(chunks[0])["type"] == "complete"
        assert _parse_sse(chunks[0])["text"] == "still works"

    @pytest.mark.asyncio
    async def test_ttl_refreshed_after_each_persist(self):
        """Redis.expire must be called with the session TTL after every rpush."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("ok")])
        await _collect(run_agent_with_events(runner, "admin", "sess-1", "q"))

        expire_calls = runner.session_service._redis.expire.call_args_list
        # At minimum user message + complete = 2 expire calls
        assert len(expire_calls) >= 2
        for call in expire_calls:
            assert call[0][1] == runner.session_service._ttl
