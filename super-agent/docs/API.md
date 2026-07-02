# A2A Health Agent — API Reference

Base URL (local): `http://localhost:8010`

Interactive docs: `http://localhost:8010/docs` (Swagger UI) · `http://localhost:8010/redoc`

---

## Table of Contents

- [Observability](#observability)
  - [GET /health](#get-health)
  - [GET /ready](#get-ready)
- [Agent](#agent)
  - [POST /query](#post-query)
  - [POST /query_api](#post-query_api)
- [Sessions](#sessions)
  - [GET /sessions](#get-sessions)
  - [GET /sessions/{session_id}/messages](#get-sessionssession_idmessages)
- [Debug](#debug)
  - [GET /debug/session/{session_id}](#get-debugsessionsession_id)
  - [GET /debug/llm](#get-debugllm)
- [MCP](#mcp)
  - [POST /mcp/validate](#post-mcpvalidate)
- [A2A (Agent-to-Agent)](#a2a-agent-to-agent)
  - [GET /.well-known/agent.json](#get-well-knownagentjson)
  - [POST /a2a](#post-a2a)
  - [POST /a2a/stream](#post-a2astream)

---

## Observability

### GET /health

Liveness check — returns service status, active LLM, and all connected MCP tools.

**Response `200`**

```json
{
  "status": "ok",
  "version": "2.0.0",
  "active_llm": "anthropic/claude-opus-4-6",
  "llm_endpoint": "https://...",
  "mcp_servers": [
    { "name": "wcnp-health-agent", "url": "https://..." }
  ],
  "mcp_tools": ["fetch_wcnp_namespace_health", "fetch_wcnp_latency_metrics", "..."]
}
```

**Example**

```bash
curl http://localhost:8010/health
```

---

### GET /ready

Kubernetes readiness probe. Returns `200` as soon as the server is up.

**Response `200`**

```json
{ "status": "ready" }
```

**Example**

```bash
curl http://localhost:8010/ready
```

---

## Agent

### POST /query

Submit a natural language query to the WCNP health agent. Runs the full ADK agentic loop (including multi-round MCP tool calls) and returns the final answer.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Natural language question (1–4096 chars) |
| `session_id` | string | no | Session ID for conversation continuity. Auto-generated UUID if omitted. |
| `user_id` | string | no | Caller identity. Also accepted via `loginId` or `wm_llm_gw.user_name` headers. Returns `422` if none supplied. |

**User identity resolution order**

1. `user_id` field in JSON body
2. `loginId` request header
3. `wm_llm_gw.user_name` request header

**Response `200`**

```json
{
  "response": "All pods in intl-sre are healthy...",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Example**

```bash
curl -X POST http://localhost:8010/query \
  -H 'Content-Type: application/json' \
  -H 'loginId: jane.doe@walmart.com' \
  -d '{
    "query": "Check health of namespace intl-sre",
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

---

### POST /query_api

Functionally identical to `POST /query`. Alternate entry point used by the MAOF platform integration. Accepts the same request body and returns the same response shape.

---

## Sessions

### GET /sessions

List all conversation sessions for a user, sorted newest first.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `user_id` | string | `admin` | User whose sessions to list |

**Response `200`**

```json
{
  "sessions": [
    {
      "session_id": "b5bddf59-cd55-45cd-9561-075efc412a39",
      "title": "Check health of namespace intl-sre",
      "last_update_time": 1773779504.689124,
      "user_id": "LB-lebron@Lab.Wal-Mart.com"
    }
  ]
}
```

On Redis error, returns `{ "sessions": [], "error": "session store temporarily unavailable" }`.

**Example**

```bash
curl 'http://localhost:8010/sessions?user_id=jane.doe@walmart.com'
```

---

### GET /sessions/{session_id}/messages

Return the ordered message history for a session, suitable for rendering in the UI.

**Path parameters**

| Parameter | Description |
|---|---|
| `session_id` | Session ID to fetch |

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `user_id` | string | `admin` | Owner of the session |

**Response `200`**

```json
{
  "session_id": "b5bddf59-...",
  "messages": [
    {
      "role": "user",
      "content": "Check health of namespace intl-sre",
      "timestamp": 1773779500.0
    },
    {
      "role": "assistant",
      "content": "All pods are healthy...",
      "timestamp": 1773779504.0,
      "tool_calls": [
        { "name": "fetch_wcnp_namespace_health", "args": { "namespace": "intl-sre" } }
      ]
    }
  ],
  "events": [ ... ]
}
```

`events` contains the raw SSE event log (type: `user` | `progress` | `complete`) used for exact UI replay. `tool_calls` on assistant messages lists every MCP tool invoked during that turn.

Returns `503` on Redis timeout.

**Example**

```bash
curl 'http://localhost:8010/sessions/b5bddf59-cd55-45cd-9561-075efc412a39/messages?user_id=jane.doe@walmart.com'
```

---

## Debug

> These endpoints are intended for local development and incident triage. Do not expose them publicly.

### GET /debug/session/{session_id}

Full raw dump of an ADK session from Redis — state, all ADK events (with tool call args and responses), and the UI event log.

**Path parameters**

| Parameter | Description |
|---|---|
| `session_id` | Session ID to inspect |

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `user_id` | string | `admin` | Owner of the session |

**Response `200`**

```json
{
  "session_id": "685307c8-f9cd-4281-80dc-e76164413716",
  "user_id": "LB-lebron@Lab.Wal-Mart.com",
  "last_update_time": 1773779313.74672,
  "title": "Check health of namespace intl-sre",
  "state": {
    "key": "value",
    "app:some_app_state": "...",
    "user:some_user_state": "..."
  },
  "event_count": 12,
  "tool_calls": [
    {
      "turn": 1,
      "call_id": "abc123",
      "tool": "fetch_wcnp_namespace_health",
      "args": { "namespace": "intl-sre" },
      "response": { "output": "..." },
      "ts_call": 1773779300.0,
      "ts_response": 1773779302.5
    }
  ],
  "adk_events": [ ... ],
  "ui_events": [ ... ]
}
```

State scopes are merged and prefixed: `app:` for app-scoped keys, `user:` for user-scoped keys, unprefixed for session-scoped keys.

**Errors**

| Code | Meaning |
|---|---|
| `404` | Session not found for the given user |
| `503` | Redis unavailable |

**Example**

```bash
curl 'http://localhost:8010/debug/session/685307c8-f9cd-4281-80dc-e76164413716?user_id=LB-lebron@Lab.Wal-Mart.com'
```

---

### GET /debug/llm

Returns current LLM configuration — provider, model, API base, extra headers (with secrets redacted), and Anthropic prompt caching status.

**Response `200`**

```json
{
  "provider": "anthropic",
  "model": "anthropic/claude-opus-4-6",
  "api_base": "https://...",
  "is_primary_llm": true,
  "extra_headers": {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "prompt-caching-2024-07-31"
  },
  "prompt_caching": {
    "beta_header_present": true,
    "beta_header_value": "prompt-caching-2024-07-31",
    "status": "HEADER_PRESENT — caching activates only when cache_control blocks are in messages",
    "note": "..."
  }
}
```

`api_key` and other secret-named headers are replaced with `<redacted>`.

**Prompt caching status values**

| Status | Meaning |
|---|---|
| `DISABLED` | `anthropic-beta` header not set — caching is off |
| `HEADER_PRESENT — ...` | Header is set; caching activates when `cache_control` blocks are present in messages |
| `N/A` | Non-Anthropic provider (Azure/OpenAI) |

**Example**

```bash
curl http://localhost:8010/debug/llm
```

---

## MCP

### POST /mcp/validate

Connects to any remote MCP server and validates all its Tools, Resources, and Prompts. Use before onboarding a new MCP server to catch schema issues that would cause Anthropic to reject the tool list at runtime.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Full URL of the MCP server endpoint |
| `transport` | `streamable_http` \| `sse` | no | Transport type. Default: `streamable_http` |
| `headers` | object | no | Additional HTTP headers (e.g. `Authorization`) |

**Response `200`**

```json
{
  "server_name": "wcnp-health-agent",
  "server_version": "1.0.0",
  "tools": [
    {
      "index": 0,
      "name": "fetch_wcnp_namespace_health",
      "description": "...",
      "status": "ok",
      "issues": [],
      "input_schema": { "type": "object", "properties": { ... } }
    }
  ],
  "resources": [],
  "prompts": [],
  "summary": {
    "tools_total": 5,
    "tools_ok": 4,
    "tools_warnings": 1,
    "tools_errors": 0,
    "resources_total": 0,
    "prompts_total": 0,
    "overall_status": "warning"
  }
}
```

**Tool validation checks**

| Check | Severity |
|---|---|
| `input_schema` not a dict | error |
| `input_schema` not JSON-serialisable | error |
| Missing or non-`object` top-level `type` (Anthropic requirement) | error |
| Legacy `definitions` key (use `$defs` in JSON Schema draft 2020-12) | error |
| Deprecated `id` / `$schema` keys | warning |

**Example**

```bash
curl -X POST http://localhost:8010/mcp/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://my-mcp-server.example.com/mcp",
    "transport": "streamable_http",
    "headers": { "Authorization": "Bearer my-token" }
  }'
```

---

## A2A (Agent-to-Agent)

These endpoints implement the [A2A protocol](https://github.com/google-a2a/A2A) for inter-agent communication with Wibey and other A2A-compatible clients.

### GET /.well-known/agent.json

Returns the Agent Card — the static discovery descriptor consumed by Wibey and other A2A clients. The `url` field is derived from the incoming request so it resolves correctly in any environment.

**Response `200`** — `AgentCard` object

```json
{
  "name": "A2A Health Agent",
  "description": "WCNP health intelligence agent...",
  "url": "http://localhost:8010/a2a",
  "version": "2.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "authentication": { "schemes": [] },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    { "id": "wcnp-namespace-health", "name": "WCNP Namespace Health", ... },
    { "id": "wcnp-latency-analysis", "name": "Latency Analysis", ... },
    { "id": "wcnp-deployment-info", "name": "Deployment Information", ... }
  ]
}
```

**Example**

```bash
curl http://localhost:8010/.well-known/agent.json
```

---

### POST /a2a

JSON-RPC 2.0 dispatcher. Supported methods:

| Method | Description |
|---|---|
| `tasks/send` | Run the agentic loop; returns a completed `Task` |
| `tasks/get` | Retrieve a previously completed task by ID |

Task state is in-memory and ephemeral across restarts.

**Request envelope**

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "tasks/send",
  "params": {
    "id": "task-uuid",
    "session_id": "session-uuid",
    "user_id": "jane.doe@walmart.com",
    "message": {
      "role": "user",
      "parts": [{ "type": "text", "text": "Check health of namespace intl-sre" }]
    }
  }
}
```

**`tasks/get` params**

```json
{ "id": "task-uuid" }
```

**Response `200`** — JSON-RPC success envelope with a `Task` result

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "id": "task-uuid",
    "status": { "state": "completed" },
    "artifacts": [
      {
        "name": "answer",
        "index": 0,
        "parts": [{ "type": "text", "text": "All pods are healthy..." }]
      }
    ]
  }
}
```

**Error codes**

| Code | Constant | Meaning |
|---|---|---|
| `-32600` | `INVALID_REQUEST` | Malformed JSON-RPC envelope |
| `-32601` | `METHOD_NOT_FOUND` | Unknown method name |
| `-32602` | `INVALID_PARAMS` | Missing or invalid params |
| `-32001` | `TASK_NOT_FOUND` | No task with the given ID |

---

### POST /a2a/stream

Same as `POST /a2a` (`tasks/send` only) but returns `text/event-stream` (SSE) with per-tool progress events, enabling live streaming to the UI.

**Event types**

| Event type | When | Payload fields |
|---|---|---|
| `progress` | Each MCP tool call (start + finish) | `tool`, `label`, `args`, `status` (`running`/`done`) |
| `complete` | Agent finished | `text` (full answer), `session_id`, `ts` |
| `error` | Invalid params or wrong method | `message` |

**Response headers**

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

**Example**

```bash
curl -X POST http://localhost:8010/a2a/stream \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": "req-1",
    "method": "tasks/send",
    "params": {
      "user_id": "jane.doe@walmart.com",
      "message": {
        "role": "user",
        "parts": [{ "type": "text", "text": "Check health of namespace intl-sre" }]
      }
    }
  }'
```

---

## Redis Key Reference

All session data is stored in Redis under the `health_agent` app namespace:

| Key pattern | Type | Description |
|---|---|---|
| `adk:session:health_agent:{uid}:{sid}` | String (JSON) | Session document — state, title, last_update_time |
| `adk:events:health_agent:{uid}:{sid}` | List | ADK event log (function calls, responses, model output) |
| `agent:ui_events:health_agent:{uid}:{sid}` | List | SSE event log for UI replay |
| `adk:sessions:health_agent:{uid}` | Set | Legacy index of session IDs (pre-ZSET migration) |
| `adk:sessions_z:health_agent:{uid}` | ZSet | Session IDs scored by `last_update_time` (fast sorted listing) |
| `adk:session_meta:health_agent:{uid}` | Hash | `{session_id → title}` for fast title lookups |
| `adk:user_state:health_agent:{uid}` | String (JSON) | User-scoped persistent state |
| `adk:app_state:health_agent` | String (JSON) | App-scoped persistent state |
| `agent:mcp_servers` | String (JSON) | MCP server config array (persistent, no TTL) |
