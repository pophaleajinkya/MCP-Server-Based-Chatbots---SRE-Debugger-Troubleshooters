# Multi-Agent Session Management Guide

## Table of Contents
1. [How Agents Get Sessions](#1-how-agents-get-sessions)
2. [Why Each Agent's Own Session Is Useful](#2-why-each-agents-own-session-is-useful)
3. [Chaining Sub-Agents (Pass Agent 1 Response → Agent 2)](#3-chaining-sub-agents-pass-agent-1-response--agent-2)
4. [Carrying Context Across Agent Calls (Real Example)](#4-carrying-context-across-agent-calls-real-example)

---

## 1. How Agents Get Sessions

### The Session Flow: Frontend → Orchestrator → Sub-Agents

```
Frontend (Browser / SRE-AI UI)
│
│  POST /query  { session_id: "sess-abc", query: "health of intlsre?" }
│
▼
health-agent (Orchestrator)
│  Redis Key: adk:session:health_agent:admin:sess-abc
│  Stores:    full conversation history
│
│  Calls sub-agent → derives session_id = "sess-abc::call_anomaly_agent"
│
▼
anomaly-agent (Remote Sub-Agent)
   Redis Key: adk:session:anomaly_agent:admin:sess-abc::call_anomaly_agent
   Stores:    only the sub-queries delegated to it by the orchestrator
```

### Where Does `session_id` Come From?

| Layer | Who creates it | How |
|---|---|---|
| **Frontend** | Browser / UI | Generates a UUID per conversation e.g. `"sess-abc"`. Sends it on every request in the same chat. |
| **Orchestrator** | ADK Runner | Receives `session_id` from the frontend. Creates a Redis session if it doesn't exist. |
| **Sub-Agent** | `make_remote_agent_tool` | Derives `"{root_session_id}::{agent_name}"` automatically from `ToolContext`. No manual work needed. |

### Key Rule

> **The frontend owns the root `session_id`.
> The orchestrator owns its conversation session.
> Each sub-agent owns a derived session scoped to itself.**
> Nobody shares Redis. Nobody needs access to anyone else's Redis.

---

## 2. Why Each Agent's Own Session Is Useful

### The Problem It Solves: Follow-Up Questions

Consider this conversation:

```
Turn 1 ─────────────────────────────────────────────────────────────────
User:         "What is the health of intlsre namespace?"
Orchestrator: calls health-agent → "3 pods restarting, CPU at 90%"
              calls anomaly-agent → "no anomaly in the last 1 hour"
Answer:       "intlsre has pod restarts and high CPU. No signal anomaly."

Turn 2 ─────────────────────────────────────────────────────────────────
User:         "What was the anomaly threshold used?"
```

On Turn 2, the orchestrator calls `anomaly-agent` again with the **same derived session_id** `"sess-abc::call_anomaly_agent"`.

```
anomaly-agent Redis lookup:
  key = adk:session:anomaly_agent:admin:sess-abc::call_anomaly_agent
  found! → previous sub-conversation:
    [Q: "check intlsre for last 1hr", A: "no anomaly, threshold=2σ"]

anomaly-agent now KNOWS the context → answers: "Threshold was 2 standard deviations"
```

Without its own session, the anomaly-agent would have no memory of what it computed in Turn 1.

### Session Lifecycle

```
New Conversation (new session_id from frontend)
  → All derived IDs are new → All sub-agents start fresh ✅

Same Conversation (same session_id)
  → Same derived IDs → Each sub-agent has its own history ✅

Different User (different user_id, same session_id)
  → Redis key includes user_id → Completely isolated ✅
```

---

## 3. Chaining Sub-Agents (Pass Agent 1 Response → Agent 2)

### The Pattern: Orchestrator as Pipeline

The orchestrator LLM is the **router and aggregator**. It calls Agent 1, receives the response into its context, then uses that response when calling Agent 2.

```
User: "Check health of intlsre AND correlate with signal-api anomalies"

Orchestrator LLM context window:
│
├── [TOOL CALL]  call_health_agent("check intlsre namespace health")
│       ↓
│   [TOOL RESULT] "3 pods restarting, namespace=intlsre, deployment=signal-api affected"
│
├── [TOOL CALL]  call_anomaly_agent("check signal-api in intlsre for anomalies")
│       ↑
│       └── LLM extracted namespace=intlsre and deployment=signal-api from Agent 1's result
│       ↓
│   [TOOL RESULT] "Anomaly detected: P95 latency spike at 14:32 UTC"
│
└── FINAL ANSWER: "intlsre has 3 restarting pods. signal-api shows a latency anomaly
                   at 14:32 UTC which correlates with the pod restarts."
```

### How the Orchestrator Instruction Enables This

Tell the orchestrator LLM explicitly what to do with intermediate results:

```python
root_agent = Agent(
    model=_llm,
    name="health_orchestrator",
    instruction="""
    You are a WCNP health orchestrator. When answering questions:

    1. Use call_health_agent for namespace and pod health checks.
    2. Use call_anomaly_agent for signal API and metric anomaly detection.
    3. IMPORTANT: When calling call_anomaly_agent after call_health_agent,
       ALWAYS include the namespace and deployment name extracted from the
       health check response in your query to call_anomaly_agent.
    4. Synthesise all agent responses into a single final answer.
    """,
    tools=[
        call_health_agent_tool,
        call_anomaly_agent_tool,
        *_mcp_tools,
    ],
)
```

### Sequential vs Parallel Calls

```python
# Sequential (default LLM behaviour — uses Agent 1 result to inform Agent 2)
User: "health + anomaly for intlsre"
  → LLM calls health_agent first
  → reads result
  → calls anomaly_agent WITH namespace extracted from health result

# Parallel (when results are independent — use ParallelAgent)
User: "health of intlsre AND health of payments namespace"
  → Both health checks are independent → can run simultaneously
  → Use ParallelAgent wrapping two health sub-agents
```

---

## 4. Carrying Context Across Agent Calls (Real Example)

### Scenario

```
Turn 1:
  User:    "What is the health of intlsre namespace?"
  Agent:   (calls health-agent)
           → "intlsre: 3 pods restarting, signal-api deployment at 90% CPU"

Turn 2:
  User:    "Get signal API anomaly"
  Agent:   needs to know:
             namespace  = intlsre      ← from Turn 1
             deployment = signal-api   ← from Turn 1
```

### Why This Works Automatically

The orchestrator has **full conversation history** in its Redis session. On Turn 2, the ADK runner loads the entire history into the LLM context window:

```
LLM Context on Turn 2:
─────────────────────────────────────────────
[Turn 1 - User]    "What is the health of intlsre namespace?"
[Turn 1 - Tool]    call_health_agent → "intlsre: 3 pods, signal-api at 90% CPU"
[Turn 1 - Agent]   "intlsre has pod restarts and high CPU on signal-api"
─────────────────────────────────────────────
[Turn 2 - User]    "Get signal API anomaly"          ← new input
```

The LLM sees `namespace=intlsre` and `deployment=signal-api` from Turn 1. When it calls `call_anomaly_agent`, it formulates:

```
call_anomaly_agent(
  query = "Check for anomalies in signal-api deployment in intlsre namespace"
           ↑ namespace and deployment extracted from Turn 1 context automatically
)
```

### What the Anomaly Agent Receives

```
POST https://anomaly-agent.dev.walmart.com/a2a
{
  "method": "tasks/send",
  "params": {
    "sessionId": "sess-abc::call_anomaly_agent",
    "message": {
      "role": "user",
      "parts": [{
        "type": "text",
        "text": "Check for anomalies in signal-api deployment in intlsre namespace"
      }]
    }
  }
}
```

The anomaly agent receives a **fully-formed, self-contained question**. It does not need to know about Turn 1 — the orchestrator has already extracted the relevant context and embedded it in the query.

### Turn 3: Follow-Up to the Anomaly Agent Itself

```
Turn 3:
  User:   "What was the time window you checked?"
```

Now the orchestrator calls `call_anomaly_agent` again. Same derived session_id `"sess-abc::call_anomaly_agent"`. The anomaly agent loads ITS OWN history:

```
Anomaly-Agent Redis: sess-abc::call_anomaly_agent
  [Q: "Check signal-api anomalies in intlsre"]
  [A: "Anomaly detected: P95 latency spike at 14:32, checked last 3 hours"]
```

Anomaly agent answers: `"I checked the last 3 hours of signal-api metrics"` — without the orchestrator needing to repeat the full context.

---

## Summary: Three Context Mechanisms Working Together

```
┌────────────────────────────────────────────────────────────────────────┐
│ Mechanism 1: Orchestrator Redis (full conversation)                     │
│                                                                         │
│   Enables: Turn 2 question knows about Turn 1 answer                   │
│   How: ADK loads full history into LLM context window on every turn    │
│   Owner: health-agent's Redis                                           │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ Mechanism 2: LLM Context Window (in-flight reasoning)                   │
│                                                                         │
│   Enables: Agent 1 result embedded in Agent 2 query (chaining)         │
│   How: LLM sees all tool results in same turn, extracts relevant info  │
│   Owner: Orchestrator LLM (ephemeral, per request)                     │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ Mechanism 3: Sub-Agent Derived Session (sub-agent memory)               │
│                                                                         │
│   Enables: Anomaly agent remembers its own previous computations       │
│   How: Stable derived session_id = "{root_session}::{agent_name}"      │
│   Owner: Each sub-agent's own Redis                                     │
└────────────────────────────────────────────────────────────────────────┘
```

### Decision Guide

| Scenario | Mechanism to use |
|---|---|
| User follow-up references previous answer | Mechanism 1 (orchestrator history) — automatic |
| Agent 2 needs Agent 1's output in same turn | Mechanism 2 (LLM context window) — automatic |
| User asks follow-up about what sub-agent computed | Mechanism 3 (sub-agent session) — automatic via derived session_id |
| Need to pass namespace/deployment to next agent | Mechanism 2 — orchestrator LLM extracts and includes it in the query |
| New conversation, clean slate | New `session_id` from frontend — all three reset automatically |

**No manual wiring needed for any of these.** The session derivation in `make_remote_agent_tool`, the ADK Redis session service, and the LLM's context window handle all three mechanisms automatically.
