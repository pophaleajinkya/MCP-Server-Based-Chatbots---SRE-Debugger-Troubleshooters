# Health Agent — Architecture & Intelligence Layers

## Overview

The health-agent is a single LLM-powered agent that connects to multiple MCP
(Model Context Protocol) servers and answers natural language questions about
infrastructure health. Its intelligence is split across three layers so that:

- Token cost stays low on every query (only load what you need)
- Adding a new use case requires zero agent code changes
- Each MCP server owns its domain knowledge independently

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Question                               │
│        "item-assembler-async in iro-prod is slow, what's wrong?"   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       health-agent (LLM)                           │
│                                                                     │
│  Layer 1: _AGENT_INSTRUCTION  ←── always in context (5 lines)      │
│  Layer 2: AGENT.md guides     ←── loaded once at startup           │
│  Layer 3: MCP Prompts         ←── loaded on-demand per scenario     │
│                                                                     │
│  Orchestrates calls to:                                             │
│    health-mcp  (health checks, metrics, anomaly detection)         │
│    dependency-mcp (upstream/downstream graph)                       │
└──────┬──────────────────────────────────────┬───────────────────────┘
       │                                      │
       ▼                                      ▼
┌──────────────┐                   ┌──────────────────────┐
│  health-mcp  │                   │   dependency-mcp     │
│              │                   │                      │
│  Tools:      │                   │  Tools:              │
│  - check_    │                   │  - fetch_upstream_   │
│    app_health│                   │    dependencies      │
│  - analyze   │                   │  - fetch_downstream_ │
│  - query_    │                   │    dependencies      │
│    chart     │                   │  - list_apps_in_     │
│              │                   │    namespace         │
│  Resources:  │                   │                      │
│  - AGENT.md  │                   │  Resources:          │
│  - GRAPH_    │                   │  - AGENT.md          │
│    RENDERING │                   │    (dep guide)       │
│              │                   │                      │
│  Prompts:    │                   │  Prompts:            │
│  - full-     │                   │  - trace_wcnp_app    │
│    triage    │                   │  - trace_oneops_app  │
│  - cpu-usage │                   │                      │
│  - (15 more) │                   │                      │
└──────────────┘                   └──────────────────────┘
```

---

## The Three Layers

### Layer 1 — `_AGENT_INSTRUCTION` (The Agent's DNA)

**File:** `src/agent/__init__.py`
**Always in context:** Yes — sent to the LLM on every single query
**Size:** ~5 lines (~50 tokens)
**Changes:** Rarely — only when the agent's fundamental role changes

```python
_AGENT_INSTRUCTION = (
    "You are a health and dependency intelligence assistant for Walmart's infrastructure. "
    "Use the available tools to answer every question. "
    "Call tools immediately — never ask for confirmation before calling a tool. "
    "The domain-specific guides below describe how to handle each scenario. "
    "Follow them step-by-step. "
    "Only describe your own capabilities if the user explicitly asks."
)
```

**What it does:**
- Defines WHO the agent is (role)
- Defines HOW it behaves (call tools immediately, no confirmation)
- Points to Layer 2 for scenario guidance ("the guides below")

**What it does NOT contain:**
- Any scenario-specific workflows
- Any tool names or PromQL queries
- Any domain knowledge (health, dependencies, etc.)

---

### Layer 2 — MCP Guides / AGENT.md (The Routing Table)

**Files:**
- `health_mcp/resources/AGENT.md` → served as `wcnp://agent-guide`
- `maof-dependency-agent/resources/AGENT.md` → served as `dependency://agent-guide`

**Loaded:** Once at agent startup, injected into the system instruction
**Size:** ~500-800 tokens per MCP server
**Changes:** When a new use-case category is added (one new row in the routing table)

**How it's loaded:**

