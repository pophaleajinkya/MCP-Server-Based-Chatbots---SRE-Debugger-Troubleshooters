# Implementation Plan: ADK Agent

**Feature**: `adk-agent` | **Date**: 2026-04-02 | **Spec**: `spec.md`
**Cookiecutter**: `cookiecutter/a2a-agent/`

> Follow this plan step-by-step to build a new ADK agent from the cookiecutter
> template.  Each step references the real project structure and patterns.

---

## Summary

Build an ADK agent that:
1. Reads LLM config from `.env` (user provides their own key)
2. Defines domain-specific tools as async functions
3. Creates an ADK `Agent` with LiteLLM model + tools + instruction
4. Exposes an A2A endpoint for the Super Agent to call

---

## Technical Context

**Language**: Python 3.11+
**Framework**: Google ADK 1.28+ / FastAPI / LiteLLM
**LLM Gateway**: Walmart Stage Gateway (Claude) or Element Gateway (Azure OpenAI)
**Session Store**: Redis Cluster
**Transport**: A2A JSON-RPC over HTTP
**Cookiecutter**: `cookiecutter/a2a-agent/`

---

## Project Structure

```text
my-adk-agent/
├── .env                    # LLM credentials + domain config
├── .env.example            # Template for .env (committed to git)
├── pyproject.toml          # Dependencies
├── src/
│   ├── main.py             # Entry point — uvicorn + FastAPI
│   ├── config.py           # pydantic-settings (reads .env)
│   ├── agent/
│   │   ├── __init__.py     # Exports create_agent()
│   │   └── agent.py        # LLM setup + Agent factory + instruction
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── wcnp_tools.py   # Tool: fetch WCNP apps
│   │   └── user_tools.py   # Tool: fetch user info
│   └── app/
│       └── factory.py      # FastAPI app factory + A2A endpoint
├── tests/
│   ├── test_agent_card.py
│   └── test_a2a_endpoint.py
└── README.md
```

---

## Step-by-Step Implementation

### Step 1: Scaffold from cookiecutter

```bash
cd /path/to/your/workspace
cookiecutter /path/to/super-agent/cookiecutter/a2a-agent/
# Answer prompts:
#   project_name:       WCNP Operations Agent
#   project_slug:       wcnp-ops-agent
#   agent_name:         wcnp_agent
#   agent_description:  WCNP namespace and application operations agent
#   agent_port:         8002
```

### Step 2: Configure `.env`

Copy `.env.example` to `.env` and fill in your LLM credentials:

```env
# ── Server ─────────────────────────────────────────────────────────────────
AGENT_HOST=0.0.0.0
AGENT_PORT=8002
AGENT_ENV=local

# ── LLM Gateway (Claude via Walmart Stage Gateway) ─────────────────────────
CLAUDE_GATEWAY_URL=https://wmtllmgateway.stage.walmart.com/wmtllmgateway/v1/messages
CLAUDE_API_KEY=your-jwt-token-here
CLAUDE_MODEL=claude-sonnet-4-5
CLAUDE_ANTHROPIC_VERSION=vertex-2023-10-16
CLAUDE_IS_PRIMARY_LLM=true

# ── Redis session storage ───────────────────────────────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_USERNAME=default
REDIS_SSL=false

# ── Domain-specific ────────────────────────────────────────────────────────
# Add your own env vars here
DX_API_BASE=https://dx.walmart.com
```

**Key point**: The user provides their LLM key.  The agent reads it at startup.
Never hardcode credentials.

### Step 3: Add domain-specific settings to `config.py`

```python
class Settings(BaseSettings):
    # ... (existing LLM + Redis settings from cookiecutter)

    # ── Domain-specific ────────────────────────────────────────────────────
    dx_api_base: str = "https://dx.walmart.com"
```

### Step 4: Write your tools

Create one file per tool group in `src/tools/`.  Each tool is a plain async
function — ADK wraps it as `FunctionTool` automatically.

**`src/tools/wcnp_tools.py`**:

```python
"""WCNP application tools for the ADK agent."""

import logging
from typing import Any

import httpx

from src.config import get_settings

log = logging.getLogger(__name__)
_s = get_settings()

_HEADERS = {"Accept": "application/json"}


async def fetch_wcnp_apps(namespace: str, profile: str = "prod") -> dict[str, Any]:
    """Fetch all WCNP applications deployed in a namespace.

    Use when user asks: "what apps are in intl-sre?", "show prod apps",
    "how many replicas does app X have?"

    Args:
        namespace: WCNP namespace (e.g. 'intl-sre', 'cart-prod').
        profile:   Environment — 'prod', 'stage', or 'dev'.
    """
    url = f"{_s.dx_api_base}/proxy/wcnp-apps/apps"
    params = {"namespace": namespace, "profile": profile}

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.get(url, params=params, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()

    apps = data.get("apps", [])
    return {
        "status": "success",
        "namespace": namespace,
        "profile": profile,
        "total_apps": len(apps),
        "apps": apps,
        "summary": f"Found {len(apps)} app(s) in {namespace}/{profile}",
    }
```

**`src/tools/user_tools.py`**:

