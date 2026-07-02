---
name: error-cascade
description: >
  Bidirectional confidence-gated cascade for 4XX/5XX error investigation. Traces
  error spikes DOWNSTREAM (through dependencies) and UPSTREAM (through callers)
  using cheap Prometheus sweeps first, falling back to O2 log queries only when
  Prometheus cannot disambiguate which service is the culprit. Use when
  health-triage detects failure_attribution = "downstream_dependency",
  "shared_or_this_app", or "this_app" with a traffic spike. Handles both 4XX
  and 5XX error classes. Recurses to the root-cause node in either direction.
metadata:
  adk_additional_tools:
    - wcnp_check_app_health
    - wcnp_analyze
    - fetch_wcnp_downstream_dependencies
    - fetch_wcnp_upstream_dependencies
    - get_wcnp_dependency_graph
    - wcnp_get_o2_config
    - pingfed_token
    - execute_sql
    - search_around
    - get_stream_schema
    - validate_sql
    - wcnp_chart
    - wcnp_episode_chart
    - render_chart
---

# Error Cascade — Bidirectional Confidence-Gated Investigation

## When to Use This Skill

Activate this skill when health-triage Step 3 detects:
- `failure_attribution = "downstream_dependency"` → **DOWNSTREAM cascade**
- `failure_attribution = "shared_or_this_app"` → **BOTH directions**
- `failure_attribution = "this_app"` + traffic spike from callers → **UPSTREAM cascade**
- `non_2xx_analysis.4xx_spike = true` or `non_2xx_analysis.5xx_spike = true`

## Direction Decision

| Signal at Primary App | Direction | Reasoning |
|-----------------------|-----------|-----------|
| `failure_attribution = "downstream_dependency"` | **DOWNSTREAM** | Our outbound calls fail → a dep is broken |
| `failure_attribution = "this_app"` + traffic anomaly | **UPSTREAM** | Our errors correlate with traffic increase → who's flooding us? |
| `failure_attribution = "shared_or_this_app"` | **BOTH** | Both sides bad → downstream for 5XX, upstream for traffic |
| 4XX spike only (server healthy) | **UPSTREAM** | Clients sending bad requests → who changed their contract? |
| 5XX spike only | **DOWNSTREAM** | Server errors → something we depend on is broken |
| Both 4XX + 5XX spikes | **BOTH** | Downstream for 5XX, upstream for 4XX source |

## Critical Rule: Cost Pyramid

```
         ┌──────────────────┐
         │  O2 DEEP Logs    │  ← LAST: stack traces at root-cause node only
         │  (most expensive) │
         ├──────────────────┤
         │  O2 LIGHT Logs   │  ← FALLBACK: only when Prometheus is ambiguous
         │  (expensive)      │
         ├──────────────────┤
         │  Prometheus       │  ← ALWAYS: parallel health sweep of all deps
         │  (cheap)          │
         ├──────────────────┤
         │  Topology         │  ← ALWAYS: get dependency list
         │  (cheapest)       │
         ├──────────────────┤
         │  Already Done     │  ← FREE: health-triage already computed this
         └──────────────────┘
```

> **O2 is NOT just for the final root-cause node.** It is a confidence fallback
> at ANY layer when Prometheus alone cannot disambiguate which service is the
> culprit. But ALWAYS try Prometheus first — O2 is the fallback, not the default.

## Required Information

From the prior health-triage result, you need:
- **namespace** and **app** — the originating application
- **failure_attribution** — from health-triage Step 2
- **error_classes** *(optional)* — list of elevated error types (`["4xx"]`, `["5xx"]`, or `["4xx", "5xx"]`). **Only present when a 4XX/5XX spike exists.** If absent, the failure is detected by success-rate degradation without a specific spike — still cascade.
- **error_class_detail** *(optional)* — per-class current/baseline/deviation percentages. Present only when `error_classes` is present.
- **non_2xx_analysis** — from `istio_traffic_spike` check

### Determine Error Class

| Field | Meaning |
|-------|---------|
| `4xx_spike = true` | 4XX errors increased vs baseline |
| `5xx_spike = true` | 5XX errors increased vs baseline |
| `4xx_current_percent` | Current 4XX rate as % of total traffic |
| `5xx_current_percent` | Current 5XX rate as % of total traffic |
| `4xx_deviation_percent` | % deviation from 4XX baseline |
| `5xx_deviation_percent` | % deviation from 5XX baseline |

