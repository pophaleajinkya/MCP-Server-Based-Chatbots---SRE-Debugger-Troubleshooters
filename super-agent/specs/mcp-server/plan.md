# Implementation Plan: MCP Server

**Feature**: `mcp-server` | **Date**: 2026-04-02 | **Spec**: `spec.md`
**Cookiecutter**: `cookiecutter/mcp-server/`

> Follow this plan step-by-step to build a new MCP server from the cookiecutter
> template.  No LLM configuration needed — MCP servers are pure tool providers.

---

## Summary

Build an MCP server that:
1. Exposes domain-specific tools via `@mcp.tool()` decorators
2. Provides an agent-guide resource for the Super Agent's LLM
3. Returns structured JSON responses (with `table_data` for large datasets)
4. Mounts at `/mcp/` via FastAPI for Streamable HTTP transport

---

## Technical Context

**Language**: Python 3.11+
**Framework**: MCP Python SDK (`mcp>=0.1.0`) + FastAPI
**Transport**: Streamable HTTP (JSON-RPC at `POST /mcp/`)
**No LLM**: MCP servers do NOT need LiteLLM, no API keys for language models
**HTTP Client**: `httpx` (recommended) or `aiohttp` for external API calls

---

## Project Structure

```text
my-mcp-server/
├── .env                    # Domain-specific config only (no LLM keys!)
├── .env.example            # Template for .env
├── pyproject.toml          # Dependencies
├── src/
│   ├── main.py             # Entry point — FastAPI + mount MCP at /mcp/
│   ├── config.py           # pydantic-settings (reads .env)
│   ├── server.py           # FastMCP instance + tools + resources + prompts
│   └── services/           # Business logic (no MCP dependencies)
│       ├── __init__.py
│       ├── api_client.py   # HTTP client for external APIs
│       └── data_service.py # Business logic layer
├── tests/
│   ├── test_health.py
│   └── test_tools.py
└── README.md
```

---

## Step-by-Step Implementation

### Step 1: Scaffold from cookiecutter

```bash
cd /path/to/your/workspace
cookiecutter /path/to/super-agent/cookiecutter/mcp-server/
# Answer prompts:
#   project_name:       WCNP MCP Server
#   project_slug:       wcnp-mcp-server
#   server_name:        wcnp-mcp
#   server_description: MCP server for WCNP namespace and app lookups
#   server_port:        8020
```

### Step 2: Configure `.env` (NO LLM needed)

```env
# ── Server ─────────────────────────────────────────────────────────────────
SERVER_HOST=0.0.0.0
SERVER_PORT=8020

# ── Domain-specific (your API endpoints) ──────────────────────────────────
DX_API_BASE=https://dx.walmart.com
REQUEST_TIMEOUT_SECONDS=30
```

**Key point**: No `CLAUDE_*`, no `OPENAI_*`, no `ELEMENT_GATEWAY_*` — MCP
servers don't need LLM credentials.

### Step 3: Add domain settings to `config.py`

```python
class Settings(BaseSettings):
    server_host: str = "0.0.0.0"
    server_port: int = 8020

    # ── Domain-specific ────────────────────────────────────────────────────
    dx_api_base: str = "https://dx.walmart.com"
    request_timeout_seconds: int = 30

    model_config = SettingsConfigDict(extra="ignore")
```

### Step 4: Write the HTTP client

**`src/services/api_client.py`**:

```python
"""HTTP client for external API calls."""

import logging
from typing import Any

import httpx

from src.config import get_settings

log = logging.getLogger(__name__)
_s = get_settings()

_HEADERS = {"Accept": "application/json"}


class DxClient:
    """Async HTTP client for DX Platform APIs."""

    def __init__(self) -> None:
        self._base = _s.dx_api_base
        self._timeout = _s.request_timeout_seconds

    async def get_wcnp_apps(self, namespace: str, profile: str = "prod") -> list[dict]:
        """Fetch apps from WCNP apps endpoint."""
        url = f"{self._base}/proxy/wcnp-apps/apps"
        params = {"namespace": namespace, "profile": profile}

        async with httpx.AsyncClient(timeout=self._timeout, verify=False) as client:
            resp = await client.get(url, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()

        return data.get("apps", [])

    async def get_user(self, service_id: str) -> dict[str, Any] | None:
        """Fetch user info by service ID.  Returns None if not found."""
        url = f"{self._base}/common/api/people/users/{service_id}"

        async with httpx.AsyncClient(timeout=self._timeout, verify=False) as client:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
```

