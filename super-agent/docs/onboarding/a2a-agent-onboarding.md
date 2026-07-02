# A2A Agent Onboarding Guide

How to build a subagent that super-agent can discover and orchestrate via the
A2A 0.3 (Agent-to-Agent) protocol.

---

## Overview

```
  User request
       │
       ▼
  super-agent  (orchestrator)
       │  POST {url}/a2a  JSON-RPC message/send
       ▼
  Your A2A Agent  ──►  your own MCP servers / tools / LLM
       │
       ▼
  Returns text response → super-agent weaves into its final answer
```

Unlike MCP servers (which expose individual **tools**), an A2A subagent is a
**complete agent** with its own LLM, session, and tool loop. super-agent
delegates entire sub-tasks to it — the subagent handles them independently and
returns a final answer.

---

## 1. What your A2A agent must expose

### Required: `POST /a2a`

The A2A 0.3 JSON-RPC endpoint. Accepts `message/send` (non-streaming) and
optionally `message/stream` (streaming SSE).

### Required: `GET /.well-known/agent.json`

The **Agent Card** — a JSON document describing your agent's identity and
capabilities. super-agent fetches this at startup to auto-configure the
FunctionTool it uses to delegate tasks to you.

---

## 2. The Agent Card (`/.well-known/agent.json`)

This is the most important file for onboarding. super-agent reads it at startup
and uses `description` + `skills` to build the LLM tool prompt.

**Minimal valid Agent Card:**
```json
{
  "name": "sre-agent",
  "description": "SRE incident analysis agent. Handles on-call alerts, runbook execution, and post-incident reports for WCNP services.",
  "version": "1.0.0",
  "url": "https://sre-agent.stage.walmart.com",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "incident_triage",
      "name": "Incident Triage",
      "description": "Analyzes an active incident given a namespace or alert name. Returns root cause, severity, and recommended actions."
    },
    {
      "id": "runbook_execution",
      "name": "Runbook Execution",
      "description": "Executes a named runbook step-by-step (e.g. 'restart-pods', 'scale-deployment')."
    },
    {
      "id": "post_incident_report",
      "name": "Post-Incident Report",
      "description": "Generates a structured post-incident report from a session or incident ID."
    }
  ],
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"]
}
```

**How super-agent uses the Agent Card:**

1. `description` → becomes the FunctionTool docstring — the LLM reads this to
   decide WHEN to delegate to your agent.
2. `skills[].id` + `skills[].description` → appended to the tool description
   as a capability list so the LLM knows exactly what sub-tasks to send you.

> **Tip:** Write `description` like a tool docstring — be specific about what
> input your agent expects and what it returns. Vague descriptions cause the
> LLM to never (or always incorrectly) delegate.

---

## 3. The A2A endpoint (`POST /a2a`)

### Request format — `message/send`

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        { "type": "text", "text": "Triage the alert firing for namespace iro-prod" }
      ],
      "messageId": "550e8400-e29b-41d4-a716-446655440000"
    },
    "configuration": {
      "sessionId": "optional-session-id-for-multi-turn"
    }
  }
}
```

### Response format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "task-uuid",
    "status": {
      "state": "completed",
      "message": null
    },
    "artifacts": [
      {
        "parts": [
          {
            "type": "text",
            "text": "Root cause: OOM in pod item-assembler-async-xxxx. Recommendation: scale up memory limit from 2Gi to 4Gi. See runbook: https://..."
          }
        ]
      }
    ]
  }
}
```

**Task states:**
- `submitted` → received, not yet started
- `working` → agent is processing
- `completed` → done, check `artifacts` for the response
- `failed` → error, check `status.message`

---

## 4. Using Google ADK (recommended)

The fastest way to build a compatible A2A agent is with **Google ADK 1.28.x**
and **`A2AStarletteApplication`** — it generates the `/a2a` endpoint AND
`/.well-known/agent.json` automatically.

```python
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

agent_card = AgentCard(
    name="sre-agent",
    description="SRE incident analysis agent. Handles on-call alerts, runbook execution ...",
    url="https://sre-agent.stage.walmart.com",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    skills=[
        AgentSkill(
            id="incident_triage",
            name="Incident Triage",
            description="Analyzes an active incident given a namespace or alert name.",
        ),
        AgentSkill(
            id="runbook_execution",
            name="Runbook Execution",
            description="Executes a named runbook step-by-step.",
        ),
    ],
    defaultInputModes=["text/plain"],
    defaultOutputModes=["text/plain"],
)

executor = A2aAgentExecutor(runner=runner)  # your ADK Runner
handler  = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
a2a_app  = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)

# Mount on your FastAPI app
app.mount("/", a2a_app.build())
# ↑ This mounts BOTH:
#     POST /.well-known/agent.json  ← Agent Card
#     POST /a2a                     ← message/send endpoint
```

