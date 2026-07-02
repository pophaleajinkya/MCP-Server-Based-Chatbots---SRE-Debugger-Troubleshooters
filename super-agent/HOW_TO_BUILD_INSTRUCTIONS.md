# How to Build Agent Instructions

This document explains the three-layer instruction system, where each layer
lives, how they are loaded and combined at runtime, and how to add new use
cases or connect a new MCP server without changing agent code.

---

## The Three Layers — What They Are

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — Agent Base Instruction                                       │
│  File:   health-agent/resources/AGENT_INSTRUCTION.md                   │
│  Loaded: At agent startup, always in LLM context                        │
│  Size:   ~300-500 tokens                                                │
│  Owner:  Agent team                                                     │
│                                                                         │
│  Contains:                                                              │
│    • Agent role (who it is)                                             │
│    • Behavioral rules (call tools immediately, run in parallel, etc.)  │
│    • Tool usage guide (which tool for which question)                  │
│    • Decision logic (root-cause analysis, cascade timeline)            │
│    • Output format                                                      │
│    • Routing table: "for symptom X → call get_mcp_prompt('wcnp-X')"   │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 2 — MCP Server Guides (AGENT.md per MCP server)                 │
│  File:   <mcp-repo>/resources/AGENT.md                                 │
│  Loaded: At agent startup via MCP resources/list + resources/read      │
│          Appended to Layer 1 instruction                                │
│  Size:   ~500-800 tokens per MCP server                                │
│  Owner:  MCP server team                                               │
│                                                                         │
│  Contains:                                                              │
│    • Tool selection guide for this domain                               │
│    • Routing table: "for use-case Y → call prompt Z"                   │
│    • Domain-specific rules and response interpretation                  │
│    • Cross-service workflows that use this server's tools               │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 3 — MCP Prompts (one per use case)                              │
│  File:   <mcp-repo>/src/prompts/<domain>.py                            │
│  Loaded: On-demand when agent calls get_mcp_prompt(name, args)         │
│  Size:   ~800-1500 tokens (loaded only when that use case fires)       │
│  Owner:  MCP server team                                               │
│                                                                         │
│  Contains:                                                              │
│    • Step-by-step PromQL queries for the specific use case              │
│    • Thresholds and interpretation rules                                │
│    • Decision tree for that scenario                                    │
│    • Visualization instructions                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## How the Layers Are Loaded at Runtime

### Step 1 — Agent startup reads Layer 1

```python
# src/agent/__init__.py
_INSTRUCTION_FILE = Path(__file__).parents[2] / "resources" / "AGENT_INSTRUCTION.md"
_AGENT_INSTRUCTION = _INSTRUCTION_FILE.read_text()
```

### Step 2 — Agent connects to MCP servers and loads Layer 2

```python
# src/app/mcp/client.py — MCPSession._load_guide()
#
# For EACH connected MCP server:
#   1. Call resources/list RPC → get list of all resources
#   2. Find any resource whose URI ends with "://agent-guide"
#   3. Call resources/read RPC for each one → get the markdown content
#   4. Concatenate all guides from all servers

list_resp  = await self._rpc("resources/list", {})
resources  = list_resp["result"]["resources"]
guide_uris = [r["uri"] for r in resources if r["uri"].endswith("://agent-guide")]
# e.g. ["wcnp://agent-guide", "dependency://agent-guide"]

for uri in guide_uris:
    resp = await self._rpc("resources/read", {"uri": uri})
    text = resp["result"]["contents"][0]["text"]
    self.guide += text
```

### Step 3 — Combined instruction is built

```python
# src/agent/__init__.py — make_agent()
instruction = Layer1_AGENT_INSTRUCTION
if guide:                              # guide = all Layer 2 content combined
    instruction = f"{Layer1}\n\n---\n\n{guide}"
```

The LLM receives this combined instruction on every query:
```
[Layer 1: AGENT_INSTRUCTION.md content]
---
[Layer 2: health-mcp AGENT.md content]
---
[Layer 2: dependency-mcp AGENT.md content]
```

### Step 4 — Layer 3 loaded on-demand during a query

```python
# Agent calls this tool when the routing table says to
get_mcp_prompt("wcnp-full-triage", {"namespace": "intl-sre", "app": "signal-api"})

# Internally: POST /mcp/prompts/wcnp-full-triage with arguments
# Returns: rendered step-by-step workflow text
# Added to conversation as a tool result — LLM reads and executes
```

### Step 5 — ADK callback enforces critical behaviors

```python
# src/app/hooks/session_hooks.py — handle_health_check_result()
# Registered as after_tool_callback on the agent
#
# When wcnp_check_app_health returns anomaly_detected=true:
#   → Injects "⚡ AGENT DIRECTIVE: fetch dependencies now" into the tool response
#   → LLM sees it as part of the data — cannot ignore it
#   → Guarantees root-cause analysis fires every time
```

---

## Token Cost