### Step 5: Write the business logic service

**`src/services/data_service.py`**:

```python
"""Business logic — no MCP or HTTP dependencies."""

from typing import Any

from src.services.api_client import DxClient


class WcnpService:
    """Domain logic for WCNP operations."""

    def __init__(self, client: DxClient) -> None:
        self._client = client

    async def list_apps(self, namespace: str, profile: str = "prod") -> list[dict]:
        """Get apps in a namespace with simplified fields."""
        raw_apps = await self._client.get_wcnp_apps(namespace, profile)
        return [
            {
                "name": app.get("name"),
                "replicas": app.get("replicas"),
                "image": app.get("image"),
                "status": app.get("status"),
                "namespace": namespace,
                "profile": profile,
            }
            for app in raw_apps
        ]

    async def get_user_info(self, service_id: str) -> dict[str, Any] | None:
        """Look up a user by service ID."""
        return await self._client.get_user(service_id)
```

### Step 6: Write MCP tools

**`src/server.py`** — tools are thin wrappers over the service layer:

```python
from mcp.server.fastmcp import FastMCP
from src.services.api_client import DxClient
from src.services.data_service import WcnpService

mcp = FastMCP(name="wcnp-mcp", version="1.0.0")

# Singletons
_client = DxClient()
_service = WcnpService(client=_client)

# ── Display columns for table_data (large dataset handling) ──────────────
_DISPLAY_COLUMNS = ["name", "replicas", "image", "status", "namespace", "profile"]


@mcp.tool(
    name="fetch_wcnp_apps",
    description=(
        "Fetch applications deployed in a WCNP namespace.\n\n"
        "Use when user asks: 'what apps are in intl-sre?', 'show prod apps',\n"
        "'how many replicas does app X have?'\n\n"
        "Parameters:\n"
        "  namespace — WCNP namespace (e.g. 'intl-sre', 'cart-prod')\n"
        "  profile   — 'prod', 'stage', or 'dev' (default: 'prod')"
    ),
)
async def fetch_wcnp_apps(namespace: str, profile: str = "prod") -> dict:
    """Fetch WCNP apps in a namespace."""
    apps = await _service.list_apps(namespace, profile)
    total = len(apps)

    # table_data contract for large datasets (see specs/large-table-handling/)
    table_rows = [{col: a.get(col) for col in _DISPLAY_COLUMNS} for a in apps]

    return {
        "status": "success",
        "total_count": total,
        "summary": f"Found {total} app(s) in {namespace}/{profile}",
        "apps": apps[:25],  # inline sample for LLM
        "table_data": {
            "columns": list(_DISPLAY_COLUMNS),
            "rows": table_rows,
        },
        "display_hint": f"Display ALL apps in a markdown table. Columns: {' | '.join(_DISPLAY_COLUMNS)}.",
    }


@mcp.tool(
    name="fetch_user_info",
    description=(
        "Look up a Walmart associate or service account by ID.\n\n"
        "Use when user asks: 'who is SVC_intl_sre_ops?', 'look up user m0a1b2c',\n"
        "'who owns this service account?'\n\n"
        "Parameters:\n"
        "  service_id — User or service account ID (e.g. 'SVC_intl_sre_ops')"
    ),
)
async def fetch_user_info(service_id: str) -> dict:
    """Look up user by service ID."""
    user = await _service.get_user_info(service_id)
    if not user:
        return {"status": "not_found", "service_id": service_id, "message": f"User {service_id} not found"}
    return {
        "status": "success",
        "service_id": service_id,
        "user": user,
        "summary": f"Found user: {user.get('displayName', service_id)}",
    }
```

