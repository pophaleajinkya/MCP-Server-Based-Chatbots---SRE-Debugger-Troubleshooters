# Metric Outlier Detection & Health Dashboard

How the agent detects anomalies, finds outlier clusters, and renders health
dashboards — using `namespace=item-assembler-async`, `app=iro-prod` as the
running example throughout.

---

## Three Use Cases

| User asks... | Tool called | What it does |
|---|---|---|
| "Show me the health dashboard for the last hour" | `wcnp_chart` | Single cluster: 5 aggregated metrics + historical anomaly per metric |
| "Which cluster has the highest latency?" / "Find the outlier cluster" | `wcnp_chart` | All clusters: one line per cluster + z-score outlier detection |
| "Is CPU / latency / memory anomalous?" | `wcnp_analyze` | Targeted health check with episode timing (existing behaviour) |

---

## Use Case 1 — `wcnp_chart`

### When it triggers

```
User: "Show the health dashboard for item-assembler-async in iro-prod for the last hour"
User: "Show all metrics for iro-prod / item-assembler-async"
User: "Give me a quick overview of item-assembler-async"
```

AGENT.md routing table:
```
"All metrics, one cluster" → wcnp_chart
```

### Step 1 — Cluster discovery

```
Agent needs a cluster_id before calling wcnp_chart.
It calls:

  wcnp_get_app_clusters(namespace="item-assembler-async", app="iro-prod")
  → ["uscentral-prod-az-036", "useast-prod-az-012"]

Agent picks one (or asks the user which cluster to inspect).
```

### Step 2 — 5 aggregated Prometheus range queries (parallel)

All queries run in parallel against one cluster's Prometheus. Every query is
**fully aggregated** — no `by (pod)` grouping — so each metric produces
**exactly one line** in the chart.

```
Cluster: uscentral-prod-az-036
Window:  last 1h  (start_epoch → end_epoch, step=5m)

CPU query:
  sum(rate(container_cpu_usage_seconds_total
    {namespace="item-assembler-async", container="iro-prod"}[5m]))
  → single time-series: total CPU rate across all pods

Memory query:
  sum(container_memory_working_set_bytes
    {namespace="item-assembler-async", container="iro-prod"})
  → single time-series: total working set bytes across all pods

Restarts query:
  sum(increase(kube_pod_container_status_restarts_total
    {namespace="item-assembler-async", container="iro-prod"}[5m]))
  → single time-series: total restart count across all pods

P95 Latency query (Istio Prometheus):
  histogram_quantile(0.95, sum(rate(
    envoy_cluster_upstream_rq_time_bucket
    {envoy_cluster_name=~"outbound.*iro-prod.*"}[5m]
  )) by (le))
  → single time-series: P95 outbound latency in milliseconds

Success Rate query (Istio Prometheus):
  sum(rate(envoy_cluster_upstream_rq_total
    {envoy_cluster_name=~"outbound.*iro-prod.*", response_code!~"5.."}[5m]))
  / sum(rate(envoy_cluster_upstream_rq_total
    {envoy_cluster_name=~"outbound.*iro-prod.*"}[5m]))
  → single time-series: ratio between 0 and 1
```

Result: **5 clean chart panels**, each with exactly 1 line and 13 data points
(1h ÷ 5m = 13 points).

### Step 3 — Historical anomaly detection (parallel, one per available metric)

After the range queries complete, a second parallel gather runs
`compare_to_same_time_multi_day()` for each metric that returned data.

This function:
1. Fetches the same metric as a **point query** at `analysis_end` (current value)
2. Fetches the same time window on **11 historical days** (1, 2, 3, 7, 8, 9, 13, 14, 17, 18, 19 days ago) — all in parallel
3. Computes **z-scores** across those 11 historical values to remove outlier days (past incidents, maintenance windows)
4. Computes a **clean baseline** = mean of the remaining days
5. Compares current vs clean baseline and flags an anomaly if deviation > threshold

```
Example for P95 Latency:

Historical day values (same 1h window, same time of day):
  day 1:  82ms   z=+0.12  ← kept
  day 2:  79ms   z=-0.21  ← kept
  day 3:  91ms   z=+0.97  ← kept
  day 7:  85ms   z=+0.38  ← kept
  day 8:  88ms   z=+0.63  ← kept
  day 9:  81ms   z=+0.03  ← kept
  day 13: 432ms  z=+3.82  ← EXCLUDED (past incident, z > 1.5)
  day 14: 78ms   z=-0.31  ← kept
  day 17: 80ms   z=-0.09  ← kept
  day 18: 84ms   z=+0.27  ← kept
  day 19: 83ms   z=+0.18  ← kept

Clean baseline = mean of kept days = 83ms
Current value  = 1240ms
Deviation      = +1394% → ANOMALY

anomaly_summary["latency"] = {
  "is_anomaly":        true,
  "current_value":     1240,
  "clean_baseline":    83,
  "deviation_percent": 1394.0,
  "anomaly_reason":    "Metric increased by 1394.0% vs 10-day clean baseline (1 outlier day excluded)",
  "days_used":         [1,2,3,7,8,9,14,17,18,19],
  "days_excluded":     [{"day": 13, "value": 432.0, "z_score": 3.82}]
}
```