```
Startup sequence:
  MCPSession.connect()
    → _load_guide()
      → resources/list RPC         ← discovers all *://agent-guide resources
      → resources/read RPC (each)  ← loads their content

  MCPPool.connect()
    → concatenates guides from ALL connected MCP servers
    → mcp_pool.guide = health-guide + "---" + dependency-guide

  make_agent(guide=mcp_pool.guide)
    → instruction = Layer 1 + "\n---\n" + Layer 2 (all guides combined)
```

**What it contains — health-mcp AGENT.md example:**

```markdown
## Tool Selection Guide
| User says...                     | Use this tool              |
| "Check health of my app"         | wcnp_check_app_health      |
| "What's CPU like?"               | wcnp_analyze (checks=cpu)  |
| "Compare across clusters"        | wcnp_chart    |

## Use-Case Routing Table
| User asks about...        | Call this prompt       | Key arguments          |
| P99 latency / slow req    | wcnp-istio-latency     | namespace, app         |
| Full incident triage      | wcnp-full-triage       | namespace, app         |
| CPU usage / throttling    | wcnp-cpu-usage         | namespace, app         |
| ... (15 total)            | ...                    | ...                    |

## Cross-Service Root-Cause Analysis
When you find an anomaly with episode_start set:
1. Fetch upstream/downstream dependencies
2. Check health of all upstream apps
3. Compare episode_start times ...
```

**What it contains — dependency-mcp AGENT.md example:**

```markdown
## When to use which tool
- WCNP app (Kubernetes)? → fetch_wcnp_upstream/downstream_dependencies
- OneOps app?           → fetch_oneops_upstream/downstream_dependencies
- Cassandra?            → fetch_cassandra_upstream_dependencies

## Decision tree
User asks about an app's dependencies?
  Is it WCNP? → use fetch_wcnp_*
  Is it OneOps? → use fetch_oneops_*
  ...
```

**Key property:** Each MCP server owns its Layer 2 guide. The agent code never
knows which use cases exist — it learns them from the guides at startup.

---

### Layer 3 — MCP Prompts (The Workflow Templates)

**Files:**
- `health_mcp/src/prompts/wcnp.py` — 15 use-case prompts
- `maof-dependency-agent/src/mcp_server/resources_and_prompts.py` — trace prompts

**Loaded:** On-demand, only when a specific use case is triggered
**Size:** ~800-1500 tokens per prompt (only 1 prompt loaded per use case)
**Changes:** Never, for existing use cases. New use case = new prompt file.

**How it's loaded:**

```
Agent sees: episode_start in health check result
→ Layer 2 routing table says: "full triage → get_mcp_prompt('wcnp-full-triage', ...)"
→ Agent calls: get_mcp_prompt("wcnp-full-triage", {"namespace": "iro-prod", "app": "item-assembler-async"})
→ MCP server renders the prompt template with those arguments
→ Returns: step-by-step PromQL queries, decision tree, interpretation guide
→ Agent follows the instructions and calls the right health tools
```

**What a Layer 3 prompt contains — wcnp-full-triage example:**

```markdown
## WCNP — Full Incident Triage for `item-assembler-async` in `iro-prod`

Run these PromQL queries in order:
1. Replica readiness:  sum by (deployment) (kube_deployment_status_replicas_ready{namespace="iro-prod"}) / ...
2. Container restarts: sum(increase(kube_pod_container_status_restarts_total{namespace="iro-prod"}[1h]) ...) ...
3. CPU usage ratio: max(rate(container_cpu_usage_seconds_total{...}[5m])) ...
4. Memory usage ratio: ...
5. Istio client success rate: ...
6. Istio P99 latency: ...
7. External secret sync failures: ...
8. Rollout activity: ...

Decision tree:
| Signal                | Likely cause         | Next step                       |
| Replicas < desired    | Pod crash / OOM      | Check restarts + memory         |
| Restarts > 0, CPU 80% | CPU throttle         | Raise CPU limit or scale out    |
| Latency spike, OK SR  | Slow dependency      | Check dependency P99            |
| Secrets not synced    | Credentials issue    | Check Akeyless + pod events     |
```