### Step 7: Write the agent guide

This is the most important resource — Super Agent auto-discovers it and injects
it into the orchestrator LLM's system prompt.

```python
@mcp.resource("wcnp-mcp://agent-guide")
async def agent_guide() -> str:
    return """\
## WCNP MCP — Tool Routing Guide

### Tools available

#### fetch_wcnp_apps
- **When to use**: User asks about apps, namespaces, replicas, deployments
- **Required args**: `namespace` — extract from user's message
- **Optional args**: `profile` — defaults to 'prod'
- **Returns**: App list with name, replicas, image, status

#### fetch_user_info
- **When to use**: User asks about a person, service account, or ownership
- **Required args**: `service_id` — extract from user's message
- **Returns**: User details (name, email, team, manager)

### Prompt templates

| Template | When to use |
|---|---|
| namespace-audit | User asks for a comprehensive namespace review |

### Domain constraints
- Namespace names are lowercase with hyphens (e.g. 'intl-sre', 'cart-prod')
- Profile must be exactly 'prod', 'stage', or 'dev'
- Service account IDs start with 'SVC_' prefix
"""
```

### Step 8: Write prompt templates (optional)

```python
@mcp.prompt("namespace_audit")
async def namespace_audit(namespace: str) -> str:
    return f"""\
## Namespace Audit: {namespace}

### Steps
1. Call `fetch_wcnp_apps` for namespace="{namespace}" profile="prod"
2. Summarize: total apps, replica counts, image versions
3. Identify any unhealthy apps (status != "Running")
4. Call `fetch_user_info` for the namespace owner if known

### Output format
- **Namespace**: {namespace}
- **Total apps**: N
- **Healthy**: N / Unhealthy: N
- **App table**: name | replicas | image | status
- **Recommendations**: any actions needed
"""
```

### Step 9: Register with Super Agent

Add to `mcp_servers.yml`:

```yaml
mcp_servers:
  - name: wcnp-mcp
    description: "WCNP namespace and application lookups"
    url: http://localhost:8020/mcp/
    transport: streamable_http
    enabled: true
    headers: {}
```

### Step 10: Test locally

```bash
# Start the server
python -m src.main

# Health check
curl http://localhost:8020/health

# List tools (JSON-RPC)
curl -X POST http://localhost:8020/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Call a tool
curl -X POST http://localhost:8020/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"fetch_wcnp_apps","arguments":{"namespace":"intl-sre"}}}'
```

---

## Separation of Concerns — The 4-Layer Pattern

Every MCP server should follow this pattern (from incident-mcp):

```text
Layer 1: HTTP Client        — All network calls (httpx/aiohttp)
Layer 2: Service            — Business logic (no MCP, no HTTP deps)
Layer 3: MCP Tools          — Thin @mcp.tool() wrappers over service
Layer 4: Resources/Prompts  — Agent guide + workflow templates
```

| Layer | Depends on | Example file |
|---|---|---|
| HTTP Client | httpx, external APIs | `services/api_client.py` |
| Service | Client only | `services/data_service.py` |
| MCP Tools | Service, FastMCP | `server.py` (tools section) |
| Resources | FastMCP only | `server.py` (resources section) |

**Why**: Tools are easy to test (mock the service), service is easy to test
(mock the client), client is easy to test (mock httpx).

---

## Constraints

- **No LLM** — MCP servers don't need language model credentials
- **No reasoning** — tools return data, the Super Agent LLM reasons
- **Tool names must be globally unique** — across all MCP servers
- **`verify=False`** for internal API calls (Walmart certs)
- **`ssl=False`** for aiohttp (same reason)
- **Agent guide URI** must end with `://agent-guide` for auto-discovery
- **JSON-RPC transport** — `POST /mcp/` (Streamable HTTP)
- **Anthropic schema compliance** — no `default`, `$ref`, `definitions` in tool schemas