```
Every query always pays:
  Layer 1 AGENT_INSTRUCTION.md     ~400 tokens
  Layer 2 all AGENT.md guides      ~800 tokens  (loaded once at startup)
  Tool schemas (all tools)         ~2000 tokens
  ──────────────────────────────────────────────
  Baseline per query               ~3200 tokens

When a specific use case triggers (one prompt only):
  Layer 3 MCP prompt               ~1000 tokens  (this query only)
  ──────────────────────────────────────────────
  Total with use case              ~4200 tokens

vs. putting all 15 use cases in system prompt:
  15 × 1000 tokens                 ~15000 tokens  (every query, even irrelevant)
```

---

## How to Add a New Use Case to an Existing MCP Server

**Example: Add "Redis memory pressure" diagnosis to health-mcp**

### Step 1 — Write the prompt in the MCP server

```python
# health_mcp/src/prompts/wcnp.py

def _render_redis_memory(args: dict[str, str]) -> str:
    ns  = args.get("namespace", "<namespace>")
    app = args.get("app", "<app>")
    return dedent(f"""\
        ## WCNP — Redis Memory Pressure for `{app}` in `{ns}`

        ### Step 1 — Check memory fragmentation ratio
        ```promql
        redis_mem_fragmentation_ratio{{namespace="{ns}", app="{app}"}}
        ```
        Threshold: > 1.5 = fragmented, > 2.0 = critical

        ### Step 2 — Check evicted keys rate
        ```promql
        rate(redis_evicted_keys_total{{namespace="{ns}", app="{app}"}}[5m])
        ```
        Any evictions → data loss risk

        ### Interpretation
        - fragmentation > 1.5 + evictions → Redis needs restart
        - evictions only → increase maxmemory limit
        - Correlate with app OOM errors in istio success rate
    """)

# Register it
_register(PromptDef(
    name="wcnp-redis-memory",
    description="Diagnose Redis memory pressure and eviction for a WCNP app.",
    arguments=[_req("namespace", "Kubernetes namespace"), _req("app", "App name")],
    render=_render_redis_memory,
))
```

### Step 2 — Add one row to the routing table in AGENT.md

```markdown
# health_mcp/resources/AGENT.md

## Use-Case Routing Table
...
| Redis memory pressure / eviction | `wcnp-redis-memory` | namespace, app |
```

### Step 3 — Deploy health_mcp

```bash
# health-agent: ZERO changes required
# Just deploy the MCP server

kubectl rollout restart deployment/health-mcp
# Agent picks up the new prompt at next restart
```

**That's it. Three changes, all in the MCP server repo.**

---

## How to Connect a New MCP Server

**Example: Connect a new `cassandra-mcp` server**

### Step 1 — The new MCP server must expose an agent-guide resource

```python
# cassandra-mcp/resources/AGENT.md  ← create this file

# cassandra-mcp/src/server.py or app.py
@mcp.resource("cassandra://agent-guide")
def get_agent_guide() -> str:
    return (RESOURCES_DIR / "AGENT.md").read_text()
```

The URI must end with `://agent-guide` — that's the convention the health-agent
uses to discover guides automatically.

```markdown
# cassandra-mcp/resources/AGENT.md

# Cassandra Health Agent Guide

## When to use Cassandra tools
Use when the user asks about:
- Cassandra query timeouts or slow reads
- Node health, disk pressure, compaction
- Cluster replication lag

## Tool Selection
| User asks...                    | Tool                              |
| Cassandra slow queries          | cassandra_check_cluster_health    |
| Who calls this Cassandra cluster| fetch_cassandra_upstream_deps     |

## Use-Case Routing Table
| Symptom                  | Prompt name              | Arguments       |
| Timeout / slow queries   | cassandra-timeout-triage | cluster, keyspace |
| High compaction          | cassandra-compaction     | cluster         |
| Replication lag          | cassandra-replication    | cluster         |
```

### Step 2 — Register the new MCP server in the agent config

```yaml
# health-agent/src/config/mcp_servers.yml

mcp_servers:
  - name: health-mcp
    url: http://health-mcp:8999/mcp/
    transport: streamable_http
    enabled: true

  - name: dependency-mcp
    url: http://dependency-mcp:8015/mcp/
    transport: streamable_http
    enabled: true

  - name: cassandra-mcp          # ← add this
    url: http://cassandra-mcp:8020/mcp/
    transport: streamable_http
    enabled: true
    headers: {}
```

Or in production via Redis (no file needed):
```bash
# Push config to Redis key: agent:config:mcp_servers:<env>:<group>:config
# Agent reads this at startup — no deployment required
```

### Step 3 — Restart the agent

```bash
kubectl rollout restart deployment/health-agent
```

At startup:
1. Agent connects to `cassandra-mcp`
2. `MCPSession._load_guide()` finds `cassandra://agent-guide` → loads it
3. `MCPPool.guide` now contains health-mcp guide + dependency-mcp guide + **cassandra-mcp guide**
4. Agent instruction includes the Cassandra routing table automatically
5. User asks "Why is Cassandra slow?" → agent reads routing table → calls `cassandra-timeout-triage` prompt → gets the full workflow

