# Graph Rendering — Protocol Reference

This document describes how the health-agent renders charts and panels in the UI.
It covers the full pipeline from MCP tool response → SSE event → UI component,
and tells LLM agents exactly what to do (and not do) to trigger graph rendering.

---

## How It Works (Pipeline Overview)

```
MCP tool returns { chart_data | multi_chart_data | grafana_url }
    ↓  runner.py detects the response key automatically
    ↓  emits  {"type": "graph", "graph_tool": "render_chart|render_multi_chart|render_grafana_panel", "args": {...}}  via SSE
    ↓  a2a-copilotkit-adapter.ts receives the graph event
    ↓  emits AG-UI TOOL_CALL events for the render tool
    ↓  CopilotKit stores as ActionExecutionMessage
    ↓  useCopilotAction({ name: "render_chart", render: ... }) intercepts
    ↓  React component renders in the chat UI
    ↓  event is persisted to Redis — survives page refresh
```

**The LLM does not need to reproduce chart data in render_* function call arguments.**
The agent backend auto-emits graph events directly from MCP tool responses.
The render_* tools still exist so the LLM can call them for edge cases, but the
primary rendering path is fully automatic.

---

## Three Graph Types

### 1. Single Chart — `render_chart`

Triggered when an MCP tool response contains **`chart_data`**.

