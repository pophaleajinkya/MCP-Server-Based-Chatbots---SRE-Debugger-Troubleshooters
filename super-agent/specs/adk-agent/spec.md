# Spec: Building an ADK Agent (A2A Subagent)

**Feature**: `adk-agent` | **Date**: 2026-04-02 | **Status**: Active
**Cookiecutter**: `cookiecutter/a2a-agent/`

> **Audience**: AI coding assistants (Copilot, Wibey, Claude) + developers.
> Read this spec when building a new ADK-based agent that connects to the
> Super Agent as an A2A subagent.

---

## Summary

An ADK Agent is a standalone service that uses Google's Agent Development Kit
(ADK) to orchestrate LLM calls with tools.  It exposes an A2A (Agent-to-Agent)
JSON-RPC endpoint that the Super Agent can delegate to for domain-specific tasks.

**Key difference from MCP servers**: An ADK agent has its **own LLM** — it
reasons, plans, and calls tools autonomously.  An MCP server is a dumb tool
provider with no LLM.

---

## Architecture

```
User Question → Super Agent (orchestrator)
                    │
                    ├─ calls MCP tools directly (no LLM in MCP)
                    │
                    └─ delegates to A2A subagent via JSON-RPC
                         │
                         ├─ ADK Agent has its OWN LLM (Claude/GPT via LiteLLM)
                         ├─ Agent reasons + calls its own tools
                         └─ Returns final answer to Super Agent
```

---

## User Scenarios

### P1 — Scaffold a new ADK agent

**Given** a developer wants to build a new domain-specific agent
**When** they run `cookiecutter cookiecutter/a2a-agent/`
**Then** they get a working project with LLM config, tool template, A2A endpoint, tests
**And** they configure their LLM in `.env` and add their domain tools

### P1 — Agent calls external APIs as tools

**Given** an ADK agent needs data from Walmart internal APIs
**When** the agent's LLM decides to call a tool
**Then** the tool makes an HTTP call to the API and returns structured data
**And** the LLM reasons over the response and produces an answer

### P2 — Agent connects to Super Agent as subagent

**Given** a working ADK agent with an A2A endpoint
**When** the Super Agent is configured to delegate to it
**Then** the Super Agent sends questions via JSON-RPC `message/send`
**And** the ADK agent processes autonomously and returns the answer

---

## Requirements

### FR-001: LLM via LiteLLM in `.env`

The user provides their LLM configuration in `.env`.  The agent reads it at
startup and creates a `LiteLlm` model instance.

```env
# Claude via Walmart Stage Gateway (default)
CLAUDE_GATEWAY_URL=https://wmtllmgateway.stage.walmart.com/wmtllmgateway/v1/messages
CLAUDE_API_KEY=your-jwt-token
CLAUDE_MODEL=claude-sonnet-4-5
CLAUDE_ANTHROPIC_VERSION=vertex-2023-10-16
CLAUDE_IS_PRIMARY_LLM=true
```

**LiteLLM setup**:
```python
import litellm
litellm.ssl_verify = False  # Walmart internal certs

from google.adk.models.lite_llm import LiteLlm

_claude_base = _s.claude_gateway_url.removesuffix("/v1/messages").removesuffix("/messages")
_llm = LiteLlm(
    model=f"anthropic/{_s.claude_model}",
    api_key=_s.claude_api_key,
    api_base=_claude_base,
    extra_headers={"anthropic-version": _s.claude_anthropic_version},
)
```

### FR-002: Tools as async functions

Tools are plain async functions.  ADK auto-wraps them as `FunctionTool`.
The docstring IS the tool description shown to the LLM.

```python
async def fetch_wcnp_apps(namespace: str, profile: str = "prod") -> dict:
    """Fetch WCNP applications for a given namespace and profile.

    Use this tool when the user asks about apps deployed in a namespace,
    their status, replicas, or deployment details.

    Args:
        namespace: The WCNP namespace (e.g. 'intl-sre', 'cart-prod').
        profile:   Environment profile — 'prod', 'stage', or 'dev'.
    """
    url = f"https://dx.walmart.com/proxy/wcnp-apps/apps?namespace={namespace}&profile={profile}"
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()
```

### FR-003: Agent factory pattern

The agent is created via an async factory function that returns `(Agent, AsyncExitStack)`.

```python
async def create_agent() -> tuple[Agent, AsyncExitStack]:
    exit_stack = AsyncExitStack()
    tools = [fetch_wcnp_apps, fetch_user_info]  # your domain tools

    agent = Agent(
        model=_llm,
        name="wcnp-agent",
        description="WCNP namespace and application management agent",
        instruction=_INSTRUCTION,
        tools=tools,
    )
    return agent, exit_stack
```

### FR-004: A2A endpoint via FastAPI

The agent exposes a JSON-RPC A2A endpoint for the Super Agent to call.

```python
# POST /a2a — Super Agent calls this
# GET /.well-known/agent.json — Agent Card discovery
```

### FR-005: System instruction with domain knowledge

The instruction tells the LLM what it can do and how to use tools.

