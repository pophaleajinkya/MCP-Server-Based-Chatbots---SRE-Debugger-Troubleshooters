# MCP Apps — Interactive Widget Guide

Build interactive HTML/JS widgets that render inside the chat as sandboxed
iframes. Widgets can call MCP tools, receive live data, and let users interact
with buttons, forms, charts, and dashboards — all without leaving the
conversation.

**MCP Apps coexists with A2UI.** Use A2UI v0.9 for lightweight declarative
components (cards, tables, icons). Use MCP Apps when you need full interactivity
(real-time charts, forms that call tools, live dashboards with refresh).

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Quick Start — Your First Widget](#2-quick-start--your-first-widget)
3. [Widget HTML Template](#3-widget-html-template)
4. [Receiving Data in the Widget](#4-receiving-data-in-the-widget)
5. [Calling MCP Tools from the Widget](#5-calling-mcp-tools-from-the-widget)
6. [Forms — Collecting User Input](#6-forms--collecting-user-input)
7. [Charts — Interactive Visualizations](#7-charts--interactive-visualizations)
8. [Dashboards — Multi-Section Layouts](#8-dashboards--multi-section-layouts)
9. [Real-Time Updates](#9-real-time-updates)
10. [Sending Messages Back to the Agent](#10-sending-messages-back-to-the-agent)
11. [Security Model](#11-security-model)
12. [Registering Resources in Your MCP Server](#12-registering-resources-in-your-mcp-server)
13. [Adding _meta.ui to Tool Definitions](#13-adding-metaui-to-tool-definitions)
14. [Complete Example — Episode Chart Widget](#14-complete-example--episode-chart-widget)
15. [Complete Example — Health Dashboard Widget](#15-complete-example--health-dashboard-widget)
16. [A2UI vs MCP Apps — When to Use Which](#16-a2ui-vs-mcp-apps--when-to-use-which)

---

## 1. Architecture

```
User asks question
  → LLM calls MCP tool (has _meta.ui.resourceUri = "ui://my-server/widget")
  → MCP server returns tool result (JSON)
  → A2A stream carries function_call DataPart with ui metadata
  → UI adapter detects ui:// resourceUri
  → UI fetches HTML from /api/mcp-proxy → /mcp-proxy → MCP server resources/read
  → HTML renders in sandboxed iframe
  → User interacts (clicks button, fills form)
  → iframe calls MCP tools via postMessage → /api/mcp-proxy → MCP server
  → Updated data flows back into the iframe
```

The widget runs inside a sandboxed `<iframe>` — it cannot access the parent
page, cookies, or localStorage. All communication goes through JSON-RPC
`postMessage`.

---

## 2. Quick Start — Your First Widget

### Step 1: Create the HTML file

```html
<!-- src/ui/hello.html -->
<!DOCTYPE html>
<html>
<head><title>Hello Widget</title></head>
<body>
  <h1 id="title">Hello!</h1>
  <p id="result">Waiting for data...</p>

  <script type="module">
    import { App } from "https://esm.sh/@modelcontextprotocol/ext-apps@0.1.5";

    const app = new App();

    // Called when the tool result arrives
    app.ontoolresult = (result) => {
      document.getElementById("result").textContent = JSON.stringify(result, null, 2);
    };

    // Called when the tool input arrives
    app.oninput = (input) => {
      document.getElementById("title").textContent = `Hello, ${input.name || "World"}!`;
    };

    await app.connect();
  </script>
</body>
</html>
```

### Step 2: Register in your MCP server

```python
# In app.py
from mcp_ui_server import create_ui_resource

@server.read_resource()
async def handle_read_resource(uri):
    if str(uri) == "ui://my-server/hello":
        html = Path("src/ui/hello.html").read_text()
        return [create_ui_resource({
            "uri": "ui://my-server/hello",
            "content": {"type": "rawHtml", "htmlString": html},
            "encoding": "text",
        })]
    raise ValueError(f"Unknown: {uri}")
```

### Step 3: Add `_meta.ui` to your tool

```python
Tool(
    name="greet_user",
    description="Greet the user with a widget",
    inputSchema={"type": "object", "properties": {"name": {"type": "string"}}},
    _meta={"ui": {"resourceUri": "ui://my-server/hello"}},
)
```

That's it. When the LLM calls `greet_user`, the chat renders the widget.

---

## 3. Widget HTML Template

Every widget follows this structure:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    /* Your styles — will render inside the iframe */
    body { font-family: system-ui, sans-serif; padding: 16px; }

    /* Support dark mode */
    @media (prefers-color-scheme: dark) {
      body { background: #1a2233; color: #e5e7eb; }
    }
  </style>
</head>
<body>
  <!-- Your UI -->

  <script type="module">
    import { App } from "https://esm.sh/@modelcontextprotocol/ext-apps@0.1.5";

    const app = new App();

    app.ontoolresult = (result) => { /* handle tool result */ };
    app.oninput = (input) => { /* handle tool input/args */ };

    await app.connect();
  </script>
</body>
</html>
```

Key points:
- Use `type="module"` for the script tag (ESM import)
- Import `App` from the CDN — no build step needed
- Call `await app.connect()` at the end
- Support dark mode with `@media (prefers-color-scheme: dark)`
- Keep widgets self-contained — inline all CSS, load JS from CDN

---

## 4. Receiving Data in the Widget

### Tool Result (automatic)

When the MCP tool returns its result, `app.ontoolresult` fires:

```javascript
app.ontoolresult = (result) => {
  // result is the MCP tool's return value
  // For TextContent tools: result.content[0].text contains the JSON string
  const text = result?.content?.[0]?.text || JSON.stringify(result);
  const data = JSON.parse(text);

  // Now render the data
  renderTable(data.results);
};
```

### Tool Input (automatic)

The tool's input arguments arrive via `app.oninput`:

```javascript
app.oninput = (input) => {
  // input is the arguments passed to the tool
  // e.g. { namespace: "iro-prod", app: "signal-api" }
  document.getElementById("namespace").textContent = input.namespace;
};
```

---

## 5. Calling MCP Tools from the Widget

Widgets can call any tool on the MCP server:

```javascript
// Call a tool and get the result
const result = await app.callServerTool({
  name: "wcnp_check_app_health",
  arguments: {
    namespace: "iro-prod",
    app: "signal-api",
  },
});

// Parse the result
const text = result?.content?.[0]?.text;
const healthData = JSON.parse(text);
renderDashboard(healthData);
```

This enables **interactive widgets**: the user clicks "Refresh" and the widget
calls the tool again to get fresh data.

---

## 6. Forms — Collecting User Input

### Simple Form

```html
<form id="queryForm">
  <label>Namespace:
    <input type="text" id="ns" placeholder="e.g. iro-prod" required>
  </label>
  <label>App:
    <input type="text" id="app" placeholder="e.g. signal-api">
  </label>
  <label>Time Range:
    <select id="hours">
      <option value="1">Last 1 hour</option>
      <option value="6">Last 6 hours</option>
      <option value="24">Last 24 hours</option>
    </select>
  </label>
  <button type="submit">Check Health</button>
</form>
<div id="results"></div>

<script type="module">
  import { App } from "https://esm.sh/@modelcontextprotocol/ext-apps@0.1.5";
  const app = new App();

  document.getElementById("queryForm").onsubmit = async (e) => {
    e.preventDefault();
    const ns = document.getElementById("ns").value;
    const appName = document.getElementById("app").value;

    document.getElementById("results").textContent = "Loading...";

    const result = await app.callServerTool({
      name: "wcnp_check_app_health",
      arguments: { namespace: ns, ...(appName ? { app: appName } : {}) },
    });

    const text = result?.content?.[0]?.text;
    const data = JSON.parse(text.split("\n<a2ui>")[0]); // Strip A2UI tags
    document.getElementById("results").innerHTML = renderHealthTable(data);
  };

  await app.connect();
</script>
```

### Form with Dependent Fields

```javascript
// Show different fields based on selection
document.getElementById("checkType").onchange = (e) => {
  const type = e.target.value;
  document.getElementById("prometheusFields").style.display =
    type === "custom_query" ? "block" : "none";
  document.getElementById("metricFields").style.display =
    type === "built_in" ? "block" : "none";
};
```

### Multi-Step Wizard

```javascript
let step = 1;
const steps = document.querySelectorAll(".step");

function showStep(n) {
  steps.forEach((s, i) => s.style.display = i === n - 1 ? "block" : "none");
}

document.getElementById("nextBtn").onclick = () => {
  if (step < steps.length) showStep(++step);
};

document.getElementById("backBtn").onclick = () => {
  if (step > 1) showStep(--step);
};

document.getElementById("submitBtn").onclick = async () => {
  const formData = collectAllSteps();
  const result = await app.callServerTool({
    name: "wcnp_analyze",
    arguments: formData,
  });
  showResults(result);
};
```

---

## 7. Charts — Interactive Visualizations

### Chart.js Line Chart

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js"></script>
<canvas id="chart" height="300"></canvas>

<script type="module">
  import { App } from "https://esm.sh/@modelcontextprotocol/ext-apps@0.1.5";
  const app = new App();

  app.ontoolresult = (result) => {
    const text = result?.content?.[0]?.text || "{}";
    const data = JSON.parse(text.split("\n<a2ui>")[0]);
    const series = data.episode_series;
    if (!series) return;

    new Chart(document.getElementById("chart"), {
      type: "line",
      data: {
        labels: series.labels,
        datasets: [
          { label: "Value", data: series.data, borderColor: "#0071CE", fill: true,
            backgroundColor: "rgba(0,113,206,0.1)", tension: 0.3 },
          { label: "Threshold", data: Array(series.labels.length).fill(series.threshold),
            borderColor: "#ef4444", borderDash: [6, 3], pointRadius: 0 },
          { label: "Baseline", data: Array(series.labels.length).fill(series.baseline),
            borderColor: "#22c55e", borderDash: [4, 4], pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" } },
      },
    });
  };

  await app.connect();
</script>
```

### Bar Chart Comparison

```javascript
const mcd = data.multi_chart_data;
mcd.charts.forEach((chart, i) => {
  const canvas = document.createElement("canvas");
  document.getElementById("charts").appendChild(canvas);

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: chart.labels,
      datasets: chart.datasets.map((ds, j) => ({
        label: ds.label,
        data: ds.data,
        backgroundColor: COLORS[j % COLORS.length],
      })),
    },
    options: { plugins: { title: { display: true, text: chart.metric } } },
  });
});
```

---

## 8. Dashboards — Multi-Section Layouts

### Tabbed Dashboard

```html
<div class="tabs">
  <button class="tab active" data-tab="overview">Overview</button>
  <button class="tab" data-tab="anomalies">Anomalies</button>
  <button class="tab" data-tab="charts">Charts</button>
</div>
<div class="tab-content" id="overview">...</div>
<div class="tab-content" id="anomalies" style="display:none">...</div>
<div class="tab-content" id="charts" style="display:none">...</div>

<script>
  document.querySelectorAll(".tab").forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
      tab.classList.add("active");
      document.getElementById(tab.dataset.tab).style.display = "block";
    };
  });
</script>
```

### Auto-Refresh Dashboard

```javascript
let refreshInterval = null;

document.getElementById("autoRefresh").onchange = (e) => {
  if (e.target.checked) {
    refreshInterval = setInterval(async () => {
      const result = await app.callServerTool({
        name: "wcnp_check_app_health",
        arguments: currentArgs,
      });
      updateDashboard(result);
    }, 30000); // Refresh every 30s
  } else {
    clearInterval(refreshInterval);
  }
};
```

---

## 9. Real-Time Updates

### Polling for Changes

```javascript
async function pollMetrics() {
  while (true) {
    const result = await app.callServerTool({
      name: "wcnp_query_prometheus",
      arguments: { cluster_id: "eus2-prod-a44", namespace: "iro-prod", query: currentQuery },
    });
    updateChart(result);
    await new Promise(r => setTimeout(r, 10000)); // Poll every 10s
  }
}
```

### Update Model Context

When the user makes a selection in the widget, notify the agent:

```javascript
await app.updateModelContext({
  content: [{ type: "text", text: "User selected cluster: eus2-prod-a44" }],
});
```

This lets the agent respond to user interactions within the widget.

---

## 10. Sending Messages Back to the Agent

### Open External Links

```javascript
// Opens in user's browser (not in iframe)
await app.openLink({ url: "https://grafana.example.com/dashboard" });
```

### Send Follow-Up Message

```javascript
// Send a message that appears in the conversation
await app.sendMessage({
  content: [{ type: "text", text: "Based on the dashboard, I'd recommend checking the CPU usage on eus2-prod-a44." }],
});
```

---

## 11. Security Model

| Layer | Protection |
|-------|-----------|
| Iframe sandbox | `sandbox="allow-scripts"` — no access to parent page |
| Same-origin policy | Widget cannot read parent cookies/localStorage |
| JSON-RPC only | All communication is structured JSON via `postMessage` |
| Proxy routing | Widget calls go through `/api/mcp-proxy` — no direct MCP access |
| Content review | Host can inspect HTML before rendering |

Widgets cannot:
- Access parent DOM
- Read cookies or auth tokens
- Navigate the parent page
- Make arbitrary network requests (CSP enforced)

Widgets can:
- Call MCP tools via `app.callServerTool()`
- Read MCP resources via the proxy
- Open links in the user's browser (via `app.openLink()`)
- Update the agent's context (via `app.updateModelContext()`)

---

## 12. Registering Resources in Your MCP Server

### Using mcp-ui-server (Python)

```bash
pip install mcp-ui-server
```

```python
from mcp_ui_server import create_ui_resource
from pathlib import Path

# In your read_resource handler:
@server.read_resource()
async def handle_read_resource(uri):
    uri_str = str(uri)

    # UI resources
    if uri_str.startswith("ui://"):
        html_files = {
            "ui://my-server/dashboard": "src/ui/dashboard.html",
            "ui://my-server/form": "src/ui/form.html",
            "ui://my-server/chart": "src/ui/chart.html",
        }
        html_path = html_files.get(uri_str)
        if html_path:
            html = Path(html_path).read_text(encoding="utf-8")
            return [create_ui_resource({
                "uri": uri_str,
                "content": {"type": "rawHtml", "htmlString": html},
                "encoding": "text",
            })]

    # Other resources (markdown guides, etc.)
    ...
```

### Resource Registration

```python
from mcp.types import Resource

# Add to your resource list
Resource(
    uri="ui://my-server/dashboard",
    name="Health Dashboard Widget",
    description="Interactive health dashboard with tabs and refresh",
    mimeType="text/html;profile=mcp-app",
)
```

---

## 13. Adding _meta.ui to Tool Definitions

```python
from mcp.types import Tool

Tool(
    name="my_interactive_tool",
    description="Does something with a rich widget UI",
    inputSchema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
        },
        "required": ["namespace"],
    },
    # This links the tool to its widget
    _meta={"ui": {"resourceUri": "ui://my-server/dashboard"}},
)
```

When the LLM calls this tool, the chat UI:
1. Shows the normal text/A2UI response
2. Also renders the widget HTML in a sandboxed iframe below
3. Passes the tool input and result to the widget

---

## 14. Complete Example — Episode Chart Widget

See `health-mcp/src/ui/episode_chart.html`:

- Uses Chart.js for interactive line charts
- Renders episode data with threshold + baseline overlay lines
- Shows episode metadata (start time, duration, peak, status)
- Receives data via `app.ontoolresult` and `app.oninput`
- Supports dark mode

---

## 15. Complete Example — Health Dashboard Widget

See `health-mcp/src/ui/health_dashboard.html`:

- Tabbed interface (Anomalies, Healthy, Correlations, Timeline)
- Data tables with status pills
- Summary badges (healthy/degraded/unhealthy counts)
- "Refresh" button that calls `wcnp_check_app_health` via `app.callServerTool()`
- Auto-strips `<a2ui>` tags from tool results
- Supports dark mode

---

## 16. A2UI vs MCP Apps — When to Use Which

| Use Case | A2UI v0.9 | MCP Apps |
|----------|-----------|---------|
| Status card with text | Use A2UI `Card` → `Text` | Overkill |
| Static data table | Use A2UI `Table` | Overkill |
| Tabbed content | Use A2UI `Tabs` | Use if tabs need to call tools |
| Form that submits data | Cannot submit — display only | Use MCP Apps form |
| Live-updating chart | Cannot update — static render | Use MCP Apps + Chart.js |
| Chart with zoom/pan | Data table fallback only | Use MCP Apps + Chart.js |
| Refresh button | Cannot call tools | Use MCP Apps `callServerTool` |
| Multi-step wizard | Cannot track state | Use MCP Apps with JS state |
| Grafana embed | A2UI `Button` with link | MCP Apps iframe |
| Icon + status indicator | Use A2UI `Icon` + `Text` | Overkill |

**Rule of thumb:**
- If it's **read-only** — use A2UI v0.9
- If it's **interactive** (forms, refresh, zoom, live data) — use MCP Apps
- Both can coexist in the same tool response