**Adding a new use case — zero agent code changes:**

```python
# 1. Write the prompt in health_mcp/src/prompts/wcnp.py
def _render_redis_memory_pressure(args):
    ns  = args.get("namespace", "<namespace>")
    app = args.get("app", "<app>")
    return f"""
## Redis Memory Pressure — {app} in {ns}

Run these queries:
1. Memory fragmentation ratio: redis_mem_fragmentation_ratio{{...}}
2. ...
"""

# 2. Register it in the prompt registry
_register(PromptDef(
    name="wcnp-redis-memory",
    description="Diagnose Redis memory pressure for a WCNP app.",
    arguments=[_req("namespace", "..."), _req("app", "...")],
    render=_render_redis_memory_pressure,
))

# 3. Add one row to health_mcp/resources/AGENT.md
# | Redis memory pressure / eviction | wcnp-redis-memory | namespace, app |

# That's it. No changes to health-agent.
```

---

## Which Layer Orchestrates?

**The LLM (Layer 1) orchestrates. Not any MCP tool.**

```
┌──────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATION                                 │
│                                                                   │
│  Layer 1 (_AGENT_INSTRUCTION):                                   │
│    "Call tools immediately. Follow the guides."                  │
│    ↑ This is what makes the agent an AGENT, not a chatbot.       │
│    ↑ It decides WHEN to call which tool, in what order.          │
│                                                                   │
│  Layer 2 (AGENT.md):                                             │
│    "For latency → use wcnp-full-triage prompt"                   │
│    "Found anomaly? → check upstream dependencies"                │
│    ↑ This gives the agent ROUTING RULES across use cases.        │
│    ↑ It shapes WHICH scenario workflow to trigger.               │
│                                                                   │
│  Layer 3 (MCP Prompts):                                          │
│    "Here are 8 PromQL queries and a decision tree"               │
│    ↑ This gives step-by-step EXECUTION INSTRUCTIONS.             │
│    ↑ It provides WHAT to do within a specific use case.          │
└──────────────────────────────────────────────────────────────────┘
```

The LLM reads Layer 1 + Layer 2 (always in context), decides which workflow
to trigger, loads Layer 3 (the specific prompt), then orchestrates all tool
calls: health checks, dependency lookups, metric queries, chart rendering.

---

## How health-mcp + dependency-mcp Solve Anomalies Together

### Scenario: "item-assembler-async in iro-prod is experiencing high latency"

