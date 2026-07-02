"""
End-to-end tests for the graph rendering pipeline.

These tests hit the **running health-agent HTTP server** (localhost:8010) and
the **running health-mcp server** (localhost:8999).  They are skipped
automatically when either service is not reachable so the CI pipeline does
not fail on machines without the stack running.

Run manually after starting both services:
  cd health_mcp  && uvicorn app:app --port 8999
  cd health-agent && python src/main.py          # starts on port 8010

Then:
  pytest tests/e2e/test_graph_rendering.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

AGENT_BASE  = os.getenv("AGENT_BASE_URL",  "http://localhost:8010")
MCP_BASE    = os.getenv("MCP_BASE_URL",    "http://localhost:8999")
SKIP_REASON = "Agent or MCP not reachable — start both services to run E2E tests"
TIMEOUT     = 90   # seconds — LLM calls can be slow


# ── Service availability checks ───────────────────────────────────────────────

def _agent_available() -> bool:
    try:
        r = httpx.get(f"{AGENT_BASE}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _mcp_available() -> bool:
    try:
        r = httpx.get(f"{MCP_BASE}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _demo_tools_available() -> bool:
    try:
        r = httpx.get(f"{AGENT_BASE}/health", timeout=5)
        tools = r.json().get("mcp_tools", [])
        return any("demo" in t for t in tools)
    except Exception:
        return False


def _llm_working() -> bool:
    """Check if LLM calls actually complete (vs returning an error event)."""
    try:
        events = _stream("ping", session_id="_probe_llm_")
        return any(e.get("type") == "complete" for e in events)
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_agent_available() and _mcp_available()),
    reason=SKIP_REASON,
)
requires_demo_tools = pytest.mark.skipif(
    not _demo_tools_available(),
    reason="Demo tools not registered — ensure AGENT_ENV=local and local MCP is running",
)
requires_llm = pytest.mark.skipif(
    not (_agent_available() and _llm_working()),
    reason="LLM not returning complete responses — check gateway headers and credentials",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stream(query: str, session_id: str = "e2e-test") -> list[dict]:
    """POST to /a2a/stream and return all parsed SSE events."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": session_id,
            "message": {"role": "user", "parts": [{"type": "text", "text": query}]},
        },
    }
    events = []
    with httpx.stream("POST", f"{AGENT_BASE}/a2a/stream", json=payload, timeout=TIMEOUT) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def _graph_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "graph"]


def _complete_event(events: list[dict]) -> dict | None:
    for e in events:
        if e.get("type") == "complete":
            return e
    return None


# ── Use-case 1: CPU + Memory trend (last 1h vs yesterday vs 19d) ──────────────

@requires_stack
@requires_demo_tools
class TestTrendComparison:

    def test_trend_comparison_emits_graph_event(self):
        """wcnp_demo_trend_comparison response triggers a render_multi_chart graph event."""
        events = _stream(
            "Show me CPU and memory trend for signal-api in intl-sre comparing "
            "last 1 hour vs yesterday vs 19 days ago",
            session_id="e2e-trend-001",
        )
        graph = _graph_events(events)
        assert len(graph) >= 1, f"Expected at least 1 graph event, got: {graph}"

        multi_chart = next(
            (e for e in graph if e.get("graph_tool") == "render_multi_chart"), None
        )
        assert multi_chart is not None, "Expected render_multi_chart event"

    def test_trend_comparison_chart_has_cpu_and_memory(self):
        """The multi_chart_data must include CPU and Memory panels."""
        events = _stream(
            "Compare CPU and memory for signal-api in intl-sre: last hour vs yesterday vs 19 days ago",
            session_id="e2e-trend-002",
        )
        multi_events = [
            e for e in _graph_events(events)
            if e.get("graph_tool") == "render_multi_chart"
        ]
        assert multi_events, "No render_multi_chart event found"
        charts = multi_events[0]["args"].get("charts", [])
        metric_names = {c.get("metric", "").lower() for c in charts}
        assert any("cpu" in m for m in metric_names), f"No CPU chart in {metric_names}"
        assert any("mem" in m for m in metric_names), f"No Memory chart in {metric_names}"

    def test_trend_comparison_datasets_match_periods(self):
        """Each chart must have 3 datasets — one per time period."""
        events = _stream(
            "Show me CPU and memory trend for signal-api in intl-sre comparing "
            "last 1 hour, yesterday, and 19 days ago",
            session_id="e2e-trend-003",
        )
        multi_events = [
            e for e in _graph_events(events)
            if e.get("graph_tool") == "render_multi_chart"
        ]
        if not multi_events:
            pytest.skip("render_multi_chart not emitted — LLM may have used a different tool")
        charts = multi_events[0]["args"].get("charts", [])
        if charts:
            first_chart = charts[0]
            assert len(first_chart.get("datasets", [])) == 3

    def test_trend_comparison_no_nan_in_data(self):
        """No NaN values must appear anywhere in the graph event args."""
        events = _stream(
            "Trend comparison for signal-api in intl-sre last 1 hour vs yesterday vs 19 days ago",
            session_id="e2e-trend-nan",
        )
        for g in _graph_events(events):
            serialized = json.dumps(g)
            assert "NaN" not in serialized, "NaN found in graph event — sanitization failed"

    def test_stream_ends_with_complete_event(self):
        """Stream must always end with a complete event."""
        events = _stream(
            "CPU and memory trend for signal-api in intl-sre",
            session_id="e2e-trend-004",
        )
        complete = _complete_event(events)
        assert complete is not None, "No complete event in stream"
        assert isinstance(complete.get("text"), str)
        assert len(complete["text"]) > 0


