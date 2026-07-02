# MCP Server Onboarding Guide

How to build, register, and maintain an MCP server that super-agent can orchestrate.

---

## Overview

```
  User request
       │
       ▼
  super-agent (orchestrator)
       │  calls tools via MCP JSON-RPC
       ▼
  Your MCP Server  ──►  your domain logic
  POST /mcp/
```

super-agent connects to your server at startup, loads all your **tools**, **resources**,
and **prompts**, and injects them into its orchestrator LLM. The LLM decides autonomously
when to call your tools based on the tool descriptions you provide.

---

## 1. What your MCP server must expose

### Required: `POST /mcp/`

The main MCP endpoint — accepts JSON-RPC 2.0 messages over **Streamable HTTP**
(default) or **SSE** transport.

**Mandatory JSON-RPC methods:**

| Method | Purpose |
|---|---|
| `initialize` | Handshake — returns server name, version, and capabilities |
| `tools/list` | Returns all available tools with input schemas |
| `tools/call` | Executes a tool by name with arguments |

**Optional but strongly recommended:**

| Method | Purpose |
|---|---|
| `resources/list` | Lists data resources (e.g. guides, documents) |
| `resources/read` | Returns the content of a named resource |
| `prompts/list` | Lists reusable workflow prompt templates |
| `prompts/get` | Renders a prompt template with arguments |

---

## 2. Tool definition format

Each tool in `tools/list` must follow this schema:

```json
{
  "name": "my_tool_name",
  "description": "Clear, specific description of what this tool does and WHEN to use it. The orchestrator LLM reads this to decide which tool to call.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "namespace": {
        "type": "string",
        "description": "The Kubernetes namespace to inspect (e.g. 'iro-prod')"
      },
      "limit": {
        "type": "integer",
        "description": "Max results to return. Defaults to 10 if not provided."
      }
    },
    "required": ["namespace"]
  }
}
```

**Critical rules for tool schemas (Anthropic/Claude compatibility):**

- Top-level `type` MUST be `"object"` — never `"array"` or `"string"`
- Do NOT use `"default"` inside `inputSchema` — Anthropic rejects it
- Do NOT use `"$ref"`, `"definitions"`, or `"$schema"` — use inline schemas
- Do NOT use `"if"` / `"then"` / `"else"` — conditional schemas are rejected
- Tool names must be unique across ALL MCP servers connected to super-agent

---

## 3. The agent guide resource (strongly recommended)

Expose a resource at URI `<scheme>://agent-guide` — super-agent auto-discovers
any resource whose URI ends with `://agent-guide` and injects it into the LLM's
system prompt.

**Convention:**
```
URI: wcnp://agent-guide   (or  sre://agent-guide, deploy://agent-guide, etc.)
```

The guide should contain:
- Domain routing rules (which tool handles which scenario)
- Prompt template names and when to call them
- Important constraints (e.g. "NEVER guess PromQL metric names")
- Any domain terminology the LLM needs to know

**Example guide structure:**
```markdown
## Tool Routing

### Namespace health
- Use `check_namespace_health` when the user asks about pod status, restarts, CPU/memory
- Required arg: `namespace` — extract from the user's message
- Returns: JSON health report — parse the `status` field first

### Prometheus queries
- ALWAYS call `get_mcp_prompt('wcnp-promql-guide')` BEFORE writing any PromQL
- Metric names are EXACT — one wrong character returns empty results

## Prompt Templates
| Name | When to use |
|---|---|
| wcnp-full-triage | User reports an outage or degradation |
| wcnp-promql-guide | Before any Prometheus query |
```

---

## 4. Prompt templates

Prompts let you pre-package domain workflows that the agent loads on demand.

```
GET prompts/list  →  [ { "name": "wcnp-full-triage", "description": "..." }, ... ]
GET prompts/get   →  rendered markdown instructions for the use case
```

The agent calls `get_mcp_prompt("wcnp-full-triage", {"namespace": "iro-prod"})`
which renders your template with arguments and returns structured instructions.

---

## 5. Register with super-agent

### Local development

1. Start your MCP server (default port 8999):
   ```bash
   uvicorn main:app --port 8999
   ```

2. Create/edit `a2a_agents.yml` (copy from `mcp_servers.yml.example`):
   ```yaml
   servers:
     - name: my-mcp-server
       url: http://localhost:8999/mcp/
       transport: streamable_http
       enabled: true
       description: "What this server does"
       headers: {}
   ```

3. Add to `.env`:
   ```
   AGENT_ENV=local
   MCP_SERVERS_FILE=./mcp_servers.yml
   ```

### Non-local environments (dev / stage / prod)

Register by writing a JSON array to Redis at:
```
super_agent:config:mcp_servers:<AGENT_ENV>:<AGENT_GROUP>:config
```

Example:
```bash
redis-cli SET "super_agent:config:mcp_servers:stage:sre:config" '[
  {
    "name": "my-mcp-server",
    "url": "https://my-mcp-server.stage.walmart.com/mcp/",
    "transport": "streamable_http",
    "enabled": true,
    "description": "What this server does",
    "headers": {}
  }
]'
```

> **Note:** MCP servers are **required** — if any registered server fails to
> connect, super-agent aborts startup. Use `"enabled": false` to temporarily
> disable a server without removing it from Redis.

---

## 6. Transport options

| Transport | URL pattern | When to use |
|---|---|---|
| `streamable_http` | `/mcp/` | Default — recommended for all new servers |
| `sse` | `/mcp/sse` or `/sse` | Legacy — use only if your framework requires it |

---

## 7. Authentication / headers

Pass auth headers in the `headers` map:
```json
{
  "name": "my-mcp-server",
  "url": "https://my-server.walmart.com/mcp/",
  "transport": "streamable_http",
  "enabled": true,
  "headers": {
    "Authorization": "Bearer <token>",
    "X-Api-Key": "<key>"
  }
}
```

---

## 8. Health check endpoint (recommended)

Expose `GET /health` returning:
```json
{
  "status": "ok",
  "tools": ["tool_a", "tool_b"],
  "version": "1.0.0"
}
```

super-agent's `/health` endpoint aggregates these — useful for monitoring.

---

## 9. Response format for tools

`tools/call` must return MCP `TextContent`:
```json
{
  "content": [
    {
      "type": "text",
      "text": "{ ... your JSON payload as a string ... }"
    }
  ],
  "isError": false
}
```

For rich UI rendering, include recognised keys in your JSON payload:

| Key | super-agent behaviour |
|---|---|
| `chart_data` | Renders a line/bar chart in the UI |
| `multi_chart_data` | Renders synchronised multi-panel chart |
| `table_data` | Renders paginated data table |
| `grafana_url` | Renders a live Grafana iframe panel |

---

## 10. Common pitfalls

| Problem | Cause | Fix |
|---|---|---|
| Tool never called | Description too vague | Make descriptions specific: "Use when user asks about X" |
| Empty PromQL results | Guessed metric name | Call `get_mcp_prompt` first; expose exact metric names |
| Startup aborted | Server unreachable | Check URL, firewall, SSL certs; use `enabled: false` to skip |
| Anthropic schema error | `default` in inputSchema | Remove all `default` keys from every tool schema |
| ADK template crash | `{var}` in agent guide | Replace `{var}` with `<var>` or escaped `{{var}}` |