```
STEP 1 — Primary health check (health-mcp)
──────────────────────────────────────────
Agent calls: wcnp_check_app_health(namespace="iro-prod", app="item-assembler-async")

health-mcp runs 21 checks in parallel:
  ✓ CPU: healthy
  ✓ Memory: healthy
  ✗ istio_client_latency: DEGRADED
      episode_start = "2026-03-15T21:00:00Z"  ← anomaly started at 9:00 PM
      peak_value    = 4350 ms
      baseline      = 85 ms
      deviation     = +5000%
      grafana_url   = "https://grafana.cluster.../istio-dashboard?..."

Layer 2 rule fires: "anomaly found with episode_start → fetch dependencies"


STEP 2 — Dependency discovery (dependency-mcp)
───────────────────────────────────────────────
Agent calls (parallel):
  fetch_wcnp_upstream_dependencies(app_name="item-assembler-async", namespace="iro-prod")
    → [svc-inventory-reader, svc-pricing-engine, svc-catalog-api]

  fetch_wcnp_downstream_dependencies(app_name="item-assembler-async", namespace="iro-prod")
    → [svc-order-fulfillment, svc-notification]


STEP 3 — Upstream health checks before episode_start (health-mcp)
──────────────────────────────────────────────────────────────────
Agent calls (parallel) for all 3 upstream apps:
  wcnp_check_app_health(namespace="iro-prod", app="svc-inventory-reader")
    → healthy (no anomaly)

  wcnp_check_app_health(namespace="iro-prod", app="svc-pricing-engine")
    → UNHEALTHY: istio_client_latency
       episode_start = "2026-03-15T20:50:00Z"  ← 10 min BEFORE primary!
       peak_value    = 8200 ms

  wcnp_check_app_health(namespace="iro-prod", app="svc-catalog-api")
    → UNHEALTHY: istio_traffic_spike
       episode_start = "2026-03-15T20:56:00Z"  ← 4 min before primary
       peak_value    = 3.2x baseline


STEP 4 — Downstream check (health-mcp)
────────────────────────────────────────
  wcnp_check_app_health(namespace="iro-prod", app="svc-order-fulfillment")
    → DEGRADED: istio_client_success_rate
       episode_start = "2026-03-15T21:07:00Z"  ← 7 min AFTER primary


STEP 5 — Agent builds the cascade timeline (LLM reasoning)
────────────────────────────────────────────────────────────
Comparing episode_start times using Layer 2 rule:

  8:50 PM — svc-pricing-engine:         latency spike +9500%  [UPSTREAM, EARLIEST → ROOT CAUSE]
  8:56 PM — svc-catalog-api:            traffic spike +220%   [UPSTREAM, BEFORE primary → CONTRIBUTING]
  9:00 PM — item-assembler-async:       latency degraded      [PRIMARY INCIDENT]
  9:07 PM — svc-order-fulfillment:      success rate drop     [DOWNSTREAM → CASCADING EFFECT]

Conclusion: svc-pricing-engine's latency spike at 8:50 PM (10 min before primary)
is the root cause. svc-catalog-api's traffic spike amplified the effect.
item-assembler-async's slowness then cascaded to svc-order-fulfillment.


STEP 6 — Render charts (health-mcp)
────────────────────────────────────
Agent calls (from Layer 2 routing: "visualization → wcnp-visualization-guide"):
  wcnp_chart(
    namespace="iro-prod",
    apps=["svc-pricing-engine", "item-assembler-async", "svc-order-fulfillment"],
    metric="p95_latency",
    hours=2
  )
  → render_chart(...) → UI shows the cascade timeline as a chart


FINAL RESPONSE TO USER:
  "Root cause: svc-pricing-engine (upstream) had a latency spike at 8:50 PM,
   10 minutes before item-assembler-async degraded. This cascaded to
   svc-order-fulfillment at 9:07 PM.

   Cascade timeline:
     8:50 PM — svc-pricing-engine: P99 +9500% [ROOT CAUSE]
     8:56 PM — svc-catalog-api: traffic +220% [CONTRIBUTING]
     9:00 PM — item-assembler-async: latency degraded [PRIMARY]
     9:07 PM — svc-order-fulfillment: success rate drop [CASCADE]

   [Grafana URL for svc-pricing-engine Istio dashboard]
   [Chart: latency comparison across the cascade chain]"
```

---

## Anomaly Detection Use Case — All Three Layers Working Together

This example shows how the three layers cooperate to detect, explain, and
correlate anomalies when a user asks a simple question.

**User question:** *"Is there anything abnormal with signal-api in namespace intl-sre?"*

---

### What "anomaly detection" means in this system

health-mcp does not just check if a metric is above a threshold.
It compares every metric to a **rolling multi-day baseline** (Z-score over 11
historical days, with outlier days auto-excluded). An anomaly is triggered when:

```
current_value > baseline_mean + (N × baseline_stddev)

AND the deviation has persisted long enough to form an "episode"
  → episode_start  = when the anomaly first crossed the threshold
  → episode_end    = when it recovered (null = still active)
  → peak_value     = worst observed value during the episode
  → duration_minutes = how long it has been active
  → deviation_percent = how far above baseline
```

This means the agent always knows **when** an anomaly started, not just that
one exists right now — which is the key to cross-service correlation.

---

