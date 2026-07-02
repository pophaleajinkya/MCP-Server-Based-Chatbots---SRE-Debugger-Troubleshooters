---
name: health-triage
description: >
  Full WCNP application health triage — runs 21 health checks across CPU, memory,
  restarts, Istio mesh, pods, secrets, and configuration. Use when the user asks
  "is app healthy?", "what's wrong with <app>?", "check health", "latency spike",
  "5XX spike", or any general health question about a WCNP Kubernetes application.
metadata:
  aliases:
    - wcnp-triage
    - kubernetes-triage
    - k8s-triage
  adk_additional_tools:
    - wcnp_check_app_health
    - wcnp_analyze
    - wcnp_check_namespace_health
    - wcnp_get_app_clusters
    - wcnp_list_deployments
    - wcnp_query_prometheus
    - wcnp_chart
    - wcnp_episode_chart
    - wcnp_get_prometheus_endpoints
    - wcnp_check_url_health
    - wcnp_check_grafana_url_health
    - wcnp_get_o2_config
    - render_chart
    - render_multi_chart
---

# WCNP Health Triage

## When to Use This Skill

Activate this skill when the user asks about:
- Application health ("is cart-service healthy?")
- Specific symptoms (CPU, memory, latency, 5XX, restarts)
- Namespace-wide health checks
- Health comparisons across clusters
- Anomaly investigation after a health check

## Required Information

Always ensure you have:
- **namespace** — the Kubernetes namespace (e.g., `store-app`)
- **app** — the application/deployment name (e.g., `cart-service`)

If the user doesn't provide these, ask for them before proceeding.

## MANDATORY Step-by-Step Triage Workflow

> **ENFORCEMENT RULE**: You MUST execute ALL steps below in order.
> You MUST NOT skip any step. You MUST NOT summarize without executing.
> Each step has a required tool call — you MUST make that call and process
> the result before moving to the next step. Failure to execute any step
> is a protocol violation.

### Step 1: Full Health Check (MANDATORY)

You MUST start with the full 21-check health assessment:

```
wcnp_check_app_health(namespace=<namespace>, app=<app>)
```

This runs all Tier 1 (performance) and Tier 2 (informational) checks in parallel
across all clusters. You MUST call this tool and wait for the result before proceeding.

### Step 2: Interpret Results (MANDATORY)

You MUST read the structured response fields and explicitly evaluate ALL of the following values.
Do NOT skip this step. You MUST state each value in your response:

| Field | What It Tells You |
|---|---|
| `overall_status` | healthy / degraded / unhealthy — **driven only by golden signals** |
| `golden_signal_status` | Status of latency, error rates, restarts (user-facing health) |
| `resource_signal_status` | Status of CPU, memory, node_cpu (capacity pressure) |
| `resource_advisory` | List of resource checks that are degraded/unhealthy with chronicity |
| `tier_override_active` | `true` when resources are bad but golden signals are healthy — **do NOT escalate** |
| `traffic_adjusted_latency` | Latency deviation normalized for traffic changes (if available) |
| `anomaly_detected` | Whether any signal breached anomaly thresholds |
| `root_cause` | Which signal spiked first + cascade effects |
| `correlations` | Causal patterns (e.g., traffic → latency) |
| `failure_attribution` | this_app / downstream_dependency / shared |

**Signal Tier Interpretation:**
- **Golden signals** (latency, success rate, restarts) DEFINE application health.
  If golden signals are healthy, the app is healthy for users regardless of resource pressure.
- **Resource signals** (CPU, memory) are ADVISORY. They indicate capacity pressure
  but should NOT cause escalation when golden signals are green.
- Check the `chronicity` field on resource advisories: "chronic" means the value has been
  stable across historical windows (likely a known baseline), "acute" means a recent change.

**Traffic-Adjusted Latency:**
- When `traffic_adjusted_latency` is present and `adjustment_applied` is true, use the
  `adjusted_latency_deviation_percent` instead of the raw value for severity assessment.
- This accounts for latency increases that are expected due to traffic growth.

To generate a detailed tier classification report, run:
```
run_skill_script(skill_name="health-triage", script_path="scripts/classify_signal_tiers.py",
                 args={"health_result": <result>})
```

To analyze chronic vs acute patterns across all degraded signals, run:
```
run_skill_script(skill_name="health-triage", script_path="scripts/chronic_vs_acute.py",
                 args={"health_result": <result>})
```