Timeout: the entire anomaly gather is wrapped in `asyncio.wait_for(timeout=90)`.
If it times out, `anomaly_summary` is returned empty — charts still render.

### Step 4 — Tool response

```json
{
  "cluster_id": "uscentral-prod-az-036",
  "namespace":  "item-assembler-async",
  "app":        "iro-prod",
  "time_range_hours": 1,

  "multi_chart_data": {
    "title": "Health Dashboard — iro-prod (uscentral-prod-az-036)",
    "charts": [
      {"metric": "CPU Usage",    "y_label": "CPU rate",  "labels": ["00:26","00:31",...], "datasets": [{"label": "series", "data": [2.61, 2.58, ...]}]},
      {"metric": "Memory",       "y_label": "Bytes",     "labels": [...], "datasets": [{"label": "series", "data": [3.2e8, 3.2e8, ...]}]},
      {"metric": "Restarts",     "y_label": "count",     "labels": [...], "datasets": [{"label": "series", "data": [0, 0, ...]}]},
      {"metric": "P95 Latency",  "y_label": "ms",        "labels": [...], "datasets": [{"label": "series", "data": [1210, 1245, ...]}]},
      {"metric": "Success Rate", "y_label": "ratio",     "labels": [...], "datasets": [{"label": "series", "data": [0.94, 0.92, ...]}]}
    ]
  },

  "anomaly_summary": {
    "cpu":          {"is_anomaly": false, "deviation_percent": 4.2, ...},
    "memory":       {"is_anomaly": false, "deviation_percent": 1.1, ...},
    "restarts":     {"is_anomaly": false, ...},
    "latency":      {"is_anomaly": true,  "deviation_percent": 1394.0, "anomaly_reason": "...", "days_excluded": [{"day": 13, ...}]},
    "success_rate": {"is_anomaly": true,  "deviation_percent": -5.8,   "anomaly_reason": "..."}
  },

  "prometheus_links": {
    "cpu":          "https://prometheus.uscentral-prod-az-036.../graph?...",
    "latency":      "https://prometheus-istio.uscentral-prod-az-036.../graph?...",
    ...
  }
}
```

### Step 5 — UI renders `multi_chart_data` → 5-panel dashboard

The runner detects `multi_chart_data` in the tool response and emits a
`type:"graph"` SSE event. The UI renders `<MultiChartBlock>` — 5 panels in a
2-column grid, all sharing the same hover crosshair.

### Step 6 — Agent summarises anomaly_summary in text

```
"iro-prod on uscentral-prod-az-036 — last 1 hour:

  ⚠️  P95 Latency: 1,240ms (normal ~83ms, +1,394% above 10-day baseline)
      Note: day-13 excluded from baseline — past incident (432ms, z=3.82)
  ⚠️  Success Rate: 0.93 (dropped 5.8% below baseline)
  ✓   CPU, Memory, Restarts: all within normal range

[Health Dashboard chart — 5 panels]
[Open in Prometheus: Latency →]  [Open in Prometheus: Success Rate →]"
```

### Edge cases handled

| Situation | Behaviour |
|---|---|
| `hours <= 0` | Early error return: `"'hours' must be greater than 0"` |
| Istio endpoint missing | Latency + success rate charts skipped; infra charts still render |
| `compare_to_same_time_multi_day` returns `{"error": "No historical data"}` | Entry skipped — not added to `anomaly_summary` |
| `current_value` is `None` (no Prometheus data at `analysis_end`) | Entry skipped |
| >50% historical days returned 0 (app not deployed those days) | `baseline_warning` surfaced in `anomaly_summary[key]` so agent warns user |
| Anomaly gather exceeds 90s | `anomaly_summary` returned empty; charts still render |
| All pods scaled to zero → empty range query | Chart panel omitted from `multi_chart_data.charts` |

---

## Use Case 2 — `wcnp_chart`

### When it triggers

```
User: "Which cluster has the highest latency for iro-prod?"
User: "Compare CPU across all clusters for item-assembler-async"
User: "Show me how iro-prod performs across regions"
User: "Find the outlier cluster"
```

AGENT.md routing table:
```
"One metric, all clusters (comparison)" → wcnp_chart
```

### Step 1 — Cluster discovery

