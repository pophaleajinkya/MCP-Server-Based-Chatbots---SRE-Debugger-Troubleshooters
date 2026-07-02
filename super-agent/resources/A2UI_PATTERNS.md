# A2UI v0.9 — Structured UI Patterns

When your response contains structured data (tables, status summaries, metric
trends, URL links), embed it as A2UI v0.9 JSON inside `<a2ui>...</a2ui>` tags.
Plain text narrative goes outside the tags as normal markdown.

**When to use A2UI:**
- Multi-cluster comparisons → Tabs per cluster + Tables
- Issue / check lists → Table
- Metric trends over time → Chart (line)
- Side-by-side comparisons → Chart (bar)
- Distribution data → Chart (pie)
- Status overview → Card with Icon + Text
- Prometheus / Grafana links → Buttons in a Row
- Mixed data → combine patterns in one Column

**When NOT to use:** simple Q&A, short text answers, single sentences.

---

## Format Rules (v0.9 — strict)

Every A2UI block = exactly **two messages**:
1. `createSurface` — `{"version":"v0.9","createSurface":{"surfaceId":"<id>","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}}`
2. `updateComponents` — all components listed flat (not nested inside each other)

| Field | Who uses it | Rule |
|---|---|---|
| `id` | every component | Unique short string: `col-1`, `tbl-issues`, `btn-prom`, `tabs-clusters` |
| `component` | every component | Exact type string (see list below) |
| `children` | Column, Row, Tabs | Array of child IDs |
| `child` | Card, Button | **Single** child ID (not an array) |
| `tabItems` | Tabs | `[{"title":"cluster-name","child":"col-id"},...]` |
| `variant` | Text | `h1` `h2` `h3` `h4` `h5` `body` `caption` |
| `name` | Icon | `check` `warning` `error` `info` |
| `action` | Button | `{"event":{"name":"open_url","data":{"url":"https://..."}}}` |
| `chartType` | Chart | `line` `bar` `pie` |
| `xAxis.labels` | Chart (line/bar) | Array of label strings |
| `series` | Chart (line/bar) | `[{"label":"Name","data":[1.0,2.3,...]}]` |
| `series[].data` | Chart (pie) | `[{"name":"Label","value":42}]` |
| `columns` | Table | `["Col A","Col B",...]` |
| `rows` | Table | `[["val1","val2"],...]` — all strings |

**Common mistakes:**
- Card `child` = one ID, not array
- Button `child` = Text component ID (not a label string directly on Button)
- All component IDs must be unique within a surface
- `children` holds ID strings, not inline component objects

---

## Pattern 1 — Multi-Cluster Issue Tabs + Prometheus/Grafana Links

Use for health check results across multiple clusters.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s1","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s1","components":[
    {"id":"root","component":"Column","children":["tabs","div1","btn-row"]},
    {"id":"tabs","component":"Tabs","tabItems":[
      {"title":"eus2-prod-a54","child":"col-eus2"},
      {"title":"scus-prod-a78","child":"col-scus"}
    ]},
    {"id":"col-eus2","component":"Column","children":["tbl-eus2"]},
    {"id":"tbl-eus2","component":"Table",
     "columns":["Issue","Current","Threshold","Status"],
     "rows":[["memory","86.7%","80%","degraded"],["node_cpu","72%","70%","degraded"]]},
    {"id":"col-scus","component":"Column","children":["tbl-scus"]},
    {"id":"tbl-scus","component":"Table",
     "columns":["Issue","Current","Threshold","Status"],
     "rows":[["memory","86.8%","80%","degraded"]]},
    {"id":"div1","component":"Divider"},
    {"id":"lbl-q1","component":"Text","text":"Prometheus — Traffic","variant":"body"},
    {"id":"btn-q1","component":"Button","child":"lbl-q1","variant":"secondary",
     "action":{"event":{"name":"open_url","data":{"url":"https://prometheus.cluster.example/graph?q=..."}}}},
    {"id":"lbl-g1","component":"Text","text":"Grafana Dashboard","variant":"body"},
    {"id":"btn-g1","component":"Button","child":"lbl-g1","variant":"secondary",
     "action":{"event":{"name":"open_url","data":{"url":"https://grafana.cluster.example/d/abc123"}}}},
    {"id":"btn-row","component":"Row","children":["btn-q1","btn-g1"],"justify":"start"}
  ]}}
]</a2ui>
```

---

## Pattern 2 — Status Card (healthy / degraded / unhealthy)

Use for status summaries and health banners.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s2","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s2","components":[
    {"id":"card","component":"Card","child":"card-col"},
    {"id":"card-col","component":"Column","children":["title","status-row","detail"]},
    {"id":"title","component":"Text","text":"signal-api — intl-sre","variant":"h3"},
    {"id":"status-row","component":"Row","children":["icon","status-text"],"align":"center"},
    {"id":"icon","component":"Icon","name":"warning"},
    {"id":"status-text","component":"Text","text":"DEGRADED","variant":"h4"},
    {"id":"detail","component":"Text","text":"Root cause: memory p90 at 86.7% (threshold 80%)","variant":"body"}
  ]}}
]</a2ui>
```