### Layer 1 fires first (always in context)

```
_AGENT_INSTRUCTION says: "Call tools immediately."

→ Agent calls wcnp_check_app_health(namespace="intl-sre", app="signal-api")
  No confirmation, no description, just the call.
```

---

### health-mcp runs 21 checks in parallel

```
RESULT from wcnp_check_app_health:
{
  "overall_status": "unhealthy",
  "checks": {

    "cpu": {
      "status": "healthy"
    },

    "memory": {
      "status": "healthy"
    },

    "istio_client_latency": {
      "status": "unhealthy",
      "anomaly_detected": true,
      "episode_start":    "2026-03-15T14:23:00Z",   ← anomaly started at 2:23 PM
      "episode_end":       null,                     ← still active NOW
      "still_active":      true,
      "duration_minutes":  47,                       ← ongoing for 47 minutes
      "peak_value":        5200,                     ← 5.2 seconds P99 latency
      "baseline_value":    95,                       ← normal is ~95ms
      "deviation_percent": 5368,                     ← 5368% above normal
      "grafana_url": "https://grafana.scus-prod-a74.cluster.../istio-service-dashboard..."
    },

    "istio_client_success_rate": {
      "status": "degraded",
      "anomaly_detected": true,
      "episode_start":    "2026-03-15T14:25:00Z",   ← 2 minutes after latency spike
      "peak_value":        0.71,                     ← 71% success rate
      "baseline_value":    0.998,                    ← normal is 99.8%
      "deviation_percent": -28.9
    },

    "istio_traffic_spike": {
      "status": "healthy"                            ← traffic is normal
    },

    "container_restarts": {
      "status": "healthy"
    },

    "correlations": [
      {
        "pattern": "dependency_failure",
        "checks_involved": ["istio_client_latency", "istio_client_success_rate"],
        "confidence": "high",
        "description": "Client latency very high + success rate dropping but no
                         server-side errors detected → fault is in a downstream
                         dependency, not in signal-api itself."
      }
    ],

    "failure_attribution": "downstream_dependency"
  }
}
```

---

### Layer 2 routing table fires (AGENT.md already in context)

```
The agent reads the routing table from AGENT.md injected at startup:

  "anomaly found with episode_start → fetch upstream/downstream dependencies
   and compare episode_start times to identify root cause"

  "latency issue → get_mcp_prompt('wcnp-istio-latency', ...)"

  "failure_attribution = downstream_dependency → check downstream services"

Two triggers fire simultaneously:
  1. episode_start is set → dependency correlation workflow
  2. latency anomaly found → load wcnp-istio-latency prompt (Layer 3)
```

---

### Layer 3 loads on-demand (MCP Prompt)

```
Agent calls: get_mcp_prompt("wcnp-istio-latency", {
  "namespace": "intl-sre",
  "app": "signal-api",
  "direction": "client"
})

Returns the rendered workflow:
  "## WCNP — Istio Client P99 Latency for signal-api

   Run these queries as range queries (last 1h, step=1m):

   P99 latency:
   histogram_quantile(0.99, sum(rate(envoy_cluster_upstream_rq_time_bucket{
     cluster_name=~"outbound.*signal-api.*intl-sre.*"
   }[1m])) by (le)) * 1000

   P50 latency (baseline):
   histogram_quantile(0.50, ...) * 1000

   Interpretation:
   - P99 > 1000ms  → degraded
   - P99 > 3000ms  → critical
   - Large P99-P50 gap → tail latency problem, often a slow downstream call.
   ...
   After running, call render_chart(...)."

Agent now has exact PromQL queries + interpretation rules for this use case.
```

---

### Agent correlates across services (dependency-mcp + health-mcp)

