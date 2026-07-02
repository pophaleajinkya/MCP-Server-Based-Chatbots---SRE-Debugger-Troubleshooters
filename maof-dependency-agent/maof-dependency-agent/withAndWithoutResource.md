# MCP Resources: With vs Without `dependency://agent-guide`

## How `dependency://agent-guide` Works — The Key Insight

> Without the guide, the LLM has to infer routing logic from individual tool descriptions at call time.
> With the guide loaded upfront, it already knows the full decision tree before the user even asks a question — faster, more reliable routing.

---

## Layer 1: How LLMs Pick Tools (The Mechanics)

When an LLM decides which tool to call, it reads the **tool name + description** from the MCP `tools/list` response. For 9 tools, that's 9 mini-descriptions loaded into context.

The LLM then does implicit reasoning like:

> *"The user said 'namespace' — that sounds like Kubernetes — the tool `fetch_wcnp_upstream_dependencies` mentions namespace in its params — probably this one."*

This works. But it's **probabilistic pattern matching** on short strings.

---

## Layer 2: What Can Go Wrong Without the Guide

**Problem 1 — Ambiguity at the edges**

What if the user says *"get me the dependencies for iro-prod"* without specifying namespace or org? The LLM now has to guess: WCNP? OneOps? It might pick the wrong tool, get an error, backtrack — wasting tokens and time.

**Problem 2 — Missing pre-steps**

What if the user doesn't know the namespace? They'd need to call `list_apps_in_namespace` first, *then* call the dependency tool. Nothing in the tool description tells the LLM to do this two-step. Without the guide, it may skip straight to the dependency call and fail.

**Problem 3 — No global picture**

Each tool description is self-contained. None of them say *"if you're looking at managed services, use these 4 tools instead"*. The LLM has to synthesize that picture from 9 separate fragments — every single time, for every query.

---

## Layer 3: What the Resource Actually Contains

The `dependency://agent-guide` is a markdown file that gives the LLM:

1. **A decision tree** — "if the app lives in WCNP, use wcnp tools; if OneOps, use oneops tools; if managed service (Cassandra/CosmosDB/etc), use these specific tools"
2. **Required params per path** — so it knows upfront what to ask the user for
3. **Pre-step hints** — e.g. "if you don't have the namespace, call `list_apps_in_namespace` first"
4. **Direction semantics** — what upstream vs downstream means in this domain

This is **domain knowledge** that would otherwise be scattered or absent.

---

## Layer 4: The Timing Advantage

```
Without resource:
  User asks question
  → LLM reads 9 tool descriptions
  → LLM reasons about which applies
  → Maybe picks wrong one
  → Error → retry
  → Correct tool call

With resource loaded at session start:
  [Session init] → LLM reads guide once → full decision tree in context
  User asks question
  → LLM consults pre-loaded tree
  → Picks correct tool immediately
  → Done
```

The resource is loaded **before the user types anything**. By the time the query arrives, the routing is already understood — not computed.

---

## Layer 5: The Analogy

Think of it like a new employee vs a trained one.

- **Without guide**: new employee handed a list of phone extensions — figures out who to call by guessing from job titles.
- **With guide**: same employee given a runbook — *"if customer reports X, call dept A; if Y, call dept B"*. No guessing, just lookup.

The resource is your **runbook**. The LLM is the employee. Tools are the phone extensions.

---

## MCP Resources Are NOT Routes

**HTTP routes** respond to requests at runtime — every call triggers execution.

**MCP Resources** are more like **static knowledge blobs** that an agent client *can* read. Whether and when they're read depends on the client implementation.

---

## How ADK Actually Uses Resources

```
ADK super-agent starts
    └── Connects to each MCP server in mcp_servers.yml
         └── Calls resources/list  ← discovers what resources exist
              └── (optionally) Calls resources/read for each resource
                   └── Injects content into the agent's system prompt / context
```

So the resource content ends up **in the LLM's context window** at session start — not called at query time.

---

## Three Ways Clients Treat Resources

| Client behavior | What happens |
|---|---|
| **Eager load** (ideal) | Reads all resources at startup, injects into system prompt |
| **On-demand** | Reads resource only when LLM explicitly decides to fetch it |
| **Ignore** | Client never calls resources/read — resource is unused |

ADK's behavior depends on its MCP client implementation. Most well-implemented ADK agents do eager loading for small resources like guides.

---

## The Correct Mental Model

```
Routes    → triggered by user/LLM at runtime, return dynamic data
Resources → loaded upfront, static knowledge, enrich the LLM's world model
Tools     → called by LLM at runtime, execute logic, return dynamic data
```

`dependency://agent-guide` is closer to a **system prompt addition** than a route.
It enriches what the LLM already knows before it starts answering questions.

---

## TL;DR

| | Without Resource | With Resource |
|---|---|---|
| Routing logic | Inferred at runtime from 9 tool docs | Pre-loaded decision tree |
| Wrong tool selection | Possible — short descriptions are ambiguous | Less likely — explicit routing rules |
| Multi-step workflows | LLM may skip pre-steps | Guide spells out required sequence |
| Managed service routing | LLM guesses from tool name patterns | Guide has the explicit mapping table |
| Per-query overhead | LLM reasons about routing every time | Routing knowledge already in context |

Resources are **read-only knowledge blobs** loaded at session start — not triggered per query like routes are.