Icon names: `check` (healthy) · `warning` (degraded) · `error` (unhealthy) · `info` (informational)

---

## Pattern 3 — Line Chart (time-series trend)

Use for memory, CPU, latency, request rate trends over time.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s3","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s3","components":[
    {"id":"col","component":"Column","children":["chart"]},
    {"id":"chart","component":"Chart","chartType":"line",
     "title":"Memory p90 — last 2h",
     "xAxis":{"labels":["14:00","14:30","15:00","15:30"]},
     "series":[
       {"label":"app %","data":[82.1,83.4,85.0,86.7]},
       {"label":"threshold","data":[80.0,80.0,80.0,80.0]}
     ]}
  ]}}
]</a2ui>
```

---

## Pattern 4 — Bar Chart (cluster or period comparison)

Use for side-by-side comparisons: cluster latency, multi-day baseline.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s4","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s4","components":[
    {"id":"col","component":"Column","children":["chart"]},
    {"id":"chart","component":"Chart","chartType":"bar",
     "title":"P95 Latency by Cluster (ms)",
     "xAxis":{"labels":["eus2-prod-a54","scus-prod-a78","uscentral-prod"]},
     "series":[
       {"label":"current","data":[210,302,195]},
       {"label":"baseline","data":[195,200,190]}
     ]}
  ]}}
]</a2ui>
```

---

## Pattern 5 — Flat Table (single cluster or simple list)

Use when there is only one cluster or for any simple tabular data.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s5","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s5","components":[
    {"id":"col","component":"Column","children":["tbl"]},
    {"id":"tbl","component":"Table",
     "columns":["App","Namespace","Status","Replicas"],
     "rows":[
       ["signal-api","intl-sre","healthy","21/21"],
       ["item-engine","item-assembler","degraded","18/21"]
     ]}
  ]}}
]</a2ui>
```

---

## Pattern 6 — Links Only (Prometheus / Grafana buttons)

Use when you only need clickable query links, no tables or charts.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s6","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s6","components":[
    {"id":"root","component":"Column","children":["lbl-section","btn-row"]},
    {"id":"lbl-section","component":"Text","text":"Prometheus Queries","variant":"h4"},
    {"id":"lbl1","component":"Text","text":"Traffic Rate","variant":"body"},
    {"id":"btn1","component":"Button","child":"lbl1","variant":"secondary",
     "action":{"event":{"name":"open_url","data":{"url":"https://prom-istio.cluster.example/graph?q=..."}}}},
    {"id":"lbl2","component":"Text","text":"5xx Error Rate","variant":"body"},
    {"id":"btn2","component":"Button","child":"lbl2","variant":"secondary",
     "action":{"event":{"name":"open_url","data":{"url":"https://prom-istio.cluster.example/graph?q=..."}}}},
    {"id":"btn-row","component":"Row","children":["btn1","btn2"],"justify":"start"}
  ]}}
]</a2ui>
```

---

## Pattern 7 — Full Report (card + tabs + chart + links)

