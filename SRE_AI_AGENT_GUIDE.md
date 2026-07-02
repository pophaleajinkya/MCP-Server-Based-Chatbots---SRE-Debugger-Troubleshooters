# SRE AI Agent — Simple Guide

This document explains the **SRE AI agent system** in this repository: what it is, how the pieces connect, how a question travels through the system, and what each major part does. The wording is kept plain on purpose.

---

## Summary

**What it is**

The SRE AI agent is an **assistant that helps Site Reliability Engineers (SREs) and DevOps engineers** understand what is going wrong with applications running on **WCNP** (Walmart’s Kubernetes-style cloud platform). You ask questions in normal English—for example about CPU, memory, pods, latency, or dependencies—and the system pulls **live metrics and checks** (mostly from Prometheus and internal APIs) and explains the situation.

**How it thinks**

At the center is a **large language model (LLM)**. It does not “guess” infrastructure facts by itself. Instead it uses **tools** exposed through **MCP (Model Context Protocol) servers**: one stack focuses on **health and metrics**, another on **service dependencies**. The LLM decides **which tool to call and when**, following built-in rules and guides so answers stay accurate and consistent.

**What you use day to day**

Most people interact through **`sre-ai-ui`**, a web chat app. That app talks to a backend **`super-agent`** service over a standard called **A2A (Agent-to-Agent)**. The backend connects to MCP servers, Redis, and the LLM—details below.

---

## Architecture (Big Picture)

Think of traffic flowing **from the user’s browser → UI server → agent backend → tools & data → back as text (and sometimes charts)**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  User (browser)                                                          │
│  Types a question in the SRE AI chat UI                                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  sre-ai-ui (Next.js)                                                     │
│  • Chat pages, agent picker, optional PingFederate (SSO) login          │
│  • Forwards the message to the configured agent URL (A2A)                 │
│  • Can stream replies (SSE) for a live typing / events experience        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │  HTTP: A2A JSON-RPC
                                │  (e.g. /a2a or /a2a/stream)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  super-agent (Python / FastAPI) — the “Health Agent” backend              │
│  • Google ADK: runs the LLM in a loop (reason → call tools → reply)      │
│  • Loads MCP tools from connected servers (health, dependency, …)        │
│  • Uses Redis for sessions / conversation state                           │
│  • Optionally calls **remote A2A agents** for delegated sub-tasks         │
└───────────────┬─────────────────────────────┬─────────────────────────────┘
                │                             │
                ▼                             ▼
┌──────────────────────────┐    ┌────────────────────────────────────────┐
│  MCP: health / metrics   │    │  MCP: dependency graph                  │
│  (e.g. health-mcp)       │    │  (e.g. maof-dependency-agent /          │
│  Checks, PromQL, charts  │    │   dependency-mcp)                        │
└──────────────┬───────────┘    └────────────────┬───────────────────────┘
                 │                                │
                 └────────────┬───────────────────┘
                              ▼
                 ┌────────────────────────┐
                 │  Prometheus, Grafana,  │
                 │  K8s topology, etc.     │
                 │  (real production data)  │
                 └────────────────────────┘