# ── Use-case 2: Metrics snapshot across clusters ──────────────────────────────

@requires_stack
@requires_demo_tools
class TestMetricsSnapshot:

    def test_snapshot_emits_multi_chart_graph_event(self):
        """wcnp_demo_metrics_snapshot produces a render_multi_chart graph event."""
        events = _stream(
            "Show me a metrics snapshot for signal-api in intl-sre across "
            "scus-prod-a74 and uswest-prod-az-045 for the last hour",
            session_id="e2e-snapshot-001",
        )
        graph = _graph_events(events)
        multi = [e for e in graph if e.get("graph_tool") == "render_multi_chart"]
        assert multi, f"Expected render_multi_chart event, got graph tools: {[e.get('graph_tool') for e in graph]}"

    def test_snapshot_has_four_metric_panels(self):
        """The dashboard must have CPU, Memory, P95 Latency, and Istio CPU panels."""
        events = _stream(
            "Metrics snapshot for signal-api in intl-sre on scus-prod-a74 and uswest-prod-az-045",
            session_id="e2e-snapshot-002",
        )
        multi = [e for e in _graph_events(events) if e.get("graph_tool") == "render_multi_chart"]
        if not multi:
            pytest.skip("render_multi_chart not emitted")
        charts = multi[0]["args"].get("charts", [])
        assert len(charts) == 4, f"Expected 4 panels, got {len(charts)}: {[c.get('metric') for c in charts]}"

    def test_snapshot_datasets_one_per_cluster(self):
        """Each metric panel must have one dataset per cluster."""
        events = _stream(
            "Show metrics for signal-api in intl-sre on scus-prod-a74 and uswest-prod-az-045",
            session_id="e2e-snapshot-003",
        )
        multi = [e for e in _graph_events(events) if e.get("graph_tool") == "render_multi_chart"]
        if not multi:
            pytest.skip("render_multi_chart not emitted")
        for chart in multi[0]["args"].get("charts", []):
            assert len(chart.get("datasets", [])) == 2, \
                f"Expected 2 datasets for {chart.get('metric')}, got {len(chart.get('datasets', []))}"


# ── Use-case 3: Historical comparison across time offsets ─────────────────────

@requires_stack
@requires_demo_tools
class TestHistoricalComparison:

    def test_historical_comparison_emits_graph_event(self):
        """wcnp_demo_historical_comparison produces a render_multi_chart event."""
        events = _stream(
            "Compare CPU, memory, latency and istio CPU for signal-api in intl-sre "
            "across now, yesterday, 5 days ago, 1 week ago, and 19 days ago",
            session_id="e2e-historical-001",
        )
        graph = _graph_events(events)
        assert graph, "No graph events emitted"

    def test_historical_datasets_match_time_offsets(self):
        """Each chart panel must have 5 datasets (one per time offset)."""
        events = _stream(
            "Historical comparison for signal-api in intl-sre: "
            "now, yesterday, 5 days ago, 1 week ago, 19 days ago",
            session_id="e2e-historical-002",
        )
        multi = [e for e in _graph_events(events) if e.get("graph_tool") == "render_multi_chart"]
        if not multi:
            pytest.skip("render_multi_chart not emitted")
        for chart in multi[0]["args"].get("charts", []):
            n = len(chart.get("datasets", []))
            assert n == 5, f"Expected 5 datasets for {chart.get('metric')}, got {n}"


# ── Use-case 4: Grafana + Prometheus ─────────────────────────────────────────