```json
{
  "chart_data": {
    "chart_type": "line",
    "title": "CPU Usage (cores) — signal-api (Last 6h)",
    "x_label": "Time",
    "y_label": "CPU cores",
    "labels": ["14:50", "14:55", "15:00", "15:05"],
    "datasets": [
      { "label": "scus-prod-a74", "data": [0.007, 0.0035, 0.003, 0.014] },
      { "label": "uswest-prod-az-045", "data": [0.012, 0.009, 0.011, 0.016] }
    ]
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `chart_type` | `"line"` \| `"bar"` | Defaults to `"line"` |
| `title` | string | Shown in the chart header |
| `x_label` / `y_label` | string | Axis labels |
| `labels` | `string[]` | X-axis ticks (timestamps, categories) |
| `datasets` | array | One entry per series; `label` = legend name |

**MCP tools that auto-trigger this:** `wcnp_chart`

---

### 2. Multi-Panel Dashboard — `render_multi_chart`

Triggered when an MCP tool response contains **`multi_chart_data`**.
Renders N charts side-by-side with a synchronized crosshair hover.

```json
{
  "multi_chart_data": {
    "title": "Health Dashboard — signal-api (scus-prod-a74) Last 6h",
    "charts": [
      {
        "metric": "CPU Usage",
        "y_label": "CPU cores",
        "labels": ["14:50", "14:55", "15:00"],
        "datasets": [{ "label": "signal-api", "data": [0.007, 0.0035, 0.003] }]
      },
      {
        "metric": "Memory",
        "y_label": "Bytes",
        "labels": ["14:50", "14:55", "15:00"],
        "datasets": [{ "label": "signal-api", "data": [104857600, 104857600, 109051904] }]
      },
      {
        "metric": "Restarts",
        "y_label": "count",
        "labels": ["14:50", "14:55", "15:00"],
        "datasets": [{ "label": "signal-api", "data": [0, 0, 1] }]
      }
    ]
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | Dashboard title shown above all panels |
| `charts` | array | One entry per metric panel |
| `charts[].metric` | string | Panel title |
| `charts[].y_label` | string | Y-axis unit |
| `charts[].labels` | `string[]` | Shared X-axis (same for all panels) |
| `charts[].datasets` | array | Series per panel |

**MCP tools that auto-trigger this:** `wcnp_chart`

---

### 3. Grafana Panel Embed — `render_grafana_panel`

Triggered when an MCP tool response contains a **`grafana_url`** string field.
Renders a live interactive Grafana dashboard as an iframe in the chat.

```json
{
  "grafana_url": "https://grafana.scus-prod-a74.walmart.com/d/45c35f56.../deployments?orgId=1&var-namespace=intl-sre&from=1710000000000&to=1710021600000"
}
```

The URL is passed directly — do not construct Grafana URLs manually.
Use the `grafana_url` exactly as returned by the health check tool.

**MCP tools that auto-trigger this:** Any tool that returns `grafana_url` in its response
(e.g. anomaly results from `wcnp_check_app_health`, `wcnp_analyze`)

---

## Comparison Graphs (Multiple Clusters / Metrics Side-by-Side)

### Same metric across clusters — use `render_chart` with multiple datasets

Each cluster is a separate `dataset` entry, sharing the same `labels` (timestamps):

```json
{
  "chart_data": {
    "chart_type": "line",
    "title": "P95 Latency Comparison — signal-api (Last 1h)",
    "y_label": "Latency (ms)",
    "labels": ["15:00", "15:05", "15:10", "15:15"],
    "datasets": [
      { "label": "scus-prod-a74",        "data": [120, 145, 890, 1200] },
      { "label": "uswest-prod-az-045",   "data": [115, 118, 121, 119] },
      { "label": "eus2-prod-a44",        "data": [130, 128, 132, 135] }
    ]
  }
}
```

**Produced by:** `wcnp_chart` (automatically queries all clusters and merges)

---

### Multiple metrics for one app — use `render_multi_chart`

Each metric is a separate chart in the `charts` array, all sharing the same time axis:

```json
{
  "multi_chart_data": {
    "title": "Health Dashboard — signal-api (scus-prod-a74)",
    "charts": [
      { "metric": "CPU Usage",      "y_label": "cores",  "labels": [...], "datasets": [...] },
      { "metric": "Memory",         "y_label": "Bytes",  "labels": [...], "datasets": [...] },
      { "metric": "Restarts",       "y_label": "count",  "labels": [...], "datasets": [...] },
      { "metric": "P95 Latency",    "y_label": "ms",     "labels": [...], "datasets": [...] },
      { "metric": "Success Rate",   "y_label": "ratio",  "labels": [...], "datasets": [...] }
    ]
  }
}
```

**Produced by:** `wcnp_chart` (single call returns all 5 metrics pre-formatted)

---

### Multiple clusters × multiple metrics — call `wcnp_chart` per cluster

Call `wcnp_chart` once per cluster. Each call produces one `render_multi_chart`
panel automatically. The UI renders them stacked vertically with synchronized hover.

```
wcnp_chart(cluster_id="scus-prod-a74", ...)   → MultiChartBlock (cluster 1)
wcnp_chart(cluster_id="uswest-prod-az-045", ...) → MultiChartBlock (cluster 2)
```

---

## Session Persistence (Page Refresh)

Graph events are persisted to Redis as `type: "graph"` entries in the session event log.
On page refresh, `buildMessagesFromEvents` replays them as `ActionExecutionMessage` objects,
which CopilotKit converts to `generativeUI` render callbacks — charts reappear exactly as before.

**No extra work is needed to support persistence.** It is automatic for all three graph types.

---

## LLM Agent Rules

1. **Do not** call `render_chart` / `render_multi_chart` with large data arrays.
   The backend emits graph events automatically from tool responses.
   If you call render_* tools manually, keep datasets minimal (summary only).

2. **Do** call `wcnp_chart` for full dashboards — it returns pre-formatted
   `multi_chart_data` that auto-renders without any LLM data reproduction.

3. **Do** call `wcnp_chart` for cross-cluster metric comparisons —
   it queries all clusters in parallel and returns pre-formatted `chart_data`.

4. **Do** call `wcnp_chart` for a single PromQL range query rendered as a chart.

5. **Always** display `grafana_url` values from anomaly results — they trigger
   live Grafana panel embeds automatically.

6. **For text responses**, say "Charts rendered above" only after the tool call
   that produces chart data has completed — not before.