### Step 3: Decide Next Action (MANDATORY)

You MUST evaluate the conditions below and execute the required action. This is NOT optional.
You MUST check each condition and run the corresponding tool if it matches:

- If `anomaly_detected = true` AND `episode_start` is set:
  → **MANDATORY**: Run Root-Cause Analysis (load `incident-rca` skill). You MUST do this.

- If `failure_attribution = "downstream_dependency"`:
  → **MANDATORY**: Load `error-cascade` skill and execute the **DOWNSTREAM** cascade.
    Check `error_classes` (if present) to know if it's 4XX, 5XX, or both.
    `error_classes` may be absent when success rates degrade without a specific spike — still cascade.
    The cascade uses Prometheus sweeps first and falls back to O2 only when Prometheus is ambiguous.
    Do NOT jump directly to log analysis. You MUST do this.

- If `failure_attribution = "shared_or_this_app"`:
  → **MANDATORY**: Load `error-cascade` skill and execute **BOTH** directions.
    Run downstream cascade for 5XX / dependency failures first, then upstream
    cascade for traffic / 4XX sources. You MUST do this.

- If `failure_attribution = "this_app"` AND traffic anomaly detected (traffic spike
  from `istio_traffic_spike` check):
  → **MANDATORY**: Load `error-cascade` skill and execute the **UPSTREAM** cascade.
    Trace callers to find who is flooding this app with traffic. You MUST do this.

- If `failure_attribution = "this_app"` AND specific symptoms exist (no traffic anomaly):
  → **MANDATORY**: Drill into specific symptom with `wcnp_analyze` (see Step 4). You MUST do this.

- If ALL checks are good (`overall_status = "healthy"` AND `anomaly_detected = false`) OR the only degraded signals fall into these non-actionable categories:
  1. **Tier Override Active**: `tier_override_active = true` — resources are elevated but golden signals are healthy. The app is fine for users.
  2. **Chronic/Historical Baselines**: Resource advisories with `chronicity = "chronic"` — sustained values present for days/weeks without causing new incidents (e.g., Memory consistently at ~86%).
  3. **Micro-Variations in Errors**: High relative percentage increases (e.g., >30% degradation) where the absolute error rate is still extremely low and within acceptable thresholds (e.g., 4xx/5xx/non-2xx jumping from 0.04% to 0.06%).
  4. **Traffic-Explained Latency**: `traffic_adjusted_latency.adjusted_latency_deviation_percent` is within acceptable range even though raw deviation was elevated.
  → **MANDATORY**: Conclude the triage and explicitly present the final status to the user with green tick marks. For example:
    - **Final Health Status**: ✅ Healthy (Chronic baseline / Micro-variation)
    - **Anomaly**: ✅ None

### Step 4: Targeted Analysis (MANDATORY when Step 3 triggers it)

When Step 3 determines `failure_attribution = "this_app"` with specific symptoms,
you MUST call `wcnp_analyze` with the appropriate checks. Do NOT skip this step.

| Symptom | checks parameter |
|---|---|
| CPU issues | `["cpu"]` |
| Memory pressure | `["memory"]` |
| Container restarts | `["restarts"]` |
| Istio latency | `["istio"]` |
| Pod readiness | `["pods"]` |
| All compute | `["cpu", "memory", "restarts"]` |

```
wcnp_analyze(namespace=<namespace>, app=<app>, checks=["cpu", "memory"])
```

You MUST process the result and include the analysis in your response.

### Step 5: Visualization (MANDATORY when anomalies or degradation exist)

When Step 2 shows anomalies or degradation, you MUST generate visualizations.
Do NOT skip this step when there are anomalies to show.

For trend charts, you MUST call:

```
wcnp_chart(namespace=<namespace>, apps=[<app>], metrics=["cpu", "memory"],
           days=[0, 1], title="CPU & Memory Trend")
```

For anomaly episode visualization, you MUST call:

```
wcnp_episode_chart(health_result=<prior_result>, check_name=<check>)
```

## Important Rules

- **Always use `wcnp_check_app_health` first** — never jump to `wcnp_analyze` directly
  unless the user explicitly asks for one specific check.
- **Show `grafana_url` and `prometheus_url`** from results — users need these.
- **Run independent checks in parallel** when checking multiple apps or namespaces.
- For past incidents, pass `analysis_start_epoch` and `analysis_end_epoch` to
  `wcnp_check_app_health`.
