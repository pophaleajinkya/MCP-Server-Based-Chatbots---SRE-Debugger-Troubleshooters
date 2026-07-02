# MCP Tool UI Rendering Guide — A2UI v0.9 + AG-UI

This is the **complete reference** for building MCP tools that render rich UI
components in the SRE AI chat interface using the **A2UI v0.9 protocol**.

**v0.9 only.** No v0.8, no legacy SSE, no simplified props.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [A2UI v0.9 Quick Start](#2-a2ui-v09-quick-start)
3. [v0.9 Component Reference](#3-v09-component-reference)
4. [v0.9 Rules (Must Follow)](#4-v09-rules-must-follow)
5. [Examples — Health Check Report](#5-examples--health-check-report)
6. [Examples — Charts & Episode Data](#6-examples--charts--episode-data)
7. [Examples — Forms & Interaction](#7-examples--forms--interaction)
8. [Examples — Tabbed Dashboard](#8-examples--tabbed-dashboard)
9. [AG-UI Event Pipeline](#9-ag-ui-event-pipeline)
10. [Building a New MCP Server](#10-building-a-new-mcp-server)
11. [Session Persistence & Replay](#11-session-persistence--replay)
12. [Constraints & Limits](#12-constraints--limits)

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│  MCP Tool Server                                           │
│  Returns JSON + <a2ui>[...v0.9 components...]</a2ui>      │
└──────────────────────┬─────────────────────────────────────┘
                       │ MCP TextContent
                       ▼
┌────────────────────────────────────────────────────────────┐
│  super-agent (ADK 1.28)                                    │
│  A2aAgentExecutor → standard A2A protocol                  │
│  A2UI blocks pass through as artifact text                 │
└──────────────────────┬─────────────────────────────────────┘
                       │ A2A SSE (status-update, artifact-update)
                       ▼
┌────────────────────────────────────────────────────────────┐
│  sre-ai-ui (Next.js + CopilotKit)                          │
│  Detects <a2ui> tags → renders v0.9 components             │
│  A2UIRenderer.tsx: 14 basic catalog + 2 custom (Table,Chart)│
└────────────────────────────────────────────────────────────┘
```

---

## 2. A2UI v0.9 Quick Start

### Step 1: Helper functions

```python
import json, uuid
from mcp.types import TextContent

A2UI_OPEN = "<a2ui>"
A2UI_CLOSE = "</a2ui>"

def _id():
    return uuid.uuid4().hex[:8]

def wrap_a2ui(a2ui_json: list[dict]) -> str:
    return f"\n{A2UI_OPEN}{json.dumps(a2ui_json)}{A2UI_CLOSE}"

def _surface(sid: str) -> dict:
    return {"version": "v0.9", "createSurface": {
        "surfaceId": sid,
        "catalogId": "https://a2ui.org/specification/v0_9/basic_catalog.json",
    }}

def _update(sid: str, components: list[dict]) -> dict:
    return {"version": "v0.9", "updateComponents": {
        "surfaceId": sid, "components": components,
    }}
```

### Step 2: Build v0.9 components

```python
async def my_tool(namespace: str) -> list[TextContent]:
    result = {"status": "healthy", "count": 5}

    sid = f"s-{_id()}"
    card_content_id = f"cc-{_id()}"
    title_id = f"t-{_id()}"
    status_id = f"st-{_id()}"

    components = [
        # Card with child → Column → Text children (v0.9 spec)
        {"id": f"card-{_id()}", "component": "Card", "child": card_content_id},
        {"id": card_content_id, "component": "Column", "children": [title_id, status_id]},
        {"id": title_id, "component": "Text", "text": f"Namespace: {namespace}", "variant": "h3"},
        {"id": status_id, "component": "Text", "text": "All 5 apps healthy", "variant": "body"},
    ]

    a2ui = [_surface(sid), _update(sid, components)]
    return [TextContent(type="text", text=json.dumps(result) + wrap_a2ui(a2ui))]
```

---

## 3. v0.9 Component Reference

### Basic Catalog (14 components)

#### Layout

| Component | Fields | Description |
|-----------|--------|-------------|
| **Row** | `children[]`, `justify`, `align` | Horizontal layout |
| **Column** | `children[]`, `justify`, `align` | Vertical layout |
| **List** | `children[]`, `direction` | Scrollable list |

#### Display

| Component | Fields | Description |
|-----------|--------|-------------|
| **Text** | `text`, `variant` (h1-h5, body, caption) | All text content |
| **Image** | `url`, `fit` (cover/contain) | Images |
| **Icon** | `name` (check, warning, error, info, search, close, settings, star) | Semantic icons |
| **Divider** | `axis` (horizontal/vertical) | Visual separator |

#### Interactive

| Component | Fields | Description |
|-----------|--------|-------------|
| **Button** | `child` (ID), `variant`, `action` | Clickable button |
| **TextField** | `label`, `value`, `textFieldType` | Text input |
| **CheckBox** | `label`, `value` | Boolean toggle |
| **Slider** | `value`, `minValue`, `maxValue` | Range input |
| **DateTimeInput** | `value`, `enableDate`, `enableTime` | Date/time picker |
| **ChoicePicker** | `options[]`, `maxAllowedSelections` | Selection |

#### Container

| Component | Fields | Description |
|-----------|--------|-------------|
| **Card** | `child` (single ID) | Bordered container |
| **Modal** | `entryPointChild`, `contentChild` | Overlay dialog |
| **Tabs** | `tabItems[{title, child}]` | Tabbed panels |

### Custom Catalog (2 components)

| Component | Fields | Description |
|-----------|--------|-------------|
| **Table** | `columns[]`, `rows[][]` | Data table |
| **Chart** | `chartType`, `title`, `xAxis.labels`, `series[]` | Line/bar/pie chart |

---

## 4. v0.9 Rules (Must Follow)

### DO

```python
# Card: use `child` pointing to a Column with Text children
{"id": "card1", "component": "Card", "child": "card1-content"}
{"id": "card1-content", "component": "Column", "children": ["title1", "sub1"]}
{"id": "title1", "component": "Text", "text": "My Title", "variant": "h3"}
{"id": "sub1", "component": "Text", "text": "My subtitle"}

# Button: use `child` (ID) + `action`
{"id": "btn1", "component": "Button", "child": "btn1-label", "variant": "secondary",
 "action": {"event": {"name": "open_url", "data": {"url": "https://..."}}}}
{"id": "btn1-label", "component": "Text", "text": "Open Dashboard"}

# Headings: use Text with variant
{"id": "h1", "component": "Text", "text": "Section Title", "variant": "h4"}

# Chart: use chartType, xAxis.labels, series
{"id": "c1", "component": "Chart", "chartType": "line", "title": "CPU Usage",
 "xAxis": {"labels": ["14:00", "14:05"]}, "series": [{"label": "cpu", "data": [42, 43]}]}

# Table: columns and rows are direct fields (not inside props)
{"id": "t1", "component": "Table", "columns": ["App", "Status"], "rows": [["api", "healthy"]]}
```

### DON'T

```python
# ❌ Card with title/subtitle props
{"id": "card1", "component": "Card", "props": {"title": "...", "subtitle": "..."}}

# ❌ Button with label/url props
{"id": "btn1", "component": "Button", "props": {"label": "Click", "url": "https://..."}}

# ❌ Heading component (use Text with variant)
{"id": "h1", "component": "Heading", "props": {"text": "Title", "level": 3}}

# ❌ Props wrapper (v0.8 style)
{"id": "t1", "component": "Text", "props": {"text": "Hello"}}

# ❌ `type` field (v0.8 style)
{"id": "t1", "type": "Text", "text": "Hello"}

# ❌ Container, Map, Surface, Dropdown, DatePicker, TimeSelector, SubmitButton, Markdown
# These are NOT in v0.9. Use their replacements:
#   Container → Column/Row/Card
#   Map → Image (static) or Button (external link)
#   Surface → Card
#   Dropdown → ChoicePicker
#   DatePicker/TimeSelector → DateTimeInput
#   SubmitButton → Button with action
#   Markdown → Text (auto-detects markdown with # or \n)
```

---

## 5. Examples — Health Check Report

```python
def health_result_to_a2ui(result):
    sid = f"s-{_id()}"
    root_id = f"r-{_id()}"

    # Status card (v0.9: Card → child → Column → Text children)
    card_id, cc_id = f"card-{_id()}", f"cc-{_id()}"
    title_id, status_id = f"t-{_id()}", f"st-{_id()}"
    icon_id, status_row_id = f"i-{_id()}", f"sr-{_id()}"

    components = [
        {"id": root_id, "component": "Column", "children": [card_id]},
        {"id": card_id, "component": "Card", "child": cc_id},
        {"id": cc_id, "component": "Column", "children": [title_id, status_row_id]},
        {"id": title_id, "component": "Text", "text": "signal-api — iro-prod", "variant": "h3"},
        {"id": status_row_id, "component": "Row", "children": [icon_id, status_id], "align": "center"},
        {"id": icon_id, "component": "Icon", "name": "error"},
        {"id": status_id, "component": "Text", "text": "Overall: UNHEALTHY | Attribution: downstream_dependency"},
    ]

    return [_surface(sid), _update(sid, components)]
```

---

## 6. Examples — Charts & Episode Data

### Episode Chart (v0.9)

```python
def episode_chart_to_a2ui(check_name, app, cluster, episode_series):
    sid = f"s-{_id()}"
    card_id, cc_id = f"card-{_id()}", f"cc-{_id()}"
    title_id, info_id, chart_id = f"t-{_id()}", f"i-{_id()}", f"ch-{_id()}"

    components = [
        {"id": f"r-{_id()}", "component": "Column", "children": [card_id, chart_id]},
        {"id": card_id, "component": "Card", "child": cc_id},
        {"id": cc_id, "component": "Column", "children": [title_id, info_id]},
        {"id": title_id, "component": "Text", "text": f"Episode: {check_name} — {app} ({cluster})", "variant": "h4"},
        {"id": info_id, "component": "Text", "text": "Started: 14:00Z | Peak: 850.42 | Duration: 75 min"},
        {"id": chart_id, "component": "Chart", "chartType": "line",
         "title": f"{check_name} over time",
         "xAxis": {"labels": episode_series["labels"]},
         "series": [
             {"label": check_name, "data": episode_series["data"]},
             {"label": "Threshold", "data": [episode_series["threshold"]] * len(episode_series["labels"])},
             {"label": "Baseline", "data": [episode_series["baseline"]] * len(episode_series["labels"])},
         ]},
    ]

    return [_surface(sid), _update(sid, components)]
```

### Multi-Metric Dashboard (v0.9)

```python
def multi_chart_to_a2ui(multi_chart_data):
    sid = f"s-{_id()}"
    title_id = f"t-{_id()}"
    children = [title_id]
    components = [
        {"id": f"r-{_id()}", "component": "Column", "children": children},
        {"id": title_id, "component": "Text", "text": multi_chart_data["title"], "variant": "h3"},
    ]
    for chart in multi_chart_data["charts"]:
        cid = f"ch-{_id()}"
        children.append(cid)
        components.append({"id": cid, "component": "Chart", "chartType": "line",
            "title": f"{chart['metric']} ({chart.get('y_label', '')})",
            "xAxis": {"labels": chart["labels"]}, "series": chart["datasets"]})
    return [_surface(sid), _update(sid, components)]
```

---

## 7. Examples — Forms & Interaction

### Incident Investigation Form (v0.9)

```python
form_card_id, form_col_id = f"fc-{_id()}", f"fcol-{_id()}"
heading_id = f"h-{_id()}"

components = [
    {"id": f"r-{_id()}", "component": "Column", "children": [heading_id, form_card_id]},
    {"id": heading_id, "component": "Text", "text": "Incident Investigation", "variant": "h3"},
    {"id": form_card_id, "component": "Card", "child": form_col_id},
    {"id": form_col_id, "component": "Column", "children": ["ns", "app", "time", "btn"]},
    {"id": "ns", "component": "TextField", "label": "Namespace", "textFieldType": "shortText"},
    {"id": "app", "component": "TextField", "label": "App Name", "textFieldType": "shortText"},
    {"id": "time", "component": "DateTimeInput", "label": "Incident Date", "enableDate": True, "enableTime": False},
    {"id": "btn", "component": "Button", "child": "btn-text", "variant": "primary",
     "action": {"event": {"name": "run_investigation"}}},
    {"id": "btn-text", "component": "Text", "text": "Run Investigation"},
]
```

### Cluster Selector (v0.9)

```python
components = [
    {"id": "root", "component": "Row", "children": ["cluster", "env"]},
    {"id": "cluster", "component": "ChoicePicker", "label": "Cluster",
     "options": [{"label": "US East (eus2-prod-a44)", "value": "eus2-prod-a44"},
                 {"label": "US Central (scus-prod-a56)", "value": "scus-prod-a56"}],
     "maxAllowedSelections": 1},
    {"id": "env", "component": "ChoicePicker", "label": "Environment",
     "options": [{"label": "prod", "value": "prod"}, {"label": "stage", "value": "stage"}],
     "maxAllowedSelections": 1},
]
```

---

## 8. Examples — Tabbed Dashboard

The health check report uses **Tabs** to organize sections:

```python
components = [
    {"id": "root", "component": "Column", "children": ["status-card", "divider", "tabs", "links"]},

    # Status Card
    {"id": "status-card", "component": "Card", "child": "sc-content"},
    {"id": "sc-content", "component": "Column", "children": ["sc-title", "sc-status"]},
    {"id": "sc-title", "component": "Text", "text": "signal-api — iro-prod", "variant": "h3"},
    {"id": "sc-status", "component": "Row", "children": ["sc-icon", "sc-text"], "align": "center"},
    {"id": "sc-icon", "component": "Icon", "name": "error"},
    {"id": "sc-text", "component": "Text", "text": "Overall: UNHEALTHY"},

    {"id": "divider", "component": "Divider"},

    # Tabs
    {"id": "tabs", "component": "Tabs", "tabItems": [
        {"title": "Root Cause", "child": "rc-tab"},
        {"title": "Anomalies", "child": "an-tab"},
        {"title": "Graphs", "child": "gr-tab"},
        {"title": "Correlations", "child": "co-tab"},
        {"title": "Timeline", "child": "tl-tab"},
    ]},

    # Each tab is a Column with content
    {"id": "rc-tab", "component": "Column", "children": ["rc-title", "rc-info", "rc-cascade"]},
    {"id": "rc-title", "component": "Text", "text": "Root Cause Analysis", "variant": "h4"},
    {"id": "rc-info", "component": "Text", "text": "Primary signal: **istio_client_latency** | Started: 14:00:00Z"},
    {"id": "rc-cascade", "component": "Table", "columns": ["Check", "Lag (seconds)"],
     "rows": [["istio_client_success", "120"], ["istio_server_latency", "225"]]},

    {"id": "an-tab", "component": "Column", "children": ["an-title", "an-table"]},
    {"id": "an-title", "component": "Text", "text": "Anomaly Details (3)", "variant": "h4"},
    {"id": "an-table", "component": "Table",
     "columns": ["Check", "Status", "Episode Start", "Peak", "Baseline", "Deviation %"],
     "rows": [["istio_client_latency", "unhealthy", "14:00Z", "850", "120", "+605%"]]},

    {"id": "gr-tab", "component": "Column", "children": ["gr-title", "gr-chart"]},
    {"id": "gr-title", "component": "Text", "text": "Episode Graphs", "variant": "h4"},
    {"id": "gr-chart", "component": "Chart", "chartType": "line",
     "title": "istio_client_latency — signal-api (eus2-prod-a44)",
     "xAxis": {"labels": ["13:00", "13:30", "14:00", "14:15"]},
     "series": [
         {"label": "Latency", "data": [120, 125, 850, 720]},
         {"label": "Threshold", "data": [150, 150, 150, 150]},
         {"label": "Baseline", "data": [120, 120, 120, 120]},
     ]},

    # ... more tabs (correlations, timeline)

    # Prometheus links
    {"id": "links", "component": "Row", "children": ["btn1"]},
    {"id": "btn1", "component": "Button", "child": "btn1-text", "variant": "secondary",
     "action": {"event": {"name": "open_url", "data": {"url": "https://prom.example.com/graph?q=latency"}}}},
    {"id": "btn1-text", "component": "Text", "text": "Prometheus: Latency"},
]
```

---

## 9. AG-UI Event Pipeline

| AG-UI Event | When |
|---|---|
| `RUN_STARTED` | Stream begins |
| `TEXT_MESSAGE_*` | LLM text (after A2UI stripped) |
| `TOOL_CALL_*` for `render_a2ui` | `<a2ui>` block detected |
| `TOOL_CALL_*` for `render_progress` | Function call/response DataParts |
| `RUN_FINISHED` | Stream ends |

```
MCP tool returns: {"status": "ok"}\n<a2ui>[...]</a2ui>
    ↓ A2A artifact-update
    ↓ A2AAgent detects <a2ui>
    ↓ Emits TOOL_CALL for render_a2ui
    ↓ groupIntoTurns → kind: "a2ui"
    ↓ <A2UIRenderer data={...} />
```

---

## 10. Building a New MCP Server

### Checklist

- [ ] Use `component` field (NOT `type`)
- [ ] Props are top-level (NOT inside `props: {}`)
- [ ] Card uses `child` (NOT `title`/`subtitle`)
- [ ] Button uses `child` + `action` (NOT `label`/`url`)
- [ ] Text uses `variant` for headings (NOT separate `Heading` component)
- [ ] Chart uses `chartType`, `xAxis.labels`, `series` (NOT `type`, `labels`, `datasets`)
- [ ] Table uses top-level `columns`, `rows` (NOT inside `props`)
- [ ] Include `createSurface` before `updateComponents`
- [ ] Wrap in `<a2ui>...</a2ui>` tags
- [ ] No `Container`, `Map`, `Surface`, `Dropdown`, `DatePicker`, `TimeSelector`, `SubmitButton`, `Heading`, `Markdown`

---

## 11. Session Persistence & Replay

A2UI blocks in `artifact-update` events are persisted to Redis by the
`after_event` interceptor. On page refresh, `buildMessagesFromEvents()`
reconstructs messages and the `A2UIRenderer` re-renders all surfaces.

No additional work needed.

---

## 12. Constraints & Limits

| Constraint | Limit | Workaround |
|---|---|---|
| A2UI payload | ~100 KB recommended | Downsample time-series to ~30 points |
| LLM context | Full response enters context | Use `summary` field for LLM text |
| Component format | v0.9 flat only | No `props` wrapper, no `type` field |
| Episode series | ~30 points (auto) | Automatic in episode detector |