**Always state which error classes are elevated before proceeding.**

---

## THE CORE LOOP — Repeats at Every Layer

The cascade is a **loop**, not a linear sequence. It repeats at each layer
(depth 0 = primary app, depth 1 = first-hop dep, depth 2 = second-hop, etc.)
in EITHER direction (downstream or upstream). Maximum depth: **3 levels**.

```
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER N  (start N=0 with primary app)                               │
│                                                                      │
│  Step 1: CLASSIFY — error signal already known from prior layer      │
│                                                                      │
│  Step 2: ENUMERATE — fetch deps (downstream or upstream)             │
│                                                                      │
│  Step 3: PROMETHEUS SWEEP — parallel health check ALL k8app deps     │
│                                                                      │
│  Step 4: CONFIDENCE GATE ──────────────────────────────┐             │
│     │                                                  │             │
│     ├── CONFIDENT (one dep clearly dominates)          │             │
│     │   → Pick winner → go to LAYER N+1                │             │
│     │                                                  │             │
│     └── NOT CONFIDENT (evenly distributed / ambiguous) │             │
│         → O2 LIGHT on THIS layer's app                 │             │
│         → Logs reveal which dep is the culprit         │             │
│         → Pick winner → go to LAYER N+1                │             │
│                                                                      │
│  Step 5: ROOT-CAUSE CHECK                                            │
│     └── If winner has no further blame (this_app / healthy deps):    │
│         → O2 DEEP on winner (stack traces, exception details)        │
│         → Report root cause and STOP                                 │
│     └── If winner blames further:                                    │
│         → LAYER N+1 (recurse)                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## DOWNSTREAM CASCADE (5XX / dependency failures)

### Phase D1: Classify Error Signal (ALREADY DONE — zero cost)

This data comes from health-triage. You MUST state:

```
## Error Signal Classification

| Signal | Value |
|--------|-------|
| failure_attribution | downstream_dependency / shared_or_this_app |
| 4XX spike | yes/no (current: X%, baseline: Y%, deviation: Z%) |
| 5XX spike | yes/no (current: X%, baseline: Y%, deviation: Z%) |
| Error class | 4XX / 5XX / both |
| Chronicity | acute / chronic |
| Cascade direction | DOWNSTREAM |
```

### Phase D2: Enumerate Downstream Dependencies (MANDATORY — cheap)

```
fetch_wcnp_downstream_dependencies(app_name=<app>, namespace=<namespace>)
```

Filter the results:
- **k8app** dependencies → health-checkable via Prometheus (Phase D3)
- **meghacache / cosmos / kafka / sqlserver** → note as infra deps for later

**MANDATORY**: Present the dependency list:

```
## Downstream Dependencies (N total)

| Dependency | Namespace | Type | Investigate? |
|------------|-----------|------|-------------|
| payment-svc | payments | k8app | ✅ Phase D3 |
| inventory-api | inv | k8app | ✅ Phase D3 |
| meghacache | — | meghacache | ⏳ If D3 inconclusive |
```

### Phase D3: Prometheus Health Sweep (MANDATORY — parallel)

For **each** k8app dependency, run **in parallel**:

```
wcnp_check_app_health(namespace=<dep_ns>, app=<dep_app>)
```

**CRITICAL**: Run ALL dependency health checks in a single parallel batch.
Do NOT run them sequentially.

From each result, extract:
1. `overall_status` — healthy / degraded / unhealthy
2. `golden_signal_status` — golden signals affected?
3. `failure_attribution` — does this dep blame ITS downstream? (cascade continues)
4. `anomaly_detected` — new anomaly or chronic?
5. `non_2xx_analysis` — its own 4XX/5XX spikes?
6. `error_classes` / `error_class_detail` — which error types elevated?

**MANDATORY**: Rank and present results using the script:
```
run_skill_script(skill_name="error-cascade",
                 script_path="scripts/rank_dependency_health.py",
                 args={"dependency_results": <map of dep_name → health_result>,
                       "primary_app_error_deviation": <deviation% from phase D1>})