@requires_stack
@requires_demo_tools
class TestGrafanaPrometheus:

    def test_demo_grafana_prometheus_emits_chart_and_grafana_events(self):
        """wcnp_demo_grafana_prometheus emits render_chart AND render_grafana_panel events."""
        events = _stream(
            "Show me the grafana dashboard and prometheus links for signal-api "
            "in intl-sre on scus-prod-a74",
            session_id="e2e-grafana-001",
        )
        graph = _graph_events(events)
        tools = {e.get("graph_tool") for e in graph}
        assert "render_chart" in tools or "render_multi_chart" in tools, \
            f"Expected chart event, got: {tools}"
        assert "render_grafana_panel" in tools, \
            f"Expected grafana panel event, got: {tools}"

    def test_grafana_event_has_valid_url(self):
        """The render_grafana_panel event must contain a valid https:// URL."""
        events = _stream(
            "Show me grafana dashboard for signal-api in intl-sre on scus-prod-a74 with istio dashboard",
            session_id="e2e-grafana-002",
        )
        grafana_events = [
            e for e in _graph_events(events)
            if e.get("graph_tool") == "render_grafana_panel"
        ]
        if not grafana_events:
            pytest.skip("render_grafana_panel not emitted")
        url = grafana_events[0]["args"].get("url", "")
        assert url.startswith("https://"), f"Expected https:// URL, got: {url!r}"
        assert "grafana" in url.lower(), f"URL doesn't look like Grafana: {url!r}"

    def test_prometheus_links_appear_in_llm_text(self):
        """The complete event text must contain Prometheus link(s)."""
        events = _stream(
            "Show me prometheus links for signal-api in intl-sre on cluster scus-prod-a74",
            session_id="e2e-prom-001",
        )
        complete = _complete_event(events)
        assert complete, "No complete event"
        text = complete.get("text", "")
        # LLM renders prometheus_links as markdown — look for the URL pattern
        assert "prometheus" in text.lower(), \
            f"Expected Prometheus links in LLM response, got: {text[:200]!r}"

    def test_stream_contains_progress_events_for_demo_tool(self):
        """The SSE stream must include progress events for the demo tool call."""
        events = _stream(
            "Show me grafana and prometheus for signal-api in intl-sre",
            session_id="e2e-grafana-003",
        )
        progress = [e for e in events if e.get("type") == "progress"]
        assert progress, "No progress events in stream"
        tool_names = {e.get("tool") for e in progress}
        assert any("demo" in (t or "") or "grafana" in (t or "") for t in tool_names), \
            f"Expected demo or grafana tool in progress, got: {tool_names}"


# ── Generic stream contract tests ─────────────────────────────────────────────

@requires_stack
class TestStreamContract:

    def test_health_endpoint_reachable(self):
        r = httpx.get(f"{AGENT_BASE}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    # Note: A2A endpoint tests removed — the A2A layer is now ADK-native
    # (A2AStarletteApplication, A2A SDK 0.3 message/send). Tests rely on
    # a live server with factory.py lifespan wired up.

    @requires_llm
    def test_every_stream_ends_with_complete_event(self):
        """All streams must include exactly one complete event with non-empty text."""
        events = _stream("What tools do you have available?", session_id="e2e-contract-001")
        complete = [e for e in events if e.get("type") == "complete"]
        assert len(complete) == 1
        assert complete[0].get("text", "").strip()

    def test_graph_events_are_valid_json(self):
        """All type:'graph' events must be valid JSON with required fields."""
        events = _stream(
            "Show me a CPU chart for signal-api in intl-sre",
            session_id="e2e-contract-002",
        )
        for e in _graph_events(events):
            assert "graph_tool" in e, f"Missing graph_tool in: {e}"
            assert "call_id" in e, f"Missing call_id in: {e}"
            assert "args" in e, f"Missing args in: {e}"
            assert isinstance(e["args"], dict), f"args not a dict in: {e}"

    def test_graph_event_args_are_json_serializable(self):
        """Graph event args must not contain NaN or non-serializable values."""
        events = _stream(
            "Show me CPU and memory trends for signal-api in intl-sre",
            session_id="e2e-contract-003",
        )
        for g in _graph_events(events):
            try:
                serialized = json.dumps(g["args"])
            except (TypeError, ValueError) as exc:
                pytest.fail(f"graph event args not serializable: {exc}\n{g['args']}")
            assert "NaN" not in serialized, f"NaN found in graph args: {serialized[:200]}"

    @requires_demo_tools
    def test_mcp_demo_tools_registered(self):
        """All four demo tools must appear in the agent's tool list."""
        r = httpx.get(f"{AGENT_BASE}/health", timeout=5)
        tools = r.json().get("mcp_tools", [])
        expected = {
            "wcnp_demo_trend_comparison",
            "wcnp_demo_metrics_snapshot",
            "wcnp_demo_historical_comparison",
            "wcnp_demo_grafana_prometheus",
        }
        missing = expected - set(tools)
        assert not missing, f"Demo tools not registered: {missing}"