```
Agent calls:
  wcnp_get_app_clusters(namespace="item-assembler-async", app="iro-prod")
  → ["uscentral-prod-az-036", "useast-prod-az-012", "uswest-prod-az-088"]

Duplicates removed automatically (dict.fromkeys).
```

### Step 2 — One aggregated query per cluster (parallel)

The same fully-aggregated PromQL runs against each cluster's own Prometheus
endpoint in parallel. Example for `metric=p95_latency`:

```
Query (same for all clusters):
  histogram_quantile(0.95, sum(rate(
    envoy_cluster_upstream_rq_time_bucket
    {cluster_name=~"outbound.*{app}(|-primary|-canary).{namespace}.svc.cluster.local"}[5m]
  )) by (le)) * 1000

uscentral-prod-az-036  Prometheus: → [1210, 1245, 1198, ...]  ← one aggregated series
useast-prod-az-012     Prometheus: → [88, 91, 85, ...]
uswest-prod-az-088     Prometheus: → [93, 89, 94, ...]
```

Each cluster's result is reduced to **one dataset labelled by cluster_id**:

```python
# If query returns multiple rows (shouldn't for aggregated queries, but safe):
merged = sum of all rows → single float array per cluster
datasets = [
  {"label": "uscentral-prod-az-036", "data": [1210, 1245, ...]},
  {"label": "useast-prod-az-012",    "data": [88, 91, ...]},
  {"label": "uswest-prod-az-088",    "data": [93, 89, ...]},
]
```

### Step 3 — Z-score outlier detection across clusters

Requires ≥ 3 clusters with data. Computes each cluster's **mean** over the
entire time window, then z-scores those means against each other.

```
Cluster means (P95 Latency, last 1h):
  uscentral-prod-az-036:  mean = 1218ms
  useast-prod-az-012:     mean = 88ms
  uswest-prod-az-088:     mean = 92ms

Overall mean   = (1218 + 88 + 92) / 3 = 466ms
Std deviation  = 528ms

Z-scores:
  uscentral-prod-az-036:  z = (1218 - 466) / 528 = +1.42  ← below threshold
  useast-prod-az-012:     z = (88   - 466) / 528 = -0.72
  uswest-prod-az-088:     z = (92   - 466) / 528 = -0.71

Threshold = |z| ≥ 1.5 → in this example no cluster crosses the threshold.

With more extreme values (e.g. uscentral at 3400ms):
  mean = (3400 + 88 + 92) / 3 = 1193ms
  std  = 1905ms
  z(uscentral) = (3400 - 1193) / 1905 = +1.16  ← still below 1.5

  Note: with only 3 clusters z-score is less sensitive by design.
  With 5+ clusters a single bad cluster will show a clear z > 1.5.

outlier_clusters = [
  {
    "cluster_id":        "uscentral-prod-az-036",
    "z_score":           +1.42,
    "mean_value":        1218.0,
    "overall_mean":      466.0,
    "deviation_percent": +161.4
  }
]
```

### Step 4 — Tool response

```json
{
  "chart_data": {
    "chart_type": "line",
    "title":      "P95 Latency Comparison — iro-prod (Last 1h)",
    "x_label":    "Time",
    "y_label":    "Latency (ms)",
    "labels":     ["00:26", "00:31", "00:36", ...],
    "datasets": [
      {"label": "uscentral-prod-az-036", "data": [1210, 1245, 1198, ...]},
      {"label": "useast-prod-az-012",    "data": [88, 91, 85, ...]},
      {"label": "uswest-prod-az-088",    "data": [93, 89, 94, ...]}
    ]
  },
  "outlier_clusters": [
    {
      "cluster_id":        "uscentral-prod-az-036",
      "z_score":           1.42,
      "mean_value":        1218.0,
      "overall_mean":      466.0,
      "deviation_percent": 161.4
    }
  ],
  "prometheus_links": {
    "uscentral-prod-az-036": "https://prometheus-istio.uscentral.../graph?...",
    "useast-prod-az-012":    "https://prometheus-istio.useast.../graph?...",
    "uswest-prod-az-088":    "https://prometheus-istio.uswest.../graph?..."
  },
  "clusters_queried":   3,
  "clusters_with_data": 3
}
```

### Step 5 — UI renders `chart_data` → comparison line chart

Runner detects `chart_data` → emits `type:"graph"` SSE event → UI renders
`<ChartToolBlock>` with three lines (one per cluster) in the same panel.

### Step 6 — Agent surfaces `outlier_clusters` in text

```
"P95 Latency comparison for iro-prod across 3 clusters (last 1h):

  uscentral-prod-az-036:  avg 1,218ms  ← 161% above cluster mean (z=1.42)
  useast-prod-az-012:     avg 88ms     ✓ normal
  uswest-prod-az-088:     avg 92ms     ✓ normal

uscentral-prod-az-036 is the high-latency cluster.
Recommend: run wcnp_chart(cluster_id='uscentral-prod-az-036', ...) to
see whether CPU, memory, or restarts explain the elevated latency on that cluster.

[P95 Latency Comparison chart — 3 lines]
[Open in Prometheus: uscentral-prod-az-036 →]"
```