```python
"""User lookup tools for the ADK agent."""

import logging
from typing import Any

import httpx

from src.config import get_settings

log = logging.getLogger(__name__)
_s = get_settings()

_HEADERS = {"Accept": "application/json"}


async def fetch_user_info(service_id: str) -> dict[str, Any]:
    """Look up a Walmart associate or service account by ID.

    Use when user asks: "who is SVC_intl_sre_ops?", "look up user m0a1b2c",
    "who owns this service account?"

    Args:
        service_id: User or service account ID (e.g. 'SVC_intl_sre_ops').
    """
    url = f"{_s.dx_api_base}/common/api/people/users/{service_id}"

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        resp = await client.get(url, headers=_HEADERS)
        if resp.status_code == 404:
            return {
                "status": "not_found",
                "service_id": service_id,
                "message": f"User {service_id} not found",
            }
        resp.raise_for_status()
        user = resp.json()

    return {
        "status": "success",
        "service_id": service_id,
        "user": user,
        "summary": f"Found user: {user.get('displayName', service_id)}",
    }
```

### Tool design rules

| Rule | Why |
|---|---|
| Docstring IS the tool description | ADK shows it to the LLM — be specific |
| Args describe exact types | LLM extracts values from user message to match |
| Return a dict, not a string | Structured data is easier for the LLM to reason over |
| Handle errors gracefully | Return `{"status": "not_found"}` instead of raising |
| Use `httpx.AsyncClient` | Async HTTP with timeouts, `verify=False` for internal certs |
| Single responsibility | One tool = one API call.  Let the LLM chain them |

### Step 5: Write the system instruction

**`src/agent/agent.py`** — the `_INSTRUCTION` string:

```python
_INSTRUCTION = """\
You are a WCNP operations agent for Walmart's Kubernetes platform.

## Capabilities
- Look up applications deployed in any WCNP namespace
- Check replica counts, image versions, and deployment health
- Look up user and service account information
- Cross-reference app ownership with user data

## Tools
- **fetch_wcnp_apps(namespace, profile)** — get all apps in a namespace
- **fetch_user_info(service_id)** — look up a user or service account

## Rules
- Always call tools immediately — never ask for confirmation
- If the user mentions a namespace, call fetch_wcnp_apps first
- Present app lists as markdown tables with columns: name | replicas | image | status
- If a namespace has >20 apps, summarize and highlight top 5 by replica count
- For service accounts (starting with 'SVC_'), call fetch_user_info
"""
```

### Step 6: Register tools in the agent factory

**`src/agent/agent.py`**:

```python
from src.tools.wcnp_tools import fetch_wcnp_apps
from src.tools.user_tools import fetch_user_info

async def create_agent() -> tuple[Agent, AsyncExitStack]:
    exit_stack = AsyncExitStack()

    agent = Agent(
        model=_llm,
        name="wcnp_agent",
        description="WCNP namespace and application operations agent",
        instruction=_INSTRUCTION,
        tools=[fetch_wcnp_apps, fetch_user_info],
    )
    return agent, exit_stack
```

### Step 7: Test locally

```bash
# Install dependencies
pip install -e .

# Start the agent
python -m src.main

# Test the A2A endpoint
curl -X POST http://localhost:8002/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "what apps are in intl-sre namespace?"}],
        "messageId": "test-1"
      }
    }
  }'

# Check Agent Card
curl http://localhost:8002/.well-known/agent.json
```

### Step 8: Register with Super Agent

Add to `mcp_servers.yml` or the A2A agents config:

```yaml
a2a_agents:
  - name: wcnp-agent
    url: http://localhost:8002
    description: "WCNP namespace and application operations agent"
    enabled: true
```

---

## LLM Configuration Options

### Option A: Claude via Walmart Stage Gateway (default)

```env
CLAUDE_GATEWAY_URL=https://wmtllmgateway.stage.walmart.com/wmtllmgateway/v1/messages
CLAUDE_API_KEY=your-jwt-token
CLAUDE_MODEL=claude-sonnet-4-5
CLAUDE_ANTHROPIC_VERSION=vertex-2023-10-16
CLAUDE_IS_PRIMARY_LLM=true
```

```python
_claude_base = _s.claude_gateway_url.removesuffix("/v1/messages").removesuffix("/messages")
_llm = LiteLlm(
    model=f"anthropic/{_s.claude_model}",
    api_key=_s.claude_api_key,
    api_base=_claude_base,
    extra_headers={"anthropic-version": _s.claude_anthropic_version},
)
```

### Option B: Azure OpenAI via Element Gateway

```env
ELEMENT_GATEWAY_BASE_URL=https://wmtllmgateway.prod.walmart.com/wmtllmgateway/openai
ELEMENT_GATEWAY_API_KEY=your-jwt-token
ELEMENT_GATEWAY_API_VERSION=2024-10-21
OPENAI_MODEL=gpt-4.1
CLAUDE_IS_PRIMARY_LLM=false
```

```python
_litellm_base = f"{_s.element_gateway_base_url}/deployments/{_s.openai_model}"
_llm = LiteLlm(
    model=f"azure/{_s.openai_model}",
    api_key=_s.element_gateway_api_key,
    api_base=_litellm_base,
    api_version=_s.element_gateway_api_version,
)
```

---

## Constraints

- **LLM key is user-provided** — never hardcode, never commit `.env`
- **`litellm.ssl_verify = False`** — required for Walmart internal gateways
- **Tool names must be globally unique** — across all agents connected to Super Agent
- **Use `verify=False`** in httpx for internal API calls (Walmart certs)
- **Max tool rounds**: Default 8, configurable via `MAX_TOOL_ROUNDS`
- **Timeout**: Default 60s per LLM call, configurable via `LLM_TIMEOUT_SECONDS`