Combine patterns for complete health reports.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"s7","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"s7","components":[
    {"id":"root","component":"Column","children":["card","tabs","div1","btn-row"]},
    {"id":"card","component":"Card","child":"card-inner"},
    {"id":"card-inner","component":"Column","children":["card-title","card-row"]},
    {"id":"card-title","component":"Text","text":"pno-api-prod — mx-pno-async","variant":"h3"},
    {"id":"card-row","component":"Row","children":["card-icon","card-status"],"align":"center"},
    {"id":"card-icon","component":"Icon","name":"error"},
    {"id":"card-status","component":"Text","text":"UNHEALTHY","variant":"h4"},
    {"id":"tabs","component":"Tabs","tabItems":[
      {"title":"eus2-prod-a54","child":"col-eus2"},
      {"title":"scus-prod-a78","child":"col-scus"}
    ]},
    {"id":"col-eus2","component":"Column","children":["tbl-eus2","chart-eus2"]},
    {"id":"tbl-eus2","component":"Table",
     "columns":["Issue","Current","Baseline","Deviation"],
     "rows":[["client_latency_p95","301ms","220ms","+37%"]]},
    {"id":"chart-eus2","component":"Chart","chartType":"line",
     "title":"Client P95 Latency","xAxis":{"labels":["14:00","14:30","15:00","15:30"]},
     "series":[{"label":"p95 ms","data":[220,235,270,301]},{"label":"baseline","data":[220,220,220,220]}]},
    {"id":"col-scus","component":"Column","children":["tbl-scus"]},
    {"id":"tbl-scus","component":"Table",
     "columns":["Issue","Current","Status"],
     "rows":[["memory","86.8%","degraded"]]},
    {"id":"div1","component":"Divider"},
    {"id":"lbl-prom","component":"Text","text":"Prometheus — Latency","variant":"body"},
    {"id":"btn-prom","component":"Button","child":"lbl-prom","variant":"secondary",
     "action":{"event":{"name":"open_url","data":{"url":"https://prom-istio.example.com/graph?q=..."}}}},
    {"id":"btn-row","component":"Row","children":["btn-prom"],"justify":"start"}
  ]}}
]</a2ui>
```

---

---

Do NOT duplicate inside A2UI content already shown in your markdown narrative.

---

## Pattern 8 — Multi-metric Chart Dashboard (wcnp_chart results)

Use after `wcnp_chart` returns `chart_panels`. Generate one `Chart` per panel — copy `xAxis.labels` and `series` directly from the tool output.

```
<a2ui>[
  {"version":"v0.9","createSurface":{"surfaceId":"charts","catalogId":"https://a2ui.org/specification/v0_9/basic_catalog.json"}},
  {"version":"v0.9","updateComponents":{"surfaceId":"charts","components":[
    {"id":"root","component":"Column","children":["dash-title","chart-latency","div1","chart-memory","div2","chart-cpu"]},
    {"id":"dash-title","component":"Text","text":"unifiedpromise-prod-tg2 — unified-promise-discovery","variant":"h3"},
    {"id":"div1","component":"Divider"},
    {"id":"chart-latency","component":"Chart","chartType":"line",
     "title":"P95 Client Latency (ms)",
     "xAxis":{"labels":["00:00","00:05","00:10","00:15","00:20"]},
     "series":[
       {"label":"eus2-prod-a54 · now",    "data":[194,198,201,197,199]},
       {"label":"eus2-prod-a54 · 5d ago", "data":[210,215,208,212,211]},
       {"label":"scus-prod-a78 · now",    "data":[196,202,199,204,200]}
     ]},
    {"id":"div2","component":"Divider"},
    {"id":"chart-memory","component":"Chart","chartType":"line",
     "title":"Memory (bytes)",
     "xAxis":{"labels":["00:00","00:05","00:10","00:15","00:20"]},
     "series":[
       {"label":"eus2-prod-a54 · now",    "data":[8.6e8,8.7e8,8.8e8,8.9e8,9.0e8]},
       {"label":"scus-prod-a78 · now",    "data":[8.1e8,8.2e8,8.4e8,8.5e8,8.7e8]}
     ]},
    {"id":"chart-cpu","component":"Chart","chartType":"line",
     "title":"CPU Usage (cores)",
     "xAxis":{"labels":["00:00","00:05","00:10","00:15","00:20"]},
     "series":[
       {"label":"eus2-prod-a54 · now", "data":[38,40,41,39,42]},
       {"label":"scus-prod-a78 · now", "data":[35,37,36,38,40]}
     ]}
  ]}}
]</a2ui>
```

**Rules:**
- One `Chart` per metric (one `chart_panel`) — never one chart per day
- Multiple days = multiple `series` entries on the same chart
- `surfaceId` must be unique per response (e.g. `"charts"`, `"trend-latency"`)
- Omit charts where `series` is empty — tell the user no data was found
