"""
Integration tests for the full graph rendering pipeline.

Tests the SSE event stream from run_agent_with_events directly — verifying
type:"graph" event emission for chart_data, multi_chart_data, grafana_url,
and table_data payloads returned by MCP tool responses.

Architecture under test:
  run_agent_with_events (async generator) → ADK mock → SSE event dicts

Each test collects events from the generator and asserts on their structure.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_mock_runner(adk_events: list):
    """Build a mock ADK Runner that yields the given events."""

    async def _run_async(**kwargs):
        for event in adk_events:
            yield event

    svc = MagicMock()
    svc.get_session = AsyncMock(return_value=None)
    svc.create_session = AsyncMock()
    svc._ttl = 86400
    redis = MagicMock()
    redis.rpush = AsyncMock()
    redis.expire = AsyncMock()
    svc._redis = redis

    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = svc
    return runner


def _tool_response_event(tool_name: str, response: dict):
    """ADK function_response event — wraps response as ADK MCP TextContent envelope.

    ADK wraps MCP TextContent as:
        {"content": [{"type": "text", "text": "<json>"}], "isError": false}
    """
    fr = MagicMock()
    fr.name = tool_name
    fr.response = {
        "content": [{"type": "text", "text": json.dumps(response)}],
        "isError": False,
    }
    fr.id = f"resp-{tool_name}"
    part = MagicMock()
    part.function_call = None
    part.function_response = fr
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.is_final_response.return_value = False
    event.content = content
    return event


def _final_event(text: str = "Charts rendered."):
    p = MagicMock()
    p.text = text
    p.function_call = None
    p.function_response = None
    c = MagicMock()
    c.parts = [p]
    e = MagicMock()
    e.is_final_response.return_value = True
    e.content = c
    return e


async def _collect_events(runner, query: str = "test query") -> list[dict]:
    """Drive run_agent_with_events and return parsed event dicts."""
    from app.services.runner import run_agent_with_events

    events = []
    async for sse_line in run_agent_with_events(runner, "test-user", "test-session", query):
        # Each line is "data: {...}\n\n"
        for line in sse_line.splitlines():
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGraphEventInSSEStream:

    @pytest.mark.asyncio
    async def test_chart_data_response_emits_graph_event_in_stream(self):
        """When an MCP tool returns chart_data, the SSE stream contains a type:'graph' event."""
        chart_data = {
            "chart_type": "line",
            "title": "CPU Usage — signal-api",
            "labels": ["14:00", "14:05", "14:10"],
            "datasets": [{"label": "scus-prod-a74", "data": [0.007, 0.009, 0.012]}],
        }
        runner = _make_mock_runner([
            _tool_response_event("wcnp_chart", {"chart_data": chart_data}),
            _final_event("CPU chart rendered."),
        ])

        events = await _collect_events(runner, "Show CPU chart for signal-api")

        graph_events = [e for e in events if e.get("type") == "graph"]
        assert len(graph_events) == 1
        assert graph_events[0]["graph_tool"] == "render_chart"
        assert graph_events[0]["args"]["title"] == "CPU Usage — signal-api"

    @pytest.mark.asyncio
    async def test_multi_chart_data_response_emits_graph_event(self):
        """wcnp_chart response with multi_chart_data produces a render_multi_chart graph event."""
        multi_chart = {
            "title": "Health Dashboard — signal-api (scus-prod-a74)",
            "charts": [
                {"metric": "CPU",    "y_label": "cores", "labels": ["14:00"], "datasets": [{"label": "p1", "data": [0.01]}]},
                {"metric": "Memory", "y_label": "Bytes", "labels": ["14:00"], "datasets": [{"label": "p1", "data": [1e8]}]},
            ],
        }
        runner = _make_mock_runner([
            _tool_response_event("wcnp_chart", {"multi_chart_data": multi_chart}),
            _final_event("Dashboard ready."),
        ])

        events = await _collect_events(runner, "Show health dashboard")

        graph_events = [e for e in events if e.get("type") == "graph"]
        assert len(graph_events) == 1
        g = graph_events[0]
        assert g["graph_tool"] == "render_multi_chart"
        assert len(g["args"]["charts"]) == 2

    @pytest.mark.asyncio
    async def test_grafana_url_in_response_emits_grafana_graph_event(self):
        """A grafana_url anywhere in the response produces a render_grafana_panel graph event."""
        runner = _make_mock_runner([
            _tool_response_event("wcnp_check_app_health", {
                "grafana_url": "https://grafana.scus-prod-a74.cluster.k8s.us.walmart.net/d/abc/apps",
                "overall_status": "unhealthy",
            }),
            _final_event("Anomaly detected."),
        ])

        events = await _collect_events(runner, "Check app health")

        graph_events = [e for e in events if e.get("type") == "graph"]
        assert len(graph_events) == 1
        assert graph_events[0]["graph_tool"] == "render_grafana_panel"
        assert "grafana" in graph_events[0]["args"]["url"]

    @pytest.mark.asyncio
    async def test_nested_grafana_url_extracted_from_health_check(self):
        """grafana_url nested inside checks.<metric> is found and emitted."""
        runner = _make_mock_runner([
            _tool_response_event("wcnp_check_app_health", {
                "overall_status": "unhealthy",
                "checks": {
                    "istio_client_latency": {
                        "status": "unhealthy",
                        "p99_latency_ms": 4350,
                        "grafana_url": "https://grafana.cluster/d/LJ_uJAvmn/istio-service",
                    }
                },
            }),
            _final_event("Latency spike found."),
        ])

        events = await _collect_events(runner, "Check latency")

        grafana_events = [
            e for e in events
            if e.get("type") == "graph" and e.get("graph_tool") == "render_grafana_panel"
        ]
        assert len(grafana_events) == 1
        assert grafana_events[0]["args"]["url"] == "https://grafana.cluster/d/LJ_uJAvmn/istio-service"

    @pytest.mark.asyncio
    async def test_no_chart_keys_produces_no_graph_event(self):
        """A plain tool response without chart keys produces no graph event."""
        runner = _make_mock_runner([
            _tool_response_event("wcnp_list_deployments", {
                "deployments": ["signal-api"],
                "cluster_id": "scus-prod-a74",
            }),
            _final_event("Found 1 deployment."),
        ])

        events = await _collect_events(runner, "List deployments")

        assert not any(e.get("type") == "graph" for e in events)

    @pytest.mark.asyncio
    async def test_stream_contains_complete_event(self):
        """Every stream must end with a type:'complete' event containing the LLM answer."""
        runner = _make_mock_runner([
            _tool_response_event("wcnp_chart", {
                "chart_data": {"labels": [], "datasets": []},
            }),
            _final_event("All done."),
        ])

        events = await _collect_events(runner, "query")

        complete_events = [e for e in events if e.get("type") == "complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["text"] == "All done."

    @pytest.mark.asyncio
    async def test_graph_event_appears_before_complete_event(self):
        """Graph events must be emitted in the stream before the complete event."""
        runner = _make_mock_runner([
            _tool_response_event("wcnp_chart", {
                "multi_chart_data": {"title": "T", "charts": []},
            }),
            _final_event("Done."),
        ])

        events = await _collect_events(runner, "dashboard")

        types = [e.get("type") for e in events]
        assert "graph" in types
        assert "complete" in types
        assert types.index("graph") < types.index("complete")

    @pytest.mark.asyncio
    async def test_nan_in_chart_data_sanitized_in_sse_stream(self):
        """NaN in chart data must not appear as literal NaN in the SSE stream (invalid JSON)."""
        chart_data_with_nan = {
            "labels": ["14:00", "14:05"],
            "datasets": [{"label": "pod-a", "data": [0.007, float("nan")]}],
        }
        runner = _make_mock_runner([
            _tool_response_event("wcnp_chart", {"chart_data": chart_data_with_nan}),
            _final_event("done"),
        ])

        events = await _collect_events(runner, "chart")

        graph_events = [e for e in events if e.get("type") == "graph"]
        assert len(graph_events) == 1
        data = graph_events[0]["args"]["datasets"][0]["data"]
        assert data[1] is None  # NaN → null

    @pytest.mark.asyncio
    async def test_multiple_tool_responses_multiple_graph_events(self):
        """Two tool responses each with chart_data produce two separate graph events."""
        chart = {"labels": ["t1"], "datasets": [{"label": "c", "data": [1.0]}]}
        runner = _make_mock_runner([
            _tool_response_event("wcnp_chart", {"chart_data": {**chart, "title": "CPU"}}),
            _tool_response_event("wcnp_chart", {"chart_data": {**chart, "title": "Memory"}}),
            _final_event("Both charts ready."),
        ])

        events = await _collect_events(runner, "show cpu and memory")

        graph_events = [e for e in events if e.get("type") == "graph"]
        assert len(graph_events) == 2
        titles = {e["args"].get("title") for e in graph_events}
        assert "CPU" in titles
        assert "Memory" in titles

    @pytest.mark.asyncio
    async def test_all_three_graph_types_in_one_response(self):
        """A response with chart_data + multi_chart_data + grafana_url emits all three graph event types."""
        runner = _make_mock_runner([
            _tool_response_event("wcnp_demo_grafana_prometheus", {
                "chart_data":       {"labels": [], "datasets": []},
                "multi_chart_data": {"title": "T", "charts": []},
                "grafana_url":      "https://grafana.example/d/x",
            }),
            _final_event("All rendered."),
        ])

        events = await _collect_events(runner, "show all")

        graph_tools = {e["graph_tool"] for e in events if e.get("type") == "graph"}
        assert "render_chart" in graph_tools
        assert "render_multi_chart" in graph_tools
        assert "render_grafana_panel" in graph_tools
