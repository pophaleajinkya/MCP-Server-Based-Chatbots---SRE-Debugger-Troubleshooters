"""
Unit tests for render_* tool arg forwarding in run_agent_with_events().

When the ADK runner emits a function_call for render_chart, render_multi_chart,
or render_grafana_panel, the SSE event must include an 'args' field containing
the tool arguments so the UI can render charts client-side.

Non-render tools (e.g. wcnp_check_namespace_health) must NOT get an 'args' field.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers  (reused from test_runner_events.py style)
# ---------------------------------------------------------------------------

async def _collect(gen) -> list[str]:
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results


def _parse_sse(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    return json.loads(chunk[len("data: "):-2])


def _make_runner(events: list):
    async def _run_async(**kwargs):
        for event in events:
            yield event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _render_tool_call_event(tool_name: str, args: dict):
    """ADK event: function_call for a render_* tool with chart args."""
    fc = MagicMock()
    fc.name = tool_name
    fc.args = args
    fc.id = f"call-{tool_name}"

    part = MagicMock()
    part.function_call = fc
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


def _non_render_tool_call_event(tool_name: str = "wcnp_check_namespace_health"):
    """ADK event: function_call for a non-render tool."""
    fc = MagicMock()
    fc.name = tool_name
    fc.args = {"namespace": "intl-sre"}
    fc.id = f"call-{tool_name}"

    part = MagicMock()
    part.function_call = fc
    part.function_response = None

    content = MagicMock()
    content.parts = [part]

    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


def _final_event(text: str = "done"):
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


# ---------------------------------------------------------------------------
# Tests: render_chart args forwarded in SSE
# ---------------------------------------------------------------------------

class TestRenderChartArgsInSSE:

    @pytest.mark.asyncio
    async def test_render_chart_args_included_in_sse(self):
        from app.services.runner import run_agent_with_events

        chart_args = {
            "chart_type": "line",
            "title": "CPU Trend",
            "labels": ["10:00", "10:05"],
            "datasets": [{"label": "scus-prod-a74", "data": [0.01, 0.02]}],
        }
        runner = _make_runner([
            _render_tool_call_event("render_chart", chart_args),
            _final_event("Here is your chart."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "show cpu trend"))
        progress_events = [_parse_sse(c) for c in chunks if _parse_sse(c).get("type") == "progress"]

        render_events = [e for e in progress_events if e["tool"] == "render_chart"]
        assert len(render_events) == 1
        assert "args" in render_events[0]
        assert render_events[0]["args"]["title"] == "CPU Trend"
        assert render_events[0]["args"]["labels"] == ["10:00", "10:05"]
        assert render_events[0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_render_multi_chart_args_included(self):
        from app.services.runner import run_agent_with_events

        multi_args = {
            "title": "Health Dashboard",
            "charts": [
                {"metric": "CPU", "y_label": "cores", "labels": ["t1"], "datasets": [{"label": "c1", "data": [0.01]}]},
            ],
        }
        runner = _make_runner([
            _render_tool_call_event("render_multi_chart", multi_args),
            _final_event("Dashboard ready."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "dashboard"))
        events = [_parse_sse(c) for c in chunks]
        render_events = [e for e in events if e.get("tool") == "render_multi_chart"]

        assert len(render_events) == 1
        assert render_events[0]["args"]["title"] == "Health Dashboard"
        assert len(render_events[0]["args"]["charts"]) == 1

    @pytest.mark.asyncio
    async def test_render_grafana_panel_args_included(self):
        from app.services.runner import run_agent_with_events

        grafana_args = {"url": "https://grafana.example.com/d/abc123", "title": "CPU Panel", "height": 450}
        runner = _make_runner([
            _render_tool_call_event("render_grafana_panel", grafana_args),
            _final_event("Panel embedded."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "show grafana"))
        events = [_parse_sse(c) for c in chunks]
        render_events = [e for e in events if e.get("tool") == "render_grafana_panel"]

        assert len(render_events) == 1
        assert render_events[0]["args"]["url"] == "https://grafana.example.com/d/abc123"
        assert render_events[0]["args"]["height"] == 450


# ---------------------------------------------------------------------------
# Tests: non-render tools with args DO get args (runner forwards all tool args)
# ---------------------------------------------------------------------------

class TestNonRenderToolsNoArgs:
    """The runner forwards args for ALL tools whose args are serializable.

    The 'no-args' distinction only applies when the function_call.args value
    is falsy (None / empty dict).  When a non-render tool sends args the SSE
    event DOES include them — the UI simply ignores them for non-render tools.
    """

    @pytest.mark.asyncio
    async def test_non_render_tool_with_args_includes_args_field(self):
        """A non-render tool whose function_call.args is non-empty gets 'args' in the SSE event."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _non_render_tool_call_event("wcnp_check_namespace_health"),
            _final_event("Health check done."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "check health"))
        events = [_parse_sse(c) for c in chunks]
        health_events = [e for e in events if e.get("tool") == "wcnp_check_namespace_health"]

        assert len(health_events) == 1
        # The runner forwards args for all tools with truthy args
        assert "args" in health_events[0]
        assert health_events[0]["args"] == {"namespace": "intl-sre"}

    @pytest.mark.asyncio
    async def test_wcnp_query_prometheus_with_args_includes_args_field(self):
        """wcnp_query_prometheus with non-empty args gets the args field in the SSE event."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _non_render_tool_call_event("wcnp_query_prometheus"),
            _final_event("Query done."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "run query"))
        events = [_parse_sse(c) for c in chunks]
        prom_events = [e for e in events if e.get("tool") == "wcnp_query_prometheus"]

        assert len(prom_events) == 1
        assert "args" in prom_events[0]
        assert prom_events[0]["args"] == {"namespace": "intl-sre"}


# ---------------------------------------------------------------------------
# Tests: args with non-serializable value falls back gracefully
# ---------------------------------------------------------------------------

class TestRenderArgsSerializationSafety:

    @pytest.mark.asyncio
    async def test_non_serializable_args_drops_args_silently(self):
        """If args contain a non-JSON-serializable value, the event is still emitted
        without 'args' (no exception, no broken stream)."""
        from app.services.runner import run_agent_with_events

        bad_args = {"labels": object()}  # not JSON-serializable
        runner = _make_runner([
            _render_tool_call_event("render_chart", bad_args),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "chart"))
        # Must not raise — stream must complete with a 'complete' event
        complete_events = [_parse_sse(c) for c in chunks if "complete" in c]
        assert any(e.get("type") == "complete" for e in complete_events)

    @pytest.mark.asyncio
    async def test_empty_args_dict_omits_args_field(self):
        """An empty dict for function_call.args is falsy, so 'args' is omitted from the SSE event.

        The runner checks ``if part.function_call.args:`` before adding the args
        field.  An empty dict ({}) evaluates to False, so the event is emitted
        without an 'args' key — callers cannot distinguish 'no args' from 'empty args'.
        """
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _render_tool_call_event("render_chart", {}),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u1", "s1", "chart"))
        events = [_parse_sse(c) for c in chunks]
        render_events = [e for e in events if e.get("tool") == "render_chart"]
        assert len(render_events) == 1
        # Empty dict is falsy — args key is NOT added to the event
        assert "args" not in render_events[0]


# ---------------------------------------------------------------------------
# Tests: exception paths in run_agent_with_events (lines 400-401, 428-429, 443-444)
# ---------------------------------------------------------------------------

class TestRunAgentWithEventsExceptionPaths:
    """Cover the exception/skip branches in the SSE event pipeline."""

    def _make_session_service(self):
        svc = MagicMock()
        svc.get_session = AsyncMock(return_value=None)
        svc.create_session = AsyncMock()
        svc._ttl = 86400
        redis = MagicMock()
        redis.rpush = AsyncMock()
        redis.expire = AsyncMock()
        svc._redis = redis
        return svc

    def _make_runner(self, events: list):
        async def _run_async(**kwargs):
            for event in events:
                yield event
        runner = MagicMock()
        runner.run_async = _run_async
        runner.app_name = "health_agent"
        runner.session_service = self._make_session_service()
        return runner

    def _parse_sse(self, chunk: str) -> dict:
        assert chunk.startswith("data: ")
        return json.loads(chunk[len("data: "):-2])

    @pytest.mark.asyncio
    async def test_render_chart_graph_event_exception_skipped(self):
        """When building a render_chart graph event raises, the exception is swallowed — lines 400-401.

        We make _sanitize_floats raise by passing a non-serializable object
        that survives the valid-check but fails json.dumps.
        """
        from app.services.runner import run_agent_with_events

        # Build a function_call for render_chart with a non-JSON-serializable value
        # We can't directly inject nan into args since _sanitize_floats converts that.
        # Instead patch the _sanitize_floats to raise so we hit the except block.
        from unittest.mock import patch

        fc = MagicMock()
        fc.name = "render_chart"
        fc.id = "call-render"
        # Valid-looking args (labels + datasets) so _valid is True, but we'll patch
        # _sanitize_floats to raise so json.dumps validation fails
        fc.args = {"labels": ["t1"], "datasets": [{"label": "a", "data": [1.0]}]}

        part = MagicMock()
        part.function_call = fc
        part.function_response = None

        content = MagicMock()
        content.parts = [part]

        fc_event = MagicMock()
        fc_event.is_final_response.return_value = False
        fc_event.content = content

        runner = self._make_runner([fc_event, _final_event("done")])

        with patch("app.services.runner._sanitize_floats", side_effect=RuntimeError("sanitize failed")):
            chunks = await _collect(run_agent_with_events(runner, "u", "s", "q"))

        # Stream must still complete — no exception propagated
        events = [self._parse_sse(c) for c in chunks]
        types = [e.get("type") for e in events]
        assert "complete" in types
        # graph event must be absent because exception was swallowed
        assert not any(e.get("type") == "graph" and e.get("graph_tool") == "render_chart"
                       for e in events if "graph_tool" in e)

    @pytest.mark.asyncio
    async def test_function_response_invalid_json_in_text_content_skipped(self):
        """When text content is invalid JSON, the JSONDecodeError is swallowed — lines 428-429.

        The MCP TextContent envelope has invalid JSON in the 'text' field.
        The handler must skip that item and fall back to top-level response lookup.
        """
        from app.services.runner import run_agent_with_events

        fr = MagicMock()
        fr.name = "some_tool"
        fr.id = "resp-1"
        # response with a content item whose 'text' is not valid JSON
        fr.response = {
            "content": [{"type": "text", "text": "not-valid-json{{{"}],
            "isError": False,
        }

        part = MagicMock()
        part.function_call = None
        part.function_response = fr

        content = MagicMock()
        content.parts = [part]

        event = MagicMock()
        event.is_final_response.return_value = False
        event.content = content

        runner = self._make_runner([event, _final_event("done")])

        # Must not raise — invalid JSON is swallowed and stream completes normally
        chunks = await _collect(run_agent_with_events(runner, "u", "s", "q"))
        events = [self._parse_sse(c) for c in chunks]
        types = [e.get("type") for e in events]
        assert "complete" in types

    @pytest.mark.asyncio
    async def test_function_response_outer_exception_swallowed(self):
        """When the entire function_response graph processing raises, it is swallowed — lines 443-444."""
        from app.services.runner import run_agent_with_events
        from unittest.mock import patch

        fr = MagicMock()
        fr.name = "some_tool"
        fr.id = "resp-2"
        fr.response = {
            "content": [{"type": "text", "text": json.dumps({"chart_data": {"labels": [], "datasets": []}})}],
            "isError": False,
        }

        part = MagicMock()
        part.function_call = None
        part.function_response = fr

        content = MagicMock()
        content.parts = [part]

        event = MagicMock()
        event.is_final_response.return_value = False
        event.content = content

        runner = self._make_runner([event, _final_event("done")])

        # Patch _extract_graph_events to raise so the outer except block fires
        with patch("app.services.runner._extract_graph_events", side_effect=RuntimeError("graph error")):
            chunks = await _collect(run_agent_with_events(runner, "u", "s", "q"))

        # Stream must still complete — outer exception was swallowed
        events = [self._parse_sse(c) for c in chunks]
        types = [e.get("type") for e in events]
        assert "complete" in types