```
STEP A — fetch dependencies
  fetch_wcnp_downstream_dependencies(app_name="signal-api", namespace="intl-sre")
  → [account-service, product-catalog, redis-cache-proxy]

  fetch_wcnp_upstream_dependencies(app_name="signal-api", namespace="intl-sre")
  → [api-gateway, mobile-bff]


STEP B — health checks on all dependencies (parallel)
  wcnp_check_app_health("intl-sre", "account-service")
  → UNHEALTHY: istio_client_latency
     episode_start    = "2026-03-15T14:18:00Z"  ← 5 min BEFORE signal-api!
     peak_value       = 12000 ms
     deviation_percent = 12200%

  wcnp_check_app_health("intl-sre", "product-catalog")
  → healthy

  wcnp_check_app_health("intl-sre", "redis-cache-proxy")
  → healthy

  wcnp_check_app_health("intl-sre", "api-gateway")
  → healthy (upstream)

  wcnp_check_app_health("intl-sre", "mobile-bff")
  → DEGRADED: istio_client_latency
     episode_start = "2026-03-15T14:29:00Z"  ← 6 min AFTER signal-api
     ← upstream caller degraded AFTER signal-api → cascade effect, not cause


STEP C — episode_start timeline comparison (agent reasoning)
  2:18 PM — account-service:  P99 latency spike +12200% [DOWNSTREAM, EARLIEST → ROOT CAUSE]
  2:23 PM — signal-api:       P99 latency spike +5368%  [PRIMARY — 5 min after account-service]
  2:25 PM — signal-api:       success rate drop -29%    [PRIMARY — secondary effect]
  2:29 PM — mobile-bff:       P99 latency degraded      [UPSTREAM CALLER — cascade victim]

  Logic:
  • account-service is a DOWNSTREAM dependency of signal-api
  • Its episode started 5 minutes BEFORE signal-api's episode
  • failure_attribution from health check = "downstream_dependency"
  • ALL confirm: account-service is the root cause
```

---

### Charts rendered automatically (graph event pipeline)

```
Agent calls:
  wcnp_chart(
    namespace="intl-sre",
    cluster_ids=["scus-prod-a74", "uswest-prod-az-045"],
    metric="p95_latency",
    hours=2
  )
  → MCP response contains chart_data
  → runner.py detects chart_data → emits type:"graph" SSE event
  → UI renders: P95 Latency Comparison chart showing the cascade

  wcnp_chart(cluster_id="scus-prod-a74", namespace="intl-sre", app="signal-api", hours=2)
  → MCP response contains multi_chart_data
  → runner.py emits type:"graph" SSE event
  → UI renders: 5-panel dashboard (CPU, Memory, Restarts, Latency, Success Rate)
```

---

### Final response to user

```
"⚠️ signal-api has an active latency anomaly (ongoing 47 minutes):
   P99 latency = 5,200 ms (normal: ~95 ms, +5368%)
   Success rate = 71% (normal: 99.8%)

Root cause: account-service (downstream dependency)
   account-service P99 latency spiked at 2:18 PM — 5 minutes before signal-api
   degraded. signal-api calls account-service; the slowness propagated upstream.

Cascade timeline:
   2:18 PM — account-service: P99 +12,200%   [ROOT CAUSE — downstream dep]
   2:23 PM — signal-api:      P99 +5,368%    [PRIMARY INCIDENT]
   2:25 PM — signal-api:      success rate -29%  [secondary effect]
   2:29 PM — mobile-bff:      P99 degraded   [UPSTREAM CALLER — cascade victim]

Health checks on all other dependencies (product-catalog, redis-cache-proxy,
api-gateway) are healthy — the fault is isolated to account-service.

[Grafana: Istio Service Dashboard for signal-api →]
[Chart: P95 Latency Comparison across clusters]
[Dashboard: CPU / Memory / Restarts / Latency / Success Rate for signal-api]

Recommended next step: run wcnp_check_app_health on account-service to find
what caused its latency spike at 2:18 PM."
```

---

### Anomaly detection — what each layer contributed