**Zero changes to health-agent code.**

---

## Where Different Kinds of Instructions Live

```
┌─────────────────────────────────────────────────────────────────────────┐
│  "Who is this agent and how does it behave?"                           │
│                                                                         │
│  → health-agent/resources/AGENT_INSTRUCTION.md                        │
│                                                                         │
│  Examples:                                                              │
│    "Call tools immediately"                                             │
│    "Run independent calls in parallel"                                  │
│    "When anomaly_detected=true, fetch dependencies"                    │
│    "Build cascade timeline ordered by episode_start"                   │
│    "Always show grafana_url in responses"                               │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  "What tools does this MCP server have and when to use them?"          │
│                                                                         │
│  → <mcp-repo>/resources/AGENT.md                                       │
│    Exposed as: <scheme>://agent-guide MCP resource                     │
│                                                                         │
│  Examples (health-mcp/resources/AGENT.md):                            │
│    "User says 'check health' → use wcnp_check_app_health"             │
│    "Latency issue → call prompt wcnp-istio-latency"                   │
│    "full triage → call prompt wcnp-full-triage"                        │
│                                                                         │
│  Examples (dependency-mcp/resources/AGENT.md):                        │
│    "WCNP app → use fetch_wcnp_upstream_dependencies"                  │
│    "OneOps app → use fetch_oneops_upstream_dependencies"              │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  "How do I diagnose this specific symptom step-by-step?"              │
│                                                                         │
│  → <mcp-repo>/src/prompts/<domain>.py                                 │
│    Exposed as: MCP prompt, called via get_mcp_prompt(name, args)       │
│                                                                         │
│  Examples:                                                              │
│    wcnp-cpu-usage    → exact PromQL + thresholds + interpretation      │
│    wcnp-full-triage  → 8 queries + decision tree for full incident     │
│    cassandra-timeout → Cassandra-specific queries + remediation        │
│    redis-memory      → Redis memory + eviction diagnosis               │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  "When this tool returns X, automatically trigger Y"                   │
│                                                                         │
│  → health-agent/src/app/hooks/session_hooks.py                        │
│    Registered as: after_tool_callback on the ADK Agent                 │
│                                                                         │
│  Examples:                                                              │
│    wcnp_check_app_health returns anomaly_detected=true                 │
│    → inject directive: "fetch dependencies and compare episode_start"  │
│                                                                         │
│  This is the ADK-native pattern for guaranteed trigger logic.          │
│  Instructions say what to do; callbacks enforce that it happens.       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference — What Goes Where

| Instruction type | File | Format | Loaded |
|---|---|---|---|
| Agent role + behavior rules | `health-agent/resources/AGENT_INSTRUCTION.md` | Markdown | Always (Layer 1) |
| Cross-service workflows (uses tools from multiple MCPs) | `health-agent/resources/AGENT_INSTRUCTION.md` | Markdown | Always (Layer 1) |
| Domain tool selection guide | `<mcp>/resources/AGENT.md` | Markdown | Always (Layer 2) |
| Use-case routing table | `<mcp>/resources/AGENT.md` | Markdown table | Always (Layer 2) |
| Step-by-step symptom diagnosis | `<mcp>/src/prompts/<domain>.py` | Python function | On-demand (Layer 3) |
| Automatic trigger (when X → do Y) | `health-agent/src/app/hooks/session_hooks.py` | ADK callback | Framework-level |

---

## File Structure Summary

```
health-agent/
├── resources/
│   └── AGENT_INSTRUCTION.md        ← Layer 1 (edit to change agent behavior)
├── src/
│   ├── agent/
│   │   └── __init__.py             ← loads AGENT_INSTRUCTION.md + wires callbacks
│   ├── app/
│   │   ├── hooks/
│   │   │   └── session_hooks.py    ← ADK callbacks (trim history, anomaly trigger)
│   │   └── mcp/
│   │       └── client.py           ← loads *://agent-guide from all MCP servers
│   └── config/
│       └── mcp_servers.yml         ← which MCP servers to connect

health_mcp/
├── resources/
│   ├── AGENT.md                    ← Layer 2 for health domain (served as wcnp://agent-guide)
│   └── GRAPH_RENDERING.md          ← Layer 2 supplement (served as wcnp-graphs://agent-guide)
└── src/prompts/
    └── wcnp.py                     ← Layer 3 prompts (15 use cases)

maof-dependency-agent/
├── resources/
│   └── AGENT.md                    ← Layer 2 for dependency domain (served as dependency://agent-guide)
└── src/mcp_server/
    └── resources_and_prompts.py    ← Layer 3 dependency prompts

<future-mcp>/
├── resources/
│   └── AGENT.md                    ← Layer 2 for new domain (must end with ://agent-guide)
└── src/prompts/
    └── <domain>.py                 ← Layer 3 for new use cases
```
