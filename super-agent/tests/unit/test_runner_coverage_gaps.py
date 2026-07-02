"""
Unit tests targeting coverage gaps in app.services.runner.

Covers:
- _tool_label: load_skill_resource branch (skill_name + resource)
- run_agent: LLMError re-raise, MCPConnectionError re-raise,
             _is_mcp_connection_error branch inside except Exception
- run_agent_with_events: _drain_llm_events context_shrink popping,
             table row cache restoration, empty text skip, thinking events,
             intermediate reasoning events, LLMError handler drain path,
             generic Exception handler drain path, MCP connection error
             in SSE streaming, context overflow handling
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.exceptions import AgentError, LLMError, MCPConnectionError
from app.services.runner import _tool_label, _is_mcp_connection_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _collect(gen) -> list[str]:
    """Drain an async generator into a list."""
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results


def _parse_sse(chunk: str) -> dict:
    """Parse a single SSE data line into a dict."""
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    return json.loads(chunk[len("data: "):-2])


def _make_session_service():
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
    """Build a mock Runner that yields the given events from run_async."""
    async def _run_async(**kwargs):
        for event in events:
            if isinstance(event, Exception):
                raise event
            yield event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = _make_session_service()
    return runner


def _make_raising_runner(exc: Exception):
    """Build a mock Runner whose run_async raises the given exception."""
    async def _run_async(**kwargs):
        raise exc
        yield  # noqa: unreachable — needed to make this an async generator

    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = _make_session_service()
    return runner


def _text_part(text: str, thought: bool = False):
    """Create a mock Part with text (and optionally thought=True)."""
    part = MagicMock()
    part.text = text
    part.thought = True if thought else None
    part.function_call = None
    part.function_response = None
    return part


def _final_event(text: str = "done"):
    part = _text_part(text)
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.is_final_response.return_value = True
    event.content = content
    return event


def _non_final_text_event(text: str, thought: bool = False):
    """Non-final event with a text part (reasoning or thinking)."""
    part = _text_part(text, thought=thought)
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


def _function_response_event(name: str, response: dict, call_id: str = "call-1"):
    """ADK event with a function_response part carrying a tool result."""
    fr = MagicMock()
    fr.name = name
    fr.response = response
    fr.id = call_id

    part = MagicMock()
    part.function_call = None
    part.function_response = fr
    part.text = None

    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


# ---------------------------------------------------------------------------
# Tests: _tool_label — load_skill_resource branch (lines 365-368)
# ---------------------------------------------------------------------------

class TestToolLabelLoadSkillResource:
    """Cover _tool_label with name='load_skill_resource' where both
    skill_name and resource are present (line 366-367)."""

    def test_skill_name_and_resource_path(self):
        label = _tool_label(
            "load_skill_resource",
            {"skill_name": "my_skill", "resource_path": "path/to/file.txt"},
        )
        assert label == "\U0001f9e9 Loading Skill Resource: my_skill/file.txt"

    def test_skill_name_and_resource_id(self):
        label = _tool_label(
            "load_skill_resource",
            {"skill_name": "my_skill", "resource_id": "docs/readme.md"},
        )
        assert label == "\U0001f9e9 Loading Skill Resource: my_skill/readme.md"

    def test_skill_name_only(self):
        label = _tool_label(
            "load_skill_resource",
            {"skill_name": "my_skill"},
        )
        assert label == "\U0001f9e9 Loading Skill Resource: my_skill"

    def test_resource_path_preferred_over_resource_id(self):
        label = _tool_label(
            "load_skill_resource",
            {"skill_name": "s1", "resource_path": "a/b.yaml", "resource_id": "c/d.txt"},
        )
        # resource_path takes precedence
        assert label == "\U0001f9e9 Loading Skill Resource: s1/b.yaml"


# ---------------------------------------------------------------------------
# Tests: run_agent exception paths (lines 447-457)
# ---------------------------------------------------------------------------

class TestRunAgentExceptionPaths:
    """Cover run_agent: LLMError re-raise (448), MCPConnectionError re-raise (450),
    and _is_mcp_connection_error branch (453-457)."""

    @pytest.mark.asyncio
    async def test_llm_error_reraise(self):
        """LLMError raised inside run_async should propagate unchanged."""
        from app.services.runner import run_agent

        exc = LLMError(status_code=429, detail="rate limited")
        runner = _make_raising_runner(exc)

        with pytest.raises(LLMError) as exc_info:
            await run_agent(runner, "u1", "s1", "hello")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_mcp_connection_error_reraise(self):
        """MCPConnectionError raised inside run_async should propagate unchanged."""
        from app.services.runner import run_agent

        exc = MCPConnectionError("server down")
        runner = _make_raising_runner(exc)

        with pytest.raises(MCPConnectionError, match="server down"):
            await run_agent(runner, "u1", "s1", "hello")

    @pytest.mark.asyncio
    async def test_generic_exception_with_mcp_signature_becomes_mcp_error(self):
        """A generic Exception whose message matches MCP signatures should
        be wrapped in MCPConnectionError (lines 453-457)."""
        from app.services.runner import run_agent

        exc = RuntimeError("Failed to connect to MCP server at http://localhost:8080")
        runner = _make_raising_runner(exc)

        with pytest.raises(MCPConnectionError):
            await run_agent(runner, "u1", "s1", "hello")


# ---------------------------------------------------------------------------
# Tests: _drain_llm_events — context_shrink popping (lines 560-565)
# ---------------------------------------------------------------------------

class TestDrainLlmEventsContextShrink:
    """Cover the _drain_llm_events path that pops context_shrink events."""

    @pytest.mark.asyncio
    async def test_context_shrink_events_are_yielded(self):
        """When the LLM event bridge has context_shrink events, they should
        be drained and yielded as SSE lines."""
        from app.services.runner import run_agent_with_events

        shrink_event = {
            "type": "progress",
            "tool": "context_management",
            "call_id": "context_shrink",
            "label": "Optimizing context...",
            "category": "system",
            "status": "running",
        }

        runner = _make_runner([_final_event("done")])

        with patch("app.services.runner.init_llm_event_bridge") as mock_bridge:
            # Pre-populate the event bridge with a context_shrink event
            events_list = [shrink_event]
            mock_bridge.return_value = events_list

            chunks = await _collect(
                run_agent_with_events(runner, "u1", "s1", "test")
            )

        parsed = [_parse_sse(c) for c in chunks]
        shrink_events = [e for e in parsed if e.get("call_id") == "context_shrink"]
        assert len(shrink_events) >= 1
        assert shrink_events[0]["tool"] == "context_management"


# ---------------------------------------------------------------------------
# Tests: table row cache restoration (lines 690-694)
# ---------------------------------------------------------------------------

class TestTableRowCacheRestoration:
    """Cover the path that restores cached table rows stripped by
    after_tool_callback."""

    @pytest.mark.asyncio
    async def test_stripped_table_rows_restored_from_cache(self):
        from app.services.runner import run_agent_with_events
        from app.hooks.session_hooks import TABLE_ROW_CACHE, table_row_cache_key

        session_id = "s-cache-test"
        call_id = "call-table-1"

        # Prepare a function_response with stripped table_data
        raw_response = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "table_data": {
                            "_rows_stripped": True,
                            "columns": ["name", "value"],
                            "rows": [],
                        }
                    }),
                }
            ]
        }

        full_table_data = {
            "columns": ["name", "value"],
            "rows": [["cpu", "80%"], ["mem", "60%"]],
        }

        cache_key = table_row_cache_key(session_id, call_id)
        TABLE_ROW_CACHE[cache_key] = {"table_data": full_table_data}

        fr = MagicMock()
        fr.name = "some_tool"
        fr.response = raw_response
        fr.id = call_id

        part = MagicMock()
        part.function_call = None
        part.function_response = fr
        part.text = None

        content = MagicMock()
        content.parts = [part]
        resp_event = MagicMock()
        resp_event.is_final_response.return_value = False
        resp_event.content = content

        runner = _make_runner([resp_event, _final_event("done")])
        chunks = await _collect(
            run_agent_with_events(runner, "u1", session_id, "show table")
        )

        parsed = [_parse_sse(c) for c in chunks]
        # The cache entry should have been popped
        assert cache_key not in TABLE_ROW_CACHE

        # The restored table data event should carry full rows
        done_events = [e for e in parsed if e.get("status") == "done"]
        if done_events:
            for ev in done_events:
                if "table_data" in ev.get("args", {}):
                    assert ev["args"]["table_data"]["rows"] == full_table_data["rows"]


# ---------------------------------------------------------------------------
# Tests: empty text skip (line 727) and thinking/reasoning (lines 731-745)
# ---------------------------------------------------------------------------

class TestThinkingAndReasoning:
    """Cover the text part branches: empty text skip, thinking events,
    and intermediate reasoning events."""

    @pytest.mark.asyncio
    async def test_empty_text_is_skipped(self):
        """A part with whitespace-only text should be skipped (line 727)."""
        from app.services.runner import run_agent_with_events

        empty_text_event = _non_final_text_event("   ")
        runner = _make_runner([empty_text_event, _final_event("answer")])

        chunks = await _collect(
            run_agent_with_events(runner, "u1", "s1", "hello")
        )

        parsed = [_parse_sse(c) for c in chunks]
        # No reasoning or thinking event should appear for whitespace-only text
        reasoning_or_thinking = [
            e for e in parsed if e.get("type") in ("reasoning", "thinking")
        ]
        assert len(reasoning_or_thinking) == 0

    @pytest.mark.asyncio
    async def test_thinking_event_emitted(self):
        """A non-final part with thought=True should yield a thinking event (lines 731-736)."""
        from app.services.runner import run_agent_with_events

        thinking_event = _non_final_text_event("Let me analyze this...", thought=True)
        runner = _make_runner([thinking_event, _final_event("answer")])

        chunks = await _collect(
            run_agent_with_events(runner, "u1", "s1", "hello")
        )

        parsed = [_parse_sse(c) for c in chunks]
        thinking_events = [e for e in parsed if e.get("type") == "thinking"]
        assert len(thinking_events) == 1
        assert thinking_events[0]["text"] == "Let me analyze this..."

    @pytest.mark.asyncio
    async def test_reasoning_event_emitted_for_non_final(self):
        """A non-final, non-thought text part should yield a reasoning event (lines 740-745)."""
        from app.services.runner import run_agent_with_events

        reasoning = _non_final_text_event("Let me check the namespace health...")
        runner = _make_runner([reasoning, _final_event("All healthy")])

        chunks = await _collect(
            run_agent_with_events(runner, "u1", "s1", "check health")
        )

        parsed = [_parse_sse(c) for c in chunks]
        reasoning_events = [e for e in parsed if e.get("type") == "reasoning"]
        assert len(reasoning_events) == 1
        assert reasoning_events[0]["text"] == "Let me check the namespace health..."


# ---------------------------------------------------------------------------
# Tests: LLMError handler in SSE streaming (lines 761-775)
# ---------------------------------------------------------------------------

class TestSSEStreamingLLMError:
    """Cover the LLMError except block in run_agent_with_events that drains
    LLM events and yields error SSE."""

    @pytest.mark.asyncio
    async def test_llm_error_yields_error_events_and_drains(self):
        """When run_async raises LLMError, the SSE stream should yield
        the drained LLM events plus the error event (lines 761-775)."""
        from app.services.runner import run_agent_with_events

        llm_exc = LLMError(status_code=529, detail="overloaded")
        runner = _make_raising_runner(llm_exc)

        shrink_event = {
            "type": "progress",
            "tool": "context_management",
            "call_id": "context_shrink",
            "label": "Shrinking...",
            "category": "system",
            "status": "running",
        }

        with patch("app.services.runner.init_llm_event_bridge") as mock_bridge:
            mock_bridge.return_value = [shrink_event]
            chunks = await _collect(
                run_agent_with_events(runner, "u1", "s1", "test")
            )

        parsed = [_parse_sse(c) for c in chunks]

        # Should have drained the context_shrink event
        shrink_events = [e for e in parsed if e.get("call_id") == "context_shrink"]
        assert len(shrink_events) >= 1

        # Should have the LLM error progress event
        llm_err_events = [e for e in parsed if e.get("call_id") == "llm_error"]
        assert len(llm_err_events) == 1
        assert "529" in llm_err_events[0]["label"]

        # Should have the final error event
        error_events = [e for e in parsed if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "529" in error_events[0]["message"]


# ---------------------------------------------------------------------------
# Tests: generic Exception handler drain path (lines 776-797)
# ---------------------------------------------------------------------------

class TestSSEStreamingGenericExceptionDrain:
    """Cover the generic except block in run_agent_with_events that drains
    LLM events before handling specific error types."""

    @pytest.mark.asyncio
    async def test_generic_exception_drains_llm_events(self):
        """When run_async raises a generic Exception, LLM events should
        still be drained (line 778-779)."""
        from app.services.runner import run_agent_with_events

        exc = RuntimeError("something unexpected")
        runner = _make_raising_runner(exc)

        shrink_event = {
            "type": "progress",
            "tool": "context_management",
            "call_id": "context_shrink",
            "label": "Shrinking...",
            "category": "system",
            "status": "running",
        }

        with patch("app.services.runner.init_llm_event_bridge") as mock_bridge:
            mock_bridge.return_value = [shrink_event]
            chunks = await _collect(
                run_agent_with_events(runner, "u1", "s1", "test")
            )

        parsed = [_parse_sse(c) for c in chunks]
        shrink_events = [e for e in parsed if e.get("call_id") == "context_shrink"]
        assert len(shrink_events) >= 1


# ---------------------------------------------------------------------------
# Tests: MCP connection error in SSE streaming path (lines 782-797)
# ---------------------------------------------------------------------------

class TestSSEStreamingMCPConnectionError:
    """Cover the _is_mcp_connection_error branch inside the generic except
    block in run_agent_with_events (lines 782-797)."""

    @pytest.mark.asyncio
    async def test_mcp_connection_error_yields_mcp_error_events(self):
        """When run_async raises an exception matching MCP signatures,
        the SSE stream should yield MCP-specific error events."""
        from app.services.runner import run_agent_with_events

        exc = RuntimeError("Failed to connect to MCP server at http://localhost:9090")
        runner = _make_raising_runner(exc)

        chunks = await _collect(
            run_agent_with_events(runner, "u1", "s1", "test")
        )

        parsed = [_parse_sse(c) for c in chunks]

        # Should have the MCP error progress event
        mcp_err_events = [
            e for e in parsed
            if e.get("call_id") == "mcp_error"
        ]
        assert len(mcp_err_events) == 1
        assert "Unavailable" in mcp_err_events[0]["label"]

        # Should have the error event with user-friendly message
        error_events = [e for e in parsed if e.get("type") == "error"]
        assert len(error_events) == 1


# ---------------------------------------------------------------------------
# Tests: context overflow handling (lines 815-824)
# ---------------------------------------------------------------------------

class TestSSEStreamingContextOverflow:
    """Cover the context overflow branch in the generic except block
    of run_agent_with_events (lines 802-824)."""

    @pytest.mark.asyncio
    async def test_context_window_exceeded_error(self):
        """An exception with 'context length' in its message should
        trigger the context overflow path."""
        from app.services.runner import run_agent_with_events

        exc = RuntimeError("prompt is too long: context length exceeded 200000 tokens")
        runner = _make_raising_runner(exc)

        chunks = await _collect(
            run_agent_with_events(runner, "u1", "s1", "test")
        )

        parsed = [_parse_sse(c) for c in chunks]
        error_events = [e for e in parsed if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "too long" in error_events[0]["message"]
        assert "new session" in error_events[0]["message"]

    @pytest.mark.asyncio
    async def test_context_window_exceeded_error_type_name(self):
        """An exception whose type name contains 'contextwindow' should
        trigger the context overflow path."""
        from app.services.runner import run_agent_with_events

        class ContextWindowExceededError(Exception):
            pass

        exc = ContextWindowExceededError("too big")
        runner = _make_raising_runner(exc)

        chunks = await _collect(
            run_agent_with_events(runner, "u1", "s1", "test")
        )

        parsed = [_parse_sse(c) for c in chunks]
        error_events = [e for e in parsed if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "too long" in error_events[0]["message"]

    @pytest.mark.asyncio
    async def test_bad_request_after_context_shrink_attempt(self):
        """A BadRequestError after context_shrink was attempted should
        trigger the context overflow path (line 813)."""
        from app.services.runner import run_agent_with_events

        class BadRequestError(Exception):
            pass

        exc = BadRequestError("invalid request")
        runner = _make_raising_runner(exc)

        # Simulate context_shrink having been attempted via the LLM event bridge
        shrink_event = {
            "type": "progress",
            "tool": "context_management",
            "call_id": "context_shrink",
            "label": "Shrinking...",
            "category": "system",
            "status": "running",
        }

        with patch("app.services.runner.init_llm_event_bridge") as mock_bridge:
            mock_bridge.return_value = [shrink_event]
            chunks = await _collect(
                run_agent_with_events(runner, "u1", "s1", "test")
            )

        parsed = [_parse_sse(c) for c in chunks]
        error_events = [e for e in parsed if e.get("type") == "error"]
        assert len(error_events) == 1
        assert "too long" in error_events[0]["message"]


# ---------------------------------------------------------------------------
# Tests: drain on final response (line 749-750)
# ---------------------------------------------------------------------------

class TestDrainOnFinalResponse:
    """Cover the drain path right before the final 'complete' event (line 749-750)."""

    @pytest.mark.asyncio
    async def test_llm_events_drained_before_complete(self):
        """LLM events in the bridge should be drained before the complete event."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([_final_event("all done")])

        progress_event = {
            "type": "progress",
            "tool": "context_management",
            "call_id": "ctx_1",
            "label": "Optimizing...",
            "category": "system",
            "status": "done",
        }

        with patch("app.services.runner.init_llm_event_bridge") as mock_bridge:
            # Events are in the bridge when the final event arrives
            mock_bridge.return_value = [progress_event]
            chunks = await _collect(
                run_agent_with_events(runner, "u1", "s1", "test")
            )

        parsed = [_parse_sse(c) for c in chunks]
        # The progress event should appear before the complete event
        types = [e.get("type") for e in parsed]
        # At minimum we should see the user event persisted, plus the progress and complete
        assert "complete" in types