| Layer | Contribution to this answer |
|---|---|
| **Layer 1** | Decided to call `wcnp_check_app_health` immediately with no confirmation |
| **Layer 1** | Orchestrated all parallel tool calls (dependency fetch + health checks) |
| **Layer 2** | Told the agent: "anomaly with episode_start → fetch dependencies" |
| **Layer 2** | Told the agent: "latency issue → load wcnp-istio-latency prompt" |
| **Layer 2** | Provided the cross-service rule: compare episode_start to find root cause |
| **Layer 3** | Provided exact PromQL queries for P99 + P50 latency |
| **Layer 3** | Provided interpretation thresholds (>1000ms degraded, >3000ms critical) |
| **health-mcp** | Detected the anomaly with exact episode_start, deviation %, grafana URL |
| **health-mcp** | Ran intra-app correlation (latency + success rate = dependency_failure) |
| **health-mcp** | Returned chart_data / multi_chart_data → auto-rendered as graphs |
| **dependency-mcp** | Returned the upstream/downstream dependency list |
| **LLM (agent)** | Cross-referenced episode_start times with dependency direction |
| **LLM (agent)** | Concluded: downstream started 5 min before → root cause |
| **LLM (agent)** | Built the final cascade timeline and human-readable explanation |

---

## Token Cost Breakdown

```
Every query (baseline):
  Layer 1 _AGENT_INSTRUCTION     ~50 tokens   (always)
  Layer 2 AGENT.md (both MCPs)   ~800 tokens  (loaded once, always in context)
  Tool schemas (12 health + 15 dep tools) ~2000 tokens (always)
  ─────────────────────────────────────────────────────
  Baseline per query              ~2850 tokens

When a specific use case triggers:
  Layer 3 MCP Prompt (one prompt) ~1000 tokens (on-demand, this query only)
  ─────────────────────────────────────────────────────
  Total when use case triggers    ~3850 tokens

Compared to "everything in system prompt" approach (50 use cases × 1000t each):
  Naive approach                 ~52850 tokens per query
  3-layer approach               ~3850 tokens per query
  ─────────────────────────────────────────────────────
  Savings                        ~93% reduction
```

---

## Adding a New MCP Server

When a new MCP server is connected (e.g. `cosmos-mcp`), the agent automatically
picks up its domain knowledge at startup:

```
1. cosmos-mcp exposes resource: cosmos://agent-guide
   Content: "Use cosmos_check_account_health for Cosmos DB issues.
             For throttling → get_mcp_prompt('cosmos-throttling-triage', ...)
             ..."

2. Agent startup:
   MCPSession._load_guide() discovers cosmos://agent-guide
   MCPPool.guide += cosmos-mcp guide
   instruction = Layer1 + health-guide + dep-guide + cosmos-guide

3. User asks: "CosmosDB is getting throttled"
   → Agent reads the combined Layer 2 routing table
   → Finds: "CosmosDB throttling → cosmos-throttling-triage prompt"
   → Loads that prompt (Layer 3)
   → Executes the Cosmos-specific triage workflow

No changes to health-agent code.
```

---

## Summary

| Layer | What it is | Who owns it | When loaded | Size |
|---|---|---|---|---|
| **Layer 1** `_AGENT_INSTRUCTION` | Agent role + behavior rules | health-agent code | Every query | ~50 tokens |
| **Layer 2** `AGENT.md` resources | Routing table + cross-domain rules | Each MCP server | Once at startup | ~800 tokens total |
| **Layer 3** MCP Prompts | Step-by-step workflow per use case | Each MCP server | On-demand per query | ~1000 tokens (1 prompt) |

**Layer 1 orchestrates** — the LLM decides what to call and in what order.
**Layer 2 routes** — tells the LLM which scenario applies and which prompt to load.
**Layer 3 instructs** — gives the LLM exact steps for a specific use case.

The MCP servers are **passive data + knowledge providers**.
The LLM (agent) is the **active orchestrator** that combines data from multiple MCPs,
reasons about timing, and builds the final analysis.