```python
_INSTRUCTION = """\
You are a WCNP operations agent. You help users understand their
Kubernetes namespaces, applications, and team ownership.

Available tools:
- fetch_wcnp_apps: Get apps in a namespace (always call this first)
- fetch_user_info: Look up a user by service ID

Always call tools immediately — never ask for confirmation.
Present results in a clear markdown table.
"""
```

### FR-006: Configuration via pydantic-settings

All config is loaded from `.env` via `pydantic_settings.BaseSettings`.

```python
class Settings(BaseSettings):
    agent_host: str = "0.0.0.0"
    agent_port: int = 8002
    claude_gateway_url: str = ""
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    redis_host: str = "localhost"
    redis_port: int = 6379
    max_tool_rounds: int = 8
    llm_timeout_seconds: int = 60
    model_config = SettingsConfigDict(extra="ignore")
```

---

## Real-World Example: WCNP Operations Agent

An agent that uses two Walmart internal APIs as tools.

### Tool 1: Fetch WCNP Apps

**Endpoint**: `https://dx.walmart.com/proxy/wcnp-apps/apps?namespace=intl-sre&profile=prod`

```python
import httpx
from typing import Any

_DX_HEADERS = {"Accept": "application/json"}

async def fetch_wcnp_apps(namespace: str, profile: str = "prod") -> dict[str, Any]:
    """Fetch all WCNP applications deployed in a namespace.

    Use when user asks: "what apps are in intl-sre?", "show prod apps in cart namespace",
    "how many replicas does app X have?", "what's deployed in namespace Y?"

    Args:
        namespace: WCNP namespace (e.g. 'intl-sre', 'cart-prod', 'item-setup').
        profile:   Environment — 'prod', 'stage', or 'dev'. Defaults to 'prod'.

    Returns:
        Dict with app list, replica counts, image versions, and health status.
    """
    url = "https://dx.walmart.com/proxy/wcnp-apps/apps"
    params = {"namespace": namespace, "profile": profile}

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.get(url, params=params, headers=_DX_HEADERS)
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

### Tool 2: Fetch User Info

**Endpoint**: `https://dx.walmart.com/common/api/people/users/{service_id}`

```python
async def fetch_user_info(service_id: str) -> dict[str, Any]:
    """Look up a Walmart associate or service account by their ID.

    Use when user asks: "who is SVC_intl_sre_ops?", "look up user m0a1b2c",
    "who owns this service account?", "get contact info for user X".

    Args:
        service_id: The user or service account ID (e.g. 'SVC_intl_sre_ops', 'm0a1b2c').

    Returns:
        Dict with user name, email, team, manager, and role information.
    """
    url = f"https://dx.walmart.com/common/api/people/users/{service_id}"

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        resp = await client.get(url, headers=_DX_HEADERS)
        if resp.status_code == 404:
            return {"status": "not_found", "service_id": service_id, "message": f"User {service_id} not found"}
        resp.raise_for_status()
        user = resp.json()

    return {
        "status": "success",
        "service_id": service_id,
        "user": user,
        "summary": f"Found user: {user.get('displayName', service_id)}",
    }
```

### Complete Agent

```python
from google.adk.agents import Agent

_INSTRUCTION = """\
You are a WCNP operations agent for Walmart's Kubernetes platform.

## Capabilities
- Look up applications deployed in any namespace
- Check replica counts, image versions, and health status
- Look up user/service account information
- Cross-reference app ownership with user data

## Rules
- Always call fetch_wcnp_apps first when asked about namespaces or apps
- Use fetch_user_info to look up service accounts or team members
- Present app lists as markdown tables
- If a namespace has >20 apps, highlight the top 5 by replica count
"""

async def create_agent():
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

---

## ADK Agent vs MCP Server — When to Use Which

| Question | ADK Agent | MCP Server |
|---|---|---|
| Does it need its own LLM? | **Yes** — reasons autonomously | No — just a tool provider |
| Does it call tools on its own? | Yes — LLM decides which tools to call | No — the orchestrator LLM decides |
| Does it have a system prompt? | Yes — domain-specific instruction | No — agent-guide resource only |
| User configures LLM in `.env`? | **Yes** — `CLAUDE_MODEL`, `CLAUDE_API_KEY` | No — no LLM needed |
| Multi-step reasoning? | Yes — can chain tool calls | No — one tool call at a time |
| Token cost | Higher — runs its own LLM | Lower — no LLM tokens |
| Best for | Complex workflows, investigation, analysis | Simple data fetching, CRUD, lookups |

**Rule of thumb**: If the task needs **reasoning** (investigation, analysis,
multi-step workflows), use an ADK agent.  If it just needs **data** (fetch
incidents, query metrics, list apps), use an MCP server.

---

## Success Criteria

- **SC-001**: Agent starts and responds to A2A JSON-RPC requests
- **SC-002**: LLM correctly calls tools based on user questions
- **SC-003**: Tools return structured data the LLM can reason over
- **SC-004**: Agent Card at `/.well-known/agent.json` is discoverable
- **SC-005**: Configuration is fully driven by `.env` (no hardcoded credentials)
- **SC-006**: Agent can be registered as a subagent in Super Agent
