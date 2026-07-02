---
name: deep-historical
description: >
  Extended historical analysis for chronic signals — queries 30-day trends
  to determine whether a degraded metric is a long-standing baseline or a
  slow-building regression. Use when health-triage identifies chronic
  resource signals and you need to confirm they are stable baselines.
metadata:
  adk_additional_tools:
    - wcnp_query_prometheus
    - wcnp_chart
    - render_chart
    - render_multi_chart
---

# Deep Historical Analysis

## When to Use This Skill

Activate this skill **after** health-triage when:
- A resource signal (CPU, memory) has `chronicity = "chronic"`
- You need to confirm whether the value is a **stable baseline** or a **slow regression**
- The user asks "has this always been like this?" or "when did this start?"

**Do NOT use this skill first** — always run health-triage first.

## Required Information

From the prior health-triage result, you need:
- **namespace** and **app** from the original query
- **The specific metric** that is chronic (e.g., `memory`, `cpu`)
- **cluster_id** from the health-triage result

## Workflow

### Step 1: Query 30-Day Trend

Use `wcnp_query_prometheus` to fetch a long-range time series:

```
wcnp_query_prometheus(
  cluster_id=<cluster_id>,
  query=<PromQL for the metric>,
  start_epoch=<now minus 30 days in epoch ms>,
  end_epoch=<now in epoch ms>,
  step="1h"
)
```

**Common PromQL queries:**

| Metric | PromQL |
|--------|--------|
| Memory utilization | `sum(container_memory_working_set_bytes{namespace="<ns>", container="<app>"}) / sum(kube_pod_container_resource_limits{namespace="<ns>", container="<app>", resource="memory"})` |
| CPU utilization | `sum(rate(container_cpu_usage_seconds_total{namespace="<ns>", container="<app>"}[5m])) / sum(kube_pod_container_resource_limits{namespace="<ns>", container="<app>", resource="cpu"})` |

### Step 2: Visualize the Trend

Generate a 30-day chart:

```
wcnp_chart(
  namespace=<namespace>,
  apps=[<app>],
  metrics=[<metric>],
  days=[0, 7, 14, 21, 28],
  title="30-Day <Metric> Trend"
)
```

### Step 3: Classify the Pattern

Examine the 30-day data and classify:

| Pattern | Meaning | Action |
|---------|---------|--------|
| **Flat line** at elevated level | Stable baseline — app always runs here | Adjust alert thresholds or accept |
| **Gradual upward slope** | Slow regression — capacity leak or growing load | Plan capacity increase or investigate leak |
| **Step change** on a specific date | Configuration or deployment changed the baseline | Correlate with deployment history |
| **Seasonal pattern** | Predictable business cycles (peak hours, weekends) | No action — expected behavior |

### Step 4: Report

Present findings as:

```
## Deep Historical Analysis: <metric>

**Pattern**: <flat / gradual increase / step change / seasonal>
**Duration**: <how long at current level>
**Assessment**: <stable baseline / slow regression / config change>
**Recommendation**: <accept / investigate / plan capacity>
```
