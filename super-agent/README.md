# Health Agent

An ADK-based orchestration agent that answers natural language questions about WCNP cluster health, Kubernetes metrics, latency trends, and service dependencies. Connects to two MCP servers (health-mcp and dependency-mcp) and renders interactive charts directly in the UI.

Runs at **`http://0.0.0.0:8010`** by default.

---

## Local Development Setup

### Prerequisites

- Python 3.11+
- Access to a Redis cluster (for session storage)
- Both MCP servers running locally:
  - **health-mcp** on `:8999`
  - **dependency-mcp** on `:8015`

### 1. Create virtualenv and install dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values. The minimum required for local dev:

```env
# ── LLM ──────────────────────────────────────────────────────────────────────
CLAUDE_GATEWAY_URL=https://wmtllmgateway.stage.walmart.com/wmtllmgateway/v1/messages
CLAUDE_API_KEY=your-api-key
CLAUDE_IS_PRIMARY_LLM=true

# ── Redis (session storage) ───────────────────────────────────────────────────
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# ── Local dev: skip Redis for MCP config, read from YAML instead ──────────────
AGENT_ENV=local
MCP_SERVERS_FILE=./mcp_servers.yml
```

### 3. Configure local MCP servers

```bash
cp mcp_servers.yml.example mcp_servers.yml
```

Edit `mcp_servers.yml` to point to your locally running MCP servers:

```yaml
servers:
  - name: health-mcp
    url: http://localhost:8999/mcp/
    transport: streamable_http
    enabled: true
    description: "WCNP health checks, Prometheus queries, chart rendering"
    headers: {}

  - name: dependency-mcp
    url: http://localhost:8015/mcp/
    transport: streamable_http
    enabled: true
    description: "Upstream/downstream dependency graph"
    headers: {}
```

> `mcp_servers.yml` is gitignored — never commit it. Only `mcp_servers.yml.example` is tracked.

### 4. Start the agent

```bash
source .venv/bin/activate
uvicorn src.main:app --host 0.0.0.0 --port 8010 --reload
```

Agent starts at **http://localhost:8010**

---

## How AGENT_ENV=local works

When `AGENT_ENV=local` is set, the agent **skips Redis** for MCP server configuration and reads from `MCP_SERVERS_FILE` (a local YAML file) instead.

| Setting | MCP config source |
|---|---|
| `AGENT_ENV=prod` (default) | Redis key `super_agent:config:mcp_servers:<env>:<group>:config` |
| `AGENT_ENV=local` | Local YAML file at `MCP_SERVERS_FILE` |

> All other Redis usage (session storage, conversation history, ui_events) is **unaffected** by `AGENT_ENV=local`. Sessions still require a Redis connection.

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — returns MCP server list and loaded tool names |
| `POST` | `/a2a/stream` | Main chat endpoint (SSE stream) used by the UI |
| `GET` | `/sessions` | List conversation sessions for a user |
| `GET` | `/sessions/{id}/messages` | Full message + event history for a session |
| `GET` | `/mcp-validate` | Validates all loaded MCP tool schemas |

### Health check

```bash
curl http://localhost:8010/health
```

```json
{
  "status": "ok",
  "version": "2.0.0",
  "active_llm": "claude",
  "mcp_servers": [
    {"name": "health-mcp", "url": "http://localhost:8999/mcp/"},
    {"name": "dependency-mcp", "url": "http://localhost:8015/mcp/"}
  ],
  "mcp_tools": ["wcnp_list_deployments", "wcnp_check_app_health", ...]
}
```

---

## MCP Servers

The agent connects to two MCP servers at startup:

### health-mcp (`:8999`)

Provides WCNP health and metrics tools:

| Tool | Description |
|---|---|
| `wcnp_list_deployments` | List all deployments in a namespace |
| `wcnp_check_app_health` | Full health check for a single app |
| `wcnp_check_namespace_health` | Health check across all apps in a namespace |
| `wcnp_get_app_clusters` | Find which clusters an app runs on |
| `wcnp_query_prometheus` | Raw PromQL query |
| `wcnp_chart` | PromQL query pre-formatted for chart rendering |
| `wcnp_chart` | Full health + metrics dashboard for an app |
| `render_chart` | Render a line/bar chart in the UI |
| `render_multi_chart` | Render multiple synchronized charts side-by-side |
| `render_grafana_panel` | Embed a live Grafana panel in the chat |

### dependency-mcp (`:8015`)

Provides upstream/downstream dependency graph tools:

| Tool | Description |
|---|---|
| `fetch_wcnp_upstream_dependencies` | Upstream WCNP dependencies |
| `fetch_wcnp_downstream_dependencies` | Downstream WCNP dependencies |
| `fetch_oneops_upstream_dependencies` | OneOps upstream dependencies |
| `fetch_cassandra_upstream_dependencies` | Cassandra upstream dependencies |
| `fetch_meghacache_upstream_dependencies` | MeghaCache upstream dependencies |

---

## Session Management

Conversations are stored in Redis and survive page refreshes. The agent uses **event sourcing** — every SSE event (tool calls, progress, chart data, final text) is persisted to `agent:ui_events:{app}:{user}:{session}` in Redis. On page refresh, the UI replays the exact same events to reconstruct the full visual state including charts and progress steps.

### Retrieve session history

```bash
curl "http://localhost:8010/sessions?user_id=admin"
curl "http://localhost:8010/sessions/{session_id}/messages?user_id=admin"
```

---

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/unit/ -v
```

Key test files:

| File | What it tests |
|---|---|
| `tests/unit/test_runner_events.py` | SSE event emission + ui_events persistence |
| `tests/unit/test_sessions_router.py` | Session history API (ADK fallback + event-sourced path) |
| `tests/unit/test_mcp_client.py` | MCP loader (dev YAML + prod Redis) |

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `AGENT_ENV` | `prod` | Set to `local` to load MCP servers from a local YAML file instead of Redis |
| `MCP_SERVERS_FILE` | `""` | Path to local YAML file. Required when `AGENT_ENV=local` |
| `CLAUDE_GATEWAY_URL` | `""` | Walmart Claude gateway endpoint |
| `CLAUDE_API_KEY` | `""` | API key for the Claude gateway |
| `CLAUDE_IS_PRIMARY_LLM` | `false` | Set `true` to use Claude instead of OpenAI |
| `CLAUDE_MODEL` | `claude-opus-4-6` | Claude model ID |
| `REDIS_HOST` | `""` | Redis cluster host |
| `REDIS_PORT` | `6379` | Redis cluster port |
| `REDIS_PASSWORD` | `""` | Redis password |
| `REDIS_USERNAME` | `appuser` | Redis username |
| `REDIS_SESSION_TTL_SECONDS` | `604800` | Session TTL (default: 7 days) |
| `AGENT_HOST` | `0.0.0.0` | Bind host |
| `AGENT_PORT` | `8001` | Bind port (override with uvicorn `--port`) |
| `CORS_ALLOWED_ORIGINS` | see config.py | JSON array of allowed CORS origins |