### Edge cases handled

| Situation | Behaviour |
|---|---|
| `hours <= 0` | Early error: `"'hours' must be greater than 0"` |
| Duplicate cluster IDs in input | Deduplicated via `dict.fromkeys` before queries run |
| < 3 clusters with data | `outlier_clusters = []` — z-score silently skipped (not meaningful) |
| Cluster with all-`None` data points | Excluded from `cluster_means` — not used in z-score |
| All cluster means identical (stddev=0) | `outlier_clusters = []` — division by zero avoided |
| Cluster query times out or errors | Returns `cid, [], ""` — excluded from datasets and z-score |
| Unknown `metric` value | `_build_query` returns `""` → no Prometheus call → cluster returns empty data |

---

## Use Case 3 — `wcnp_analyze` (existing, targeted)

### When it triggers

```
User: "Is latency high for iro-prod in item-assembler-async?"
User: "Show latency metrics for the last hour"
User: "Check CPU and Istio for iro-prod"
```

This is the existing health check path — no chart rendering, focused anomaly
detection with episode timing.

### What it runs

```
wcnp_analyze(
  namespace = "item-assembler-async",
  app       = "iro-prod",
  checks    = ["istio"],           ← agent picks from symptom
  baseline_hours = 1               ← user specified "last hour"
)
```

Internally:
1. Auto-discovers all clusters for `item-assembler-async / iro-prod`
2. Runs the selected checks in parallel across all clusters
3. Uses `compare_auto()` → picks strategy from `rules.yaml` (rolling, day_over_day, either, all)
4. Returns `episode_start`, `episode_end`, `peak_value`, `deviation_percent`, `prometheus_url` per anomalous check

### How it differs from Use Cases 1 & 2

| | `wcnp_chart` | `wcnp_chart` | `wcnp_analyze` |
|---|---|---|---|
| Clusters | 1 specified | All (passed in) | All (auto-discovered) |
| Output | 5-panel chart + anomaly summary | Comparison chart + outlier list | Structured anomaly data + prometheus URLs |
| Chart | Yes — `multi_chart_data` | Yes — `chart_data` | No chart — episode data only |
| Anomaly method | `compare_to_same_time_multi_day` (11-day z-score) | Cross-cluster z-score | `compare_auto` (strategy from rules.yaml) |
| Best for | "Show me what's happening right now" | "Which cluster is the problem?" | "Is this metric actually anomalous?" |

---

## Query Reference — `item-assembler-async` / `iro-prod`

All queries use `namespace="item-assembler-async"` and `container/app="iro-prod"`.

### Infra Prometheus

| Metric | PromQL |
|---|---|
| CPU total | `sum(rate(container_cpu_usage_seconds_total{namespace="item-assembler-async",container="iro-prod"}[5m]))` |
| Memory total | `sum(container_memory_working_set_bytes{namespace="item-assembler-async",container="iro-prod"})` |
| Restarts total | `sum(increase(kube_pod_container_status_restarts_total{namespace="item-assembler-async",container="iro-prod"}[5m]))` |

### Istio Prometheus

| Metric | PromQL |
|---|---|
| P95 Latency (dashboard) | `histogram_quantile(0.95, sum(rate(envoy_cluster_upstream_rq_time_bucket{envoy_cluster_name=~"outbound.*iro-prod.*"}[5m])) by (le))` |
| P95 Latency (compare) | `histogram_quantile(0.95, sum(rate(envoy_cluster_upstream_rq_time_bucket{cluster_name=~"outbound.*{app}(|-primary|-canary).{namespace}.svc.cluster.local"}[5m])) by (le)) * 1000` |
| Success Rate (dashboard) | `sum(rate(envoy_cluster_upstream_rq_total{envoy_cluster_name=~"outbound.*{app}.*",response_code!~"5.."}[5m])) / sum(rate(envoy_cluster_upstream_rq_total{envoy_cluster_name=~"outbound.*{app}.*"}[5m]))` |
| Success Rate (compare) | `sum(rate(envoy_cluster_upstream_rq_total{cluster_name=~"outbound.*{app}(|-primary|-canary).{namespace}.svc.cluster.local",response_code!~"5.."}[5m])) / sum(rate(envoy_cluster_upstream_rq_total{cluster_name=~"outbound.*{app}(|-primary|-canary).{namespace}.svc.cluster.local"}[5m]))` |

> **Note:** `wcnp_chart` uses `envoy_cluster_name` (Envoy internal label, no namespace).
> `wcnp_chart` uses `cluster_name` FQDN filter — same as health-check queries.