```

**One-line takeaway:** the **UI** is the front door; **super-agent** is the brain’s **control room**; **MCP servers** are the **hands** that run checks and fetch data; the **LLM** is the **planner and explainer**.

---

## Workflow (End to End)

1. **User opens the chat** (`sre-ai-ui`) and (in many environments) signs in with **PingFederate** so the app knows who they are and can pass safe identity/context headers to the backend.

2. **User picks an agent** (if multiple are configured via `ADK_AGENTS`) or uses the default. Each agent entry has a **name** and **URL** pointing at an A2A endpoint (for example `…/a2a`).

3. **User sends a message.** The UI calls the backend route (`/api/chat` or streaming `/api/chat/stream`). The UI builds an **A2A JSON-RPC** request (`message/send` or `message/stream`) and sends it to the agent’s URL.

4. **super-agent receives the task.** It ties the request to a **session** (often stored in **Redis**) so follow-up questions remember context.

5. **The ADK runner runs the LLM** with:
   - a short **system instruction** (who the agent is and how it must behave),
   - longer **guides** loaded from MCP **resources** (like `AGENT.md`) at startup,
   - **tool definitions** from every connected MCP server.

6. **The model chooses actions.** For most questions it **calls MCP tools** (health checks, dependency lookups, charts, prompts) instead of inventing numbers. It may fetch **on-demand prompts** (workflow templates) for tricky scenarios so PromQL and steps stay correct.

7. **MCP servers execute** queries and checks against real systems and return **structured JSON**. Chart-capable paths can return data the UI renders as **graphs** (via streamed events).

8. **The LLM turns results into an answer** for the human: status, likely cause, links (e.g. Grafana), and next steps. The UI displays the streamed or final text (and charts when provided).

9. **Optional:** If **remote A2A agents** are configured, super-agent can **delegate** a whole sub-task to another agent (another LLM + tools) and merge that answer—useful when different teams own different capabilities.

---

## Components (What Each Part Does)

### 1. `sre-ai-ui` (the chat frontend)

- **Role:** The website SREs use to talk to the agent.
- **Tech:** Next.js, React.
- **Important behaviors:**
  - Reads **agent list** from environment (`ADK_AGENTS` JSON, or a fallback URL).
  - Sends chat to the backend agent using the **A2A** client (`sendA2AQuery`, streaming routes).
  - Handles **authentication** (PingFederate / session cookies) and can forward **user context** (e.g. timezone) so the agent interprets times like “this morning” correctly.
- **Why it matters:** Without it, you would only use `curl` or custom clients; this is the polished entry point.

### 2. A2A (Agent-to-Agent protocol)

- **Role:** A **standard way** for apps to send tasks to an agent and get back status, artifacts, and streaming events.
- **In this repo:** The UI calls endpoints such as **`/a2a`** (request/response) or **`/a2a/stream`** (SSE streaming). Payloads use **JSON-RPC** methods like `message/send` and `message/stream`.
- **Why it matters:** The UI does not need to know Python or ADK internals—only the **HTTP contract**. The same agent URL could be used by other tools that speak A2A.

### 3. `super-agent` (main backend agent)

- **Role:** The **primary SRE AI agent service** described in `super-agent/README.md`: connects MCP servers, runs the LLM loop, exposes `/health`, `/a2a/stream`, sessions APIs, etc.
- **Tech:** FastAPI, **Google ADK** (`Runner`, `A2aAgentExecutor`), Redis-backed sessions.
- **Important behaviors:**
  - On startup, connects to MCP servers (from Redis config in prod or a **local YAML** file for dev).
  - Builds the agent with **`make_agent`**: merges instructions with **guides** from MCP resources.
  - Surfaces **tools** so the LLM can call health checks, dependency fetches, charts, and `get_mcp_prompt`-style helpers.
- **Why it matters:** This is where **orchestration** lives—the LLM decides the sequence; this service provides the runtime, wiring, and safety gates.

### 4. Three layers of “intelligence” (how knowledge is organized)

The repo’s architecture doc splits knowledge so **token cost stays lower** and **new scenarios can be added without rewriting the agent core**:

| Layer | What it is | Analogy |
| --- | --- | --- |
| **Layer 1 — Short instruction** | A tiny **always-on** block: “you are a health/dependency assistant; **use tools immediately**; follow the guides.” | The agent’s **ID card and ground rules**. |
| **Layer 2 — MCP guides (`AGENT.md` resources)** | Loaded **once at startup**: routing tables (“if the user asks about latency, use this prompt/tool path”), cross-service rules, when to fetch dependencies. | The **table of contents + playbooks index**. |
| **Layer 3 — MCP prompts** | Loaded **only when needed**: detailed steps, exact query patterns, thresholds for one scenario (e.g. full triage, Istio latency). | **Recipe cards** for specific incidents. |

**Junior-friendly summary:** Layer 1 keeps behavior consistent; Layer 2 tells the model **which playbook** applies; Layer 3 is the **actual playbook steps** so metric names and logic stay correct.

### 5. MCP servers (health vs dependency)

- **Role:** **Plugins** that expose **tools**, **resources** (guides), and **prompts** over MCP.
- **Health-oriented MCP (e.g. health-mcp):** Runs parallel checks (CPU, memory, restarts, Istio signals, secrets, rollouts, …), talks to **Prometheus**, can build **charts**.
- **Dependency MCP (e.g. maof-dependency-agent side):** Answers “what depends on what” — **upstream/downstream** graphs for WCNP or other app types, merged from topology APIs and databases as implemented.
- **Why it matters:** The LLM should never hardcode every metric name; MCP owners **own their domain** and ship updates independently.

### 6. Redis

- **Role:** **Session and conversation state** (and in production, MCP server configuration keys).
- **Local dev note:** You can point MCP connection settings at a **YAML file** instead of Redis for server lists, but sessions typically still use Redis.
- **Why it matters:** Makes multi-turn chat **stateful** and supports scaling out the agent service.

### 7. LLM gateway

- **Role:** The **hosted API** the agent calls to run the model (Claude/OpenAI-style gateways as configured in `.env`).
- **Why it matters:** Centralizes **auth, routing, and rate limits** for enterprise use.

### 8. Remote A2A agents (optional)

- **Role:** Other services that expose **`/.well-known/agent.json`** and **`POST /a2a`**. Super-agent can treat them as **tools**: “ask this other agent for a specialized answer.”
- **Why it matters:** Lets you **compose** agents (e.g. a dedicated incident bot) without cramming every skill into one codebase.

### 9. Supporting repos in this workspace (context)

- **`maof-dependency-agent`:** Dependency data path and related MCP/agent code paths used with the health story.
- **Other `*_mcp` folders:** Additional MCP servers that can be plugged in where the deployment wires them.

These are **not** all required for every demo, but they show how the **ecosystem** grows: new MCP = new tools for the same agent pattern.

---

## Mental Model for On-Call

1. **You ask in plain language.**
2. The **UI** delivers the message via **A2A**.
3. **super-agent** runs the **LLM** with rules + guides.
4. The LLM **calls MCP tools** to get **truth from metrics/systems**.
5. You get back **explanations, statuses, links, and sometimes charts**—not guesswork.

If something looks wrong, check **agent URL config**, **MCP connectivity** (`/health`), **Redis**, and **LLM gateway credentials** before blaming “the model”—most failures are **wiring or data access**, not “AI magic.”

---

## Where to Read More in This Repo

| Topic | Location |
| --- | --- |
| Deeper architecture (layers, token costs, examples) | `super-agent/docs/architecture.md` |
| Running the backend agent | `super-agent/README.md` |
| Running the chat UI | `sre-ai-ui/README.md` |
| Onboarding a new A2A subagent | `super-agent/docs/onboarding/a2a-agent-onboarding.md` |
| Agent behavior / system prompts | `super-agent/resources/AGENT_INSTRUCTION.md` |

---

*This guide is an overview for learning. For deployment-specific URLs, credentials, and cluster names, follow your team’s internal runbooks.*