```

### Phase D4: Confidence Gate (CRITICAL DECISION POINT)

After the Prometheus sweep, apply the **confidence test**:

#### Confidence Rule

Run the ranking script — it computes a `confidence` verdict automatically:

**CONFIDENT** = exactly ONE dependency satisfies ALL of:
1. Category is `confirmed_bad` or `suspicious`
2. Its error deviation is **≥ 3× the second-worst** dependency's deviation
3. It is NOT `chronic`

**NOT CONFIDENT** = any of:
- Multiple deps have similar error deviations (no clear winner)
- Error distribution is spread evenly (e.g., B=10%, C=20%, D=1%, E=10%)
- No deps show correlated degradation but primary app has errors

#### If CONFIDENT → Go to Phase D5

The ranking script names the winner. Proceed directly to the next layer.

#### If NOT CONFIDENT → O2 Disambiguation on THIS Layer's App

When Prometheus cannot tell you which downstream is causing errors, query O2
on the **current layer's app** (NOT the deps) to find out which downstream
service is generating the errors:

**Step 4a**: Resolve O2 config for the current app
```
wcnp_get_o2_config(namespace=<this_app_ns>, app=<this_app>)
```

**Step 4b**: Get auth token
```
pingfed_token(cluster_lb=<cluster_lb from 4a>)
```

**Step 4c**: Get stream schema (first time only)
```
get_stream_schema(endpoint=<endpoint>, stream=<stream>,
                  bearer_token=<token>, organization=<org>)
```

**Step 4d**: Query error distribution by path — this reveals which downstream
service is responsible because `http_path` typically contains the downstream route:

**For 5XX errors:**
```sql
SELECT http_path, response_code,
       count(_timestamp) as error_count
FROM "<stream>"
WHERE <default_filter>
  AND CAST(response_code AS INT) >= 500
GROUP BY http_path, response_code
ORDER BY error_count DESC
LIMIT 20
```

**For 4XX errors:**
```sql
SELECT http_path, response_code,
       count(_timestamp) as error_count
FROM "<stream>"
WHERE <default_filter>
  AND CAST(response_code AS INT) >= 400
  AND CAST(response_code AS INT) < 500
GROUP BY http_path, response_code
ORDER BY error_count DESC
LIMIT 20
```

**Step 4e**: Match the top `http_path` values against the dependency list from
Phase D2. The path with the highest error count points to the culprit dependency.

**MANDATORY**: Present the O2 disambiguation result:
```
## O2 Disambiguation — <this_app>

| http_path | response_code | error_count | Likely Dependency |
|-----------|---------------|-------------|-------------------|
| /api/checkout/pay | 503 | 450 | payment-svc |
| /api/cart/items | 429 | 30 | inventory-api |

**Verdict**: payment-svc is the dominant error source (93% of errors).
```

### Phase D5: Recurse or Root-Cause

After identifying the culprit dependency (from D4):

**If the culprit has `failure_attribution = "downstream_dependency"`**:
→ The error originates further down. **Repeat from Phase D2** for this dependency.
→ Increment depth counter. Stop at depth 3.

**If the culprit has `failure_attribution = "this_app"` or no further downstream blame**:
→ This is the **root-cause node**. Proceed to **O2 DEEP analysis**:

#### O2 DEEP — Root-Cause Node Only

**Step 5a**: Resolve O2 config
```
wcnp_get_o2_config(namespace=<root_ns>, app=<root_app>)
```

**Step 5b**: Get auth token (or reuse if same cluster)
```
pingfed_token(cluster_lb=<cluster_lb>)
```

**Step 5c**: Error distribution
```sql
SELECT http_path, response_code, log,
       count(_timestamp) as error_count
FROM "<stream>"
WHERE <default_filter>
  AND CAST(response_code AS INT) >= 500
GROUP BY http_path, response_code, log
ORDER BY error_count DESC
LIMIT 20
```

**Step 5d**: Exception stack traces (for 5XX)
```sql
SELECT _timestamp, log, kubernetes_pod_name
FROM "<stream>"
WHERE <default_filter>
  AND (str_match(log, 'Exception') OR str_match(log, 'Error')
       OR str_match(log, 'Traceback') OR str_match(log, 'panic'))