---

## 5. Register with super-agent

### Local development

1. Start your A2A agent (e.g. on port 8002):
   ```bash
   uvicorn main:app --port 8002
   ```

2. Create/edit `a2a_agents.yml`:
   ```yaml
   a2a_agents:
     - name: sre_agent
       url: http://localhost:8002
       enabled: true
       description: ""   # leave empty → auto-fetched from /.well-known/agent.json
       headers: {}
   ```

3. Add to `.env`:
   ```
   AGENT_ENV=local
   A2A_AGENTS_FILE=./a2a_agents.yml
   ```

### Non-local environments (dev / stage / prod)

Write a JSON array to Redis at:
```
super_agent:config:a2a_agents:<AGENT_ENV>:<AGENT_GROUP>:config
```

Example:
```bash
redis-cli SET "super_agent:config:a2a_agents:stage:sre:config" '[
  {
    "name": "sre_agent",
    "url": "https://sre-agent.stage.walmart.com",
    "enabled": true,
    "description": "",
    "headers": {}
  }
]'
```

> **Note:** Unlike MCP servers, A2A subagents are **optional** — an empty
> Redis key is fine. super-agent starts without them and logs a notice.

---

## 6. How super-agent calls your agent

When the orchestrator LLM decides to delegate a task, super-agent calls
`make_remote_agent_tool` which sends:

```
POST {url}/a2a
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "type": "text", "text": "<user query or sub-task>" }],
      "messageId": "<uuid>"
    },
    "configuration": {
      "sessionId": "<current session id>"   ← passed when available
    }
  }
}
```

It waits up to **120 seconds** for your agent to respond, then extracts:
```
response.result.artifacts[0].parts[0].text
```

---

## 7. Authentication

Pass auth headers in the Redis / YAML config:
```json
{
  "name": "sre_agent",
  "url": "https://sre-agent.stage.walmart.com",
  "enabled": true,
  "headers": {
    "Authorization": "Bearer <service-account-token>",
    "X-Internal-Service": "super-agent"
  }
}
```

These headers are forwarded on every `POST /a2a` call.

---

## 8. Session continuity

The `sessionId` in `configuration` allows your agent to maintain conversation
context across multiple turns in the same user session. If your agent is
stateless (single-turn), you can ignore it.

If you use **ADK + Redis session storage**, sessions are managed automatically —
just ensure your ADK Runner is configured with a `RedisSessionService`.

---

## 9. Skills — best practices

The `skills` array is what tells the orchestrator LLM what sub-tasks to route
to your agent. Write each skill description from the LLM's perspective:

| Bad ❌ | Good ✅ |
|---|---|
| "Does incident stuff" | "Analyzes an active PagerDuty/WCNP alert given a namespace or alert name. Returns root cause, severity, and recommended next actions." |
| "Runs runbooks" | "Executes a specific operational runbook by name (e.g. 'restart-pods', 'drain-node'). Accepts the runbook name and target namespace." |
| "Reports" | "Generates a Markdown post-incident report from a session ID or incident description. Includes timeline, impact, root cause, and action items." |

---

## 10. Response size guidance

super-agent passes your entire response text back to the orchestrator LLM.
Keep responses concise and structured:

- ✅ Return key findings + recommendations (< 2000 chars ideal)
- ✅ Use Markdown for structure — the UI renders it
- ❌ Don't return raw Prometheus data dumps — summarise them
- ❌ Don't return binary/base64 content — use resource URIs instead

---

## 11. Health check endpoint (recommended)

Expose `GET /health`:
```json
{
  "status": "ok",
  "agent": "sre-agent",
  "version": "1.0.0"
}
```

---

## 12. Common pitfalls

| Problem | Cause | Fix |
|---|---|---|
| Agent never called | Vague skill descriptions | Rewrite skills to be specific about input/output |
| Agent Card returns 404 | Not serving `/.well-known/agent.json` | Mount `A2AStarletteApplication` — it auto-serves the card |
| Timeout errors | Agent runs long tool chains | Increase timeout in Redis config (default 120s is usually enough) |
| Empty response | Artifacts missing in response | Ensure `result.artifacts[0].parts[0].text` is populated |
| Wrong session | Session ID mismatch | Pass `sessionId` from `configuration.sessionId` to your ADK Runner |
