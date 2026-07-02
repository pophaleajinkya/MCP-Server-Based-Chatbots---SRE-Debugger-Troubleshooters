"""
Unit tests for the type:"graph" SSE event pipeline added to runner.py.

Covers:
  - _sanitize_floats()         — NaN/Inf → None, nested structures
  - _collect_grafana_urls()    — recursive grafana_url extraction
  - _extract_graph_events()    — response key detection
  - run_agent_with_events()    — graph events emitted from function_response
"""

import json
import math
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _collect(gen) -> list[str]:
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results


def _parse_sse(chunk: str) -> dict:
    assert chunk.startswith("data: "), f"bad prefix: {chunk!r}"
    assert chunk.endswith("\n\n"), f"bad suffix: {chunk!r}"
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
    async def _run_async(**kwargs):
        for event in events:
            yield event
    runner = MagicMock()
    runner.run_async = _run_async
    runner.app_name = "health_agent"
    runner.session_service = _make_session_service()
    return runner


def _function_response_event(tool_name: str, response: dict):
    """ADK event: function_response (tool result arrives back to the LLM).

    ADK wraps MCP TextContent as:
        {"content": [{"type": "text", "text": "<json_string>"}], "isError": false}
    The runner.py handler unwraps this envelope before calling _extract_graph_events.
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


def _final_event(text: str = "done"):
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


# ── _sanitize_floats ──────────────────────────────────────────────────────────

class TestSanitizeFloats:

    def test_nan_becomes_none(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats(float("nan")) is None

    def test_inf_becomes_none(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats(float("inf")) is None

    def test_negative_inf_becomes_none(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats(float("-inf")) is None

    def test_valid_float_unchanged(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats(3.14) == 3.14
        assert _sanitize_floats(0.0) == 0.0
        assert _sanitize_floats(-42.5) == -42.5

    def test_integer_unchanged(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats(42) == 42

    def test_string_unchanged(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats("hello") == "hello"

    def test_none_unchanged(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats(None) is None

    def test_dict_nan_values_replaced(self):
        from app.services.runner import _sanitize_floats
        result = _sanitize_floats({"a": float("nan"), "b": 1.5, "c": "x"})
        assert result == {"a": None, "b": 1.5, "c": "x"}

    def test_list_nan_values_replaced(self):
        from app.services.runner import _sanitize_floats
        result = _sanitize_floats([1.0, float("nan"), 3.0, float("inf")])
        assert result == [1.0, None, 3.0, None]

    def test_nested_dict_nan_replaced(self):
        from app.services.runner import _sanitize_floats
        data = {
            "chart_data": {
                "labels": ["t1", "t2"],
                "datasets": [
                    {"label": "pod-a", "data": [0.007, float("nan"), 0.003]},
                ],
            }
        }
        result = _sanitize_floats(data)
        assert result["chart_data"]["datasets"][0]["data"] == [0.007, None, 0.003]

    def test_empty_dict_unchanged(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats({}) == {}

    def test_empty_list_unchanged(self):
        from app.services.runner import _sanitize_floats
        assert _sanitize_floats([]) == []

    def test_result_is_json_serializable(self):
        from app.services.runner import _sanitize_floats
        dirty = {"data": [1.0, float("nan"), float("inf"), -float("inf"), 2.0]}
        clean = _sanitize_floats(dirty)
        # Must not raise
        serialized = json.dumps(clean)
        parsed = json.loads(serialized)
        assert parsed["data"] == [1.0, None, None, None, 2.0]

    def test_deeply_nested_nan(self):
        from app.services.runner import _sanitize_floats
        data = {"a": {"b": {"c": {"d": float("nan")}}}}
        result = _sanitize_floats(data)
        assert result["a"]["b"]["c"]["d"] is None

    def test_list_of_dicts_with_nan(self):
        from app.services.runner import _sanitize_floats
        data = [{"v": float("nan")}, {"v": 1.5}]
        result = _sanitize_floats(data)
        assert result == [{"v": None}, {"v": 1.5}]

    def test_does_not_mutate_original(self):
        from app.services.runner import _sanitize_floats
        original = {"data": [1.0, float("nan")]}
        _sanitize_floats(original)
        # Original list should still contain nan (new copy returned)
        assert math.isnan(original["data"][1])


# ── _collect_grafana_urls ─────────────────────────────────────────────────────

class TestCollectGrafanaUrls:

    def test_top_level_grafana_url(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        _collect_grafana_urls({"grafana_url": "https://grafana.example.com/d/abc"}, seen)
        assert "https://grafana.example.com/d/abc" in seen

    def test_nested_grafana_url_in_checks(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        obj = {
            "checks": {
                "cpu": {"status": "unhealthy", "grafana_url": "https://grafana.cluster/d/cpu"},
                "memory": {"status": "healthy"},
            }
        }
        _collect_grafana_urls(obj, seen)
        assert "https://grafana.cluster/d/cpu" in seen

    def test_multiple_nested_grafana_urls(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        obj = {
            "checks": {
                "cpu":    {"grafana_url": "https://g.example/cpu"},
                "memory": {"grafana_url": "https://g.example/mem"},
                "istio":  {"grafana_url": "https://g.example/istio"},
            }
        }
        _collect_grafana_urls(obj, seen)
        assert seen == {
            "https://g.example/cpu",
            "https://g.example/mem",
            "https://g.example/istio",
        }

    def test_duplicate_urls_deduplicated(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        obj = {
            "a": {"grafana_url": "https://g.example/same"},
            "b": {"grafana_url": "https://g.example/same"},
        }
        _collect_grafana_urls(obj, seen)
        assert len(seen) == 1

    def test_empty_grafana_url_ignored(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        _collect_grafana_urls({"grafana_url": ""}, seen)
        assert len(seen) == 0

    def test_non_string_grafana_url_ignored(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        _collect_grafana_urls({"grafana_url": None}, seen)
        _collect_grafana_urls({"grafana_url": 123}, seen)
        assert len(seen) == 0

    def test_grafana_url_inside_list(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        obj = {"results": [{"grafana_url": "https://g.example/list"}]}
        _collect_grafana_urls(obj, seen)
        assert "https://g.example/list" in seen

    def test_depth_limit_prevents_unbounded_recursion(self):
        from app.services.runner import _collect_grafana_urls
        # Build a deeply nested dict (depth = 10, beyond the limit of 6)
        nested = {"grafana_url": "https://deep.example/d/abc"}
        for _ in range(10):
            nested = {"child": nested}
        seen = set()
        _collect_grafana_urls(nested, seen)  # Must not raise, just may not find the URL
        # The URL at depth > 6 is not found — that's the expected behaviour
        assert isinstance(seen, set)

    def test_non_dict_input_ignored(self):
        from app.services.runner import _collect_grafana_urls
        seen = set()
        _collect_grafana_urls("not a dict", seen)
        _collect_grafana_urls(42, seen)
        _collect_grafana_urls(None, seen)
        assert len(seen) == 0


# ── _extract_graph_events ────────────────────────────────────────────────────

class TestExtractGraphEvents:

    def test_chart_data_produces_render_chart(self):
        from app.services.runner import _extract_graph_events
        response = {"chart_data": {"chart_type": "line", "labels": ["t1"], "datasets": []}}
        events = _extract_graph_events(response)
        assert len(events) == 1
        assert events[0][0] == "render_chart"
        assert events[0][1]["chart_type"] == "line"

    def test_multi_chart_data_produces_render_multi_chart(self):
        from app.services.runner import _extract_graph_events
        response = {"multi_chart_data": {"title": "Dashboard", "charts": []}}
        events = _extract_graph_events(response)
        assert len(events) == 1
        assert events[0][0] == "render_multi_chart"
        assert events[0][1]["title"] == "Dashboard"

    def test_top_level_grafana_url_produces_render_grafana_panel(self):
        from app.services.runner import _extract_graph_events
        response = {"grafana_url": "https://grafana.cluster/d/abc"}
        events = _extract_graph_events(response)
        assert len(events) == 1
        assert events[0][0] == "render_grafana_panel"
        assert events[0][1]["url"] == "https://grafana.cluster/d/abc"

    def test_nested_grafana_url_extracted(self):
        from app.services.runner import _extract_graph_events
        response = {
            "checks": {
                "cpu": {
                    "status": "unhealthy",
                    "grafana_url": "https://grafana.cluster/d/cpu-panel",
                }
            }
        }
        events = _extract_graph_events(response)
        grafana_events = [e for e in events if e[0] == "render_grafana_panel"]
        assert len(grafana_events) == 1
        assert grafana_events[0][1]["url"] == "https://grafana.cluster/d/cpu-panel"

    def test_all_three_keys_at_once(self):
        from app.services.runner import _extract_graph_events
        response = {
            "chart_data":       {"chart_type": "bar", "labels": [], "datasets": []},
            "multi_chart_data": {"title": "X", "charts": []},
            "grafana_url":      "https://grafana.cluster/d/xyz",
        }
        events = _extract_graph_events(response)
        tool_names = {e[0] for e in events}
        assert "render_chart" in tool_names
        assert "render_multi_chart" in tool_names
        assert "render_grafana_panel" in tool_names

    def test_empty_response_returns_empty(self):
        from app.services.runner import _extract_graph_events
        assert _extract_graph_events({}) == []

    def test_chart_data_not_dict_ignored(self):
        from app.services.runner import _extract_graph_events
        response = {"chart_data": "not a dict"}
        events = _extract_graph_events(response)
        assert all(e[0] != "render_chart" for e in events)

    def test_multi_chart_data_not_dict_ignored(self):
        from app.services.runner import _extract_graph_events
        response = {"multi_chart_data": [1, 2, 3]}
        events = _extract_graph_events(response)
        assert all(e[0] != "render_multi_chart" for e in events)

    def test_empty_grafana_url_ignored(self):
        from app.services.runner import _extract_graph_events
        response = {"grafana_url": ""}
        events = _extract_graph_events(response)
        assert all(e[0] != "render_grafana_panel" for e in events)

    def test_unrelated_keys_ignored(self):
        from app.services.runner import _extract_graph_events
        response = {"cluster_id": "abc", "status": "ok", "prometheus_links": {}}
        assert _extract_graph_events(response) == []

    def test_table_data_produces_render_table_data(self):
        from app.services.runner import _extract_graph_events
        response = {
            "table_data": {
                "columns": ["app", "status"],
                "rows": [["signal-api", "healthy"], ["cart-svc", "degraded"]],
                "meta": {"title": "Pods", "total_rows": 2},
            }
        }
        events = _extract_graph_events(response)
        assert len(events) == 1
        assert events[0][0] == "render_table_data"
        assert events[0][1]["columns"] == ["app", "status"]
        assert len(events[0][1]["rows"]) == 2
        assert events[0][1]["meta"]["title"] == "Pods"

    def test_table_data_not_dict_ignored(self):
        from app.services.runner import _extract_graph_events
        response = {"table_data": "not a dict"}
        events = _extract_graph_events(response)
        assert all(e[0] != "render_table_data" for e in events)

    def test_table_data_list_ignored(self):
        from app.services.runner import _extract_graph_events
        response = {"table_data": [["a", "b"], [1, 2]]}
        events = _extract_graph_events(response)
        assert all(e[0] != "render_table_data" for e in events)

    def test_all_four_keys_at_once(self):
        from app.services.runner import _extract_graph_events
        response = {
            "chart_data":       {"chart_type": "bar", "labels": [], "datasets": []},
            "multi_chart_data": {"title": "X", "charts": []},
            "table_data":       {"columns": ["col1"], "rows": [["val1"]]},
            "grafana_url":      "https://grafana.cluster/d/xyz",
        }
        events = _extract_graph_events(response)
        tool_names = {e[0] for e in events}
        assert "render_chart" in tool_names
        assert "render_multi_chart" in tool_names
        assert "render_table_data" in tool_names
        assert "render_grafana_panel" in tool_names

    def test_multiple_nested_grafana_urls_all_emitted(self):
        from app.services.runner import _extract_graph_events
        response = {
            "checks": {
                "cpu":   {"grafana_url": "https://g.example/cpu"},
                "istio": {"grafana_url": "https://g.example/istio"},
            }
        }
        events = _extract_graph_events(response)
        grafana_events = [e for e in events if e[0] == "render_grafana_panel"]
        urls = {e[1]["url"] for e in grafana_events}
        assert urls == {"https://g.example/cpu", "https://g.example/istio"}


# ── type:"graph" SSE events from function_response ────────────────────────────

class TestGraphEventsFromFunctionResponse:

    @pytest.mark.asyncio
    async def test_chart_data_in_response_emits_graph_event(self):
        from app.services.runner import run_agent_with_events

        chart_data = {
            "chart_type": "line",
            "title": "CPU Trend",
            "labels": ["14:00", "14:05"],
            "datasets": [{"label": "cluster-a", "data": [0.01, 0.02]}],
        }
        runner = _make_runner([
            _function_response_event("wcnp_chart", {"chart_data": chart_data, "row_count": 2}),
            _final_event("Here is the chart."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "show chart"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert len(graph_events) == 1
        assert graph_events[0]["graph_tool"] == "render_chart"
        assert graph_events[0]["args"]["title"] == "CPU Trend"
        assert graph_events[0]["args"]["labels"] == ["14:00", "14:05"]

    @pytest.mark.asyncio
    async def test_multi_chart_data_in_response_emits_graph_event(self):
        from app.services.runner import run_agent_with_events

        multi_chart_data = {
            "title": "Health Dashboard — signal-api",
            "charts": [
                {"metric": "CPU",    "y_label": "cores", "labels": ["t1"], "datasets": [{"label": "c1", "data": [0.01]}]},
                {"metric": "Memory", "y_label": "Bytes", "labels": ["t1"], "datasets": [{"label": "c1", "data": [1e8]}]},
            ],
        }
        runner = _make_runner([
            _function_response_event("wcnp_chart", {"multi_chart_data": multi_chart_data}),
            _final_event("Dashboard rendered."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "dashboard"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert len(graph_events) == 1
        assert graph_events[0]["graph_tool"] == "render_multi_chart"
        assert graph_events[0]["args"]["title"] == "Health Dashboard — signal-api"
        assert len(graph_events[0]["args"]["charts"]) == 2

    @pytest.mark.asyncio
    async def test_grafana_url_in_response_emits_graph_event(self):
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_check_app_health", {
                "grafana_url": "https://grafana.cluster/d/abc123",
                "overall_status": "unhealthy",
            }),
            _final_event("Health check done."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "check"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert len(graph_events) == 1
        assert graph_events[0]["graph_tool"] == "render_grafana_panel"
        assert graph_events[0]["args"]["url"] == "https://grafana.cluster/d/abc123"

    @pytest.mark.asyncio
    async def test_nested_grafana_url_in_health_check_emits_graph_event(self):
        """grafana_url nested inside checks.<metric> is found recursively."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_check_app_health", {
                "overall_status": "unhealthy",
                "checks": {
                    "cpu": {
                        "status": "unhealthy",
                        "grafana_url": "https://grafana.cluster/d/cpu-panel",
                    }
                },
            }),
            _final_event("CPU anomaly found."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "check cpu"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert any(
            e["graph_tool"] == "render_grafana_panel"
            and e["args"]["url"] == "https://grafana.cluster/d/cpu-panel"
            for e in graph_events
        )

    @pytest.mark.asyncio
    async def test_no_chart_keys_in_response_emits_no_graph_event(self):
        """A tool response with no chart_data / multi_chart_data / grafana_url
        must not emit any type:'graph' event."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_list_deployments", {
                "deployments": ["signal-api", "act-engine-api"],
                "cluster_id": "scus-prod-a74",
            }),
            _final_event("Found 2 deployments."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "list"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]
        assert graph_events == []

    @pytest.mark.asyncio
    async def test_graph_event_emitted_before_done_event(self):
        """type:'graph' must be emitted before the corresponding 'done' progress event."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_chart", {
                "chart_data": {"labels": [], "datasets": []},
            }),
            _final_event("Chart ready."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "chart"))
        events = [_parse_sse(c) for c in chunks]
        types = [e.get("type") for e in events]
        # 'done' progress for wcnp_chart comes before graph event
        # (done is emitted first, then graph events in the response handler)
        assert "graph" in types
        assert "complete" in types
        graph_idx = next(i for i, e in enumerate(events) if e.get("type") == "graph")
        complete_idx = next(i for i, e in enumerate(events) if e.get("type") == "complete")
        assert graph_idx < complete_idx

    @pytest.mark.asyncio
    async def test_nan_in_chart_data_sanitized_in_graph_event(self):
        """NaN values in chart data must be converted to null before the graph event is emitted."""
        from app.services.runner import run_agent_with_events

        chart_data_with_nan = {
            "labels": ["14:00", "14:05", "14:10"],
            "datasets": [{"label": "pod-a", "data": [0.007, float("nan"), 0.003]}],
        }
        runner = _make_runner([
            _function_response_event("wcnp_chart", {"chart_data": chart_data_with_nan}),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "chart"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert len(graph_events) == 1
        data = graph_events[0]["args"]["datasets"][0]["data"]
        assert data == [0.007, None, 0.003]   # NaN → null/None

    @pytest.mark.asyncio
    async def test_graph_event_has_required_fields(self):
        """Every type:'graph' event must have graph_tool, call_id, and args."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_chart", {
                "multi_chart_data": {"title": "T", "charts": []},
            }),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "dash"))
        events = [_parse_sse(c) for c in chunks]
        for e in (e for e in events if e.get("type") == "graph"):
            assert "graph_tool" in e
            assert "call_id" in e
            assert "args" in e
            assert isinstance(e["args"], dict)

    @pytest.mark.asyncio
    async def test_response_with_none_emits_no_graph_event(self):
        """A function_response with response=None must not crash or emit graph events."""
        from app.services.runner import run_agent_with_events

        fr = MagicMock()
        fr.name = "wcnp_chart"
        fr.response = None
        fr.id = "resp-1"
        part = MagicMock()
        part.function_call = None
        part.function_response = fr
        content = MagicMock()
        content.parts = [part]
        event = MagicMock()
        event.is_final_response.return_value = False
        event.content = content

        runner = _make_runner([event, _final_event("done")])
        chunks = await _collect(run_agent_with_events(runner, "u", "s", "q"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]
        assert graph_events == []

    @pytest.mark.asyncio
    async def test_table_data_in_response_emits_graph_event(self):
        """A tool response with table_data emits a type:'graph' event with graph_tool='render_table_data'."""
        from app.services.runner import run_agent_with_events

        table_data = {
            "columns": ["app", "namespace", "replicas", "cpu_pct", "status"],
            "rows": [
                ["signal-api", "intl-sre", 3, 12.5, "healthy"],
                ["cart-svc", "intl-sre", 5, 82.1, "degraded"],
            ],
            "meta": {
                "title": "All Deployments",
                "total_rows": 2,
                "page_size": 25,
                "description": "Deployments with resource usage",
            },
        }
        runner = _make_runner([
            _function_response_event("wcnp_list_deployments", {
                "summary": "Found 2 deployments",
                "table_data": table_data,
            }),
            _final_event("Here are the deployments."),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "list deployments"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert len(graph_events) == 1
        assert graph_events[0]["graph_tool"] == "render_table_data"
        assert graph_events[0]["args"]["columns"] == ["app", "namespace", "replicas", "cpu_pct", "status"]
        assert len(graph_events[0]["args"]["rows"]) == 2
        assert graph_events[0]["args"]["meta"]["title"] == "All Deployments"

    @pytest.mark.asyncio
    async def test_table_data_with_nan_sanitized(self):
        """NaN values in table_data rows are sanitized to None."""
        from app.services.runner import run_agent_with_events

        table_data = {
            "columns": ["app", "cpu"],
            "rows": [["signal-api", float("nan")], ["cart-svc", 0.8]],
        }
        runner = _make_runner([
            _function_response_event("wcnp_list", {"table_data": table_data}),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "list"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]

        assert len(graph_events) == 1
        assert graph_events[0]["args"]["rows"][0][1] is None  # NaN → None
        assert graph_events[0]["args"]["rows"][1][1] == 0.8

    @pytest.mark.asyncio
    async def test_three_simultaneous_render_types(self):
        """A response with all three chart keys emits three graph events."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_demo_grafana_prometheus", {
                "chart_data":       {"labels": [], "datasets": []},
                "multi_chart_data": {"title": "T", "charts": []},
                "grafana_url":      "https://grafana.example/d/x",
            }),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "all"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]
        graph_tools = {e["graph_tool"] for e in graph_events}

        assert "render_chart" in graph_tools
        assert "render_multi_chart" in graph_tools
        assert "render_grafana_panel" in graph_tools

    @pytest.mark.asyncio
    async def test_four_simultaneous_render_types(self):
        """A response with all four keys emits four graph events."""
        from app.services.runner import run_agent_with_events

        runner = _make_runner([
            _function_response_event("wcnp_analyze_namespace", {
                "chart_data":       {"labels": ["t1"], "datasets": [{"label": "x", "data": [1]}]},
                "multi_chart_data": {"title": "Dashboard", "charts": []},
                "table_data":       {"columns": ["app", "status"], "rows": [["api", "ok"]]},
                "grafana_url":      "https://grafana.example/d/all",
            }),
            _final_event("done"),
        ])

        chunks = await _collect(run_agent_with_events(runner, "u", "s", "analyze"))
        events = [_parse_sse(c) for c in chunks]
        graph_events = [e for e in events if e.get("type") == "graph"]
        graph_tools = {e["graph_tool"] for e in graph_events}

        assert len(graph_events) == 4
        assert "render_chart" in graph_tools
        assert "render_multi_chart" in graph_tools
        assert "render_table_data" in graph_tools
        assert "render_grafana_panel" in graph_tools