ORDER BY _timestamp DESC
LIMIT 10
```

**Step 5e**: For specific timestamp context, use `search_around` on the most
interesting log entry from Step 5d to get surrounding log lines.

---

## UPSTREAM CASCADE (traffic spikes / 4XX from callers)

Use when `failure_attribution = "this_app"` with a traffic anomaly, or
`failure_attribution = "shared_or_this_app"` to find WHO is sending the traffic.

### Phase U1: Classify Traffic Signal (ALREADY DONE — zero cost)

```
## Traffic Signal Classification

| Signal | Value |
|--------|-------|
| failure_attribution | this_app / shared_or_this_app |
| Traffic anomaly | yes (current: X rps, baseline: Y rps, deviation: Z%) |
| 4XX spike | yes/no |
| Cascade direction | UPSTREAM |
```

### Phase U2: Enumerate Upstream Dependencies (MANDATORY — cheap)

```
fetch_wcnp_upstream_dependencies(app_name=<app>, namespace=<namespace>)
```

This returns all services that **call INTO** this app (callers / consumers).

**MANDATORY**: Present the caller list:
```
## Upstream Callers (N total)

| Caller | Namespace | Type | Investigate? |
|--------|-----------|------|-------------|
| checkout-bff | storefront | k8app | ✅ Phase U3 |
| batch-job | cron | k8app | ✅ Phase U3 |
```

### Phase U3: Prometheus Health Sweep of Callers (MANDATORY — parallel)

For **each** k8app caller, run **in parallel**:

```
wcnp_check_app_health(namespace=<caller_ns>, app=<caller_app>)
```

Look for:
1. **Traffic anomaly** — is this caller sending more traffic than baseline?
2. `anomaly_detected` — new spike?
3. `failure_attribution` — does this caller also have upstream blame?

### Phase U4: Confidence Gate for Upstream

Same confidence logic as downstream:

**CONFIDENT** = one caller clearly dominates the traffic increase (≥ 3× next).
→ Go to that caller, repeat from Phase U2.

**NOT CONFIDENT** = traffic increase is spread across callers.
→ O2 on the **current app** to see which API paths have increased traffic:

```sql
SELECT http_path, count(_timestamp) as request_count
FROM "<stream>"
WHERE <default_filter>
GROUP BY http_path
ORDER BY request_count DESC
LIMIT 20
```

Match the busiest paths against the upstream caller list to identify the source.

### Phase U5: Root Node

When you reach a caller that has NO upstream attribution (nobody is blaming
their upstream — this is where the traffic originates):

→ **O2 DEEP** on this root caller to understand WHY it's generating extra traffic:

```sql
SELECT http_path, response_code,
       count(_timestamp) as request_count
FROM "<stream>"
WHERE <default_filter>
GROUP BY http_path, response_code
ORDER BY request_count DESC
LIMIT 20
```

Look for: new batch jobs, retry storms, new feature rollouts, config changes.

---

## BOTH DIRECTIONS (shared_or_this_app / 4XX + 5XX)

When BOTH directions are needed:

1. Run **DOWNSTREAM cascade** first (for 5XX / dependency failures)
2. Then run **UPSTREAM cascade** (for traffic / 4XX sources)
3. Correlate findings: often the upstream traffic increase CAUSES the downstream failures

Present combined findings in the final report.

---

## Confidence Scoring — Detailed Rules

The `rank_dependency_health.py` script computes confidence automatically.
Here is the logic for transparency:

### Error Deviation Comparison

After the Prometheus sweep, each dep has an error deviation (from `non_2xx_analysis`).
Rank them by deviation:

| Scenario | Example Deviations | Confident? | Reason |
|----------|-------------------|------------|--------|
| **One dominates** | D=80%, B=2%, C=1%, E=0% | ✅ YES | D is 40× next |
| **One clearly worst** | D=45%, B=10%, C=5%, E=3% | ✅ YES | D is 4.5× next (≥ 3×) |
| **Evenly spread** | B=10%, C=20%, D=1%, E=10% | ❌ NO | C=20%, B=10% — only 2× |
| **Multiple similar** | B=35%, C=30%, D=2% | ❌ NO | B/C within 1.2× |
| **None stand out** | B=2%, C=1%, D=0%, E=1% | ❌ NO | All low, no clear signal |
| **All zero** | B=0%, C=0%, D=0% | ❌ NO | No Prometheus signal at all |

### Fallback Cascade

```
Can Prometheus identify the culprit?
│
├── YES (confident) → pick winner → next layer
│
└── NO (ambiguous) → O2 LIGHT on current app
    │
    ├── O2 identifies culprit → pick winner → next layer
    │
    └── O2 also ambiguous → report findings, recommend manual investigation
```

---

## 4XX vs 5XX Investigation Differences

| Aspect | 4XX Investigation | 5XX Investigation |
|--------|-------------------|-------------------|
| **Direction** | Often UPSTREAM (who changed their call?) | Often DOWNSTREAM (which dep is broken?) |
| **Likely cause** | Auth issues, contract change, missing resource | Server crash, dependency failure, timeout |
| **Log query focus** | `http_path` + `response_code` breakdown | Exception / stack trace search |
| **Common patterns** | Token expiry, API schema mismatch, 404 | OOM, timeout, connection refused |
| **Cascade behavior** | Often stops at first hop | Often cascades through multiple levels |

### 4XX-Specific Patterns

1. **401/403 spike** → Auth token expiry, certificate rotation, IAM policy change
2. **404 spike** → Deployment removed an endpoint, routing change
3. **429 spike** → Rate limiting activated (check `istio_rate_limiting`)
4. **400 spike** → API contract change, request schema mismatch

### 5XX-Specific Patterns

1. **502/503 spike** → Downstream dependency unreachable, pod not ready
2. **500 spike** → Application exception, null pointer, unhandled error
3. **504 spike** → Timeout — downstream dependency slow (correlate with latency)

---

## Presentation

### Final Report Format

```
## Error Cascade Investigation

### Error Signal
- **Error class**: 4XX / 5XX / both
- **Originating app**: <namespace>/<app>
- **failure_attribution**: <attribution>
- **Cascade direction**: downstream / upstream / both

### Cascade Chain
<namespace>/<app>  (Layer 0 — primary app)
  └── <dep_ns>/<dep_app>  (Layer 1 — <confident/O2-disambiguated>)
      └── <dep2_ns>/<dep2_app>  (Layer 2 — root cause)

### Per-Layer Findings

#### Layer 0: <app> (primary)
- Prometheus: 5XX at X%, 4XX at Y%
- Confidence: <confident/not confident>
- O2 disambiguation: <if used, show top paths>

#### Layer 1: <dep_app>
- Prometheus: 5XX at X%, failure_attribution = downstream_dependency
- Confidence: <confident/not confident>

#### Layer 2: <dep2_app> — ROOT CAUSE
- Prometheus: 5XX at X%, failure_attribution = this_app
- O2 DEEP: <top error / stack trace summary>

### Root Cause
- **Failing service**: <dep_ns>/<dep_app>
- **Error type**: <4XX / 5XX / both>
- **Log evidence**: <top error from O2 DEEP>
- **Cascade depth**: <1 / 2 / 3>

### Recommended Actions
1. <specific action based on findings>
2. <specific action based on findings>
```

---

## O2 Cost Budget

| Query Type | When Used | Cost |
|------------|-----------|------|
| O2 LIGHT (disambiguation) | Only when Prometheus ambiguous at a layer | 1 query per layer |
| O2 DEEP (root cause) | Always at the final root-cause node | 2-3 queries |
| O2 UPSTREAM (traffic paths) | At upstream root node | 1-2 queries |

**Best case** (Prometheus confident at every layer): **2-3 O2 calls** (deep only at leaf)
**Worst case** (ambiguous at every layer, 3 deep): **~9 O2 calls** (3 light + 3 deep)
**Typical case**: **~4-5 O2 calls** (1 light disambiguation + 2-3 deep at root)

---

## Important Rules

- **ALWAYS try Prometheus FIRST at every layer** — O2 is the fallback
- **Run Prometheus health checks in PARALLEL** — never sequentially
- **O2 disambiguation queries go on the CURRENT layer's app** — not on the deps
- **O2 DEEP queries go on the ROOT-CAUSE node only** — stack traces at the leaf
- **Confidence threshold: 3×** — winner must have ≥ 3× the error deviation of the next dep
- **Max recursion: 3 levels** in either direction — stop and report if deeper
- **Always state the cascade direction** (downstream / upstream / both) at the start
- **Always show the full cascade chain** with per-layer findings
- **For BOTH directions**: run downstream first, then upstream, then correlate
