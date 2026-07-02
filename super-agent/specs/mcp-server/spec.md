# Spec: Building an MCP Server

**Feature**: `mcp-server` | **Date**: 2026-04-02 | **Status**: Active
**Cookiecutter**: `cookiecutter/mcp-server/`

> **Audience**: AI coding assistants (Copilot, Wibey, Claude) + developers.
> Read this spec when building a new MCP server that connects to the Super Agent
> as a tool provider.

---

## Summary

An MCP server is a stateless tool provider that exposes domain-specific
functions over the Model Context Protocol (MCP).  The Super Agent's LLM
decides when to call these tools — the MCP server has **no LLM of its own**.

**Key difference from ADK agents**: An MCP server does NOT have a language model.
It's a dumb pipe: receive request → call API/DB → return structured data.
The Super Agent's LLM does all the reasoning.

---

## Architecture

```
User Question → Super Agent (has the LLM)
                    │
                    ├─ LLM decides which tool to call
                    │
                    └─ calls MCP tool via JSON-RPC POST /mcp/
                         │
                         ├─ MCP Server has NO LLM
                         ├─ Tool function calls external API / DB
                         ├─ Returns structured JSON response
                         └─ Super Agent LLM reasons over the result
```

---

## User Scenarios

### P1 — Scaffold a new MCP server

**Given** a developer wants to expose a new API as tools for the Super Agent
**When** they run `cookiecutter cookiecutter/mcp-server/`
**Then** they get a working project with FastMCP, tool template, agent-guide, health check
**And** they add their domain tools and register with Super Agent

### P1 — Super Agent calls MCP tools

**Given** an MCP server registered in `mcp_servers.yml` or Redis
**When** the Super Agent's LLM decides to call a tool
**Then** it sends a JSON-RPC `tools/call` request to `POST /mcp/`
**And** the MCP server executes the tool and returns structured JSON

### P2 — Agent guide injects domain knowledge

**Given** an MCP server defines a resource at `{server-name}://agent-guide`
**When** the Super Agent starts up and discovers MCP servers
**Then** the agent-guide content is injected into the LLM's system prompt
**And** the LLM knows which tools to call for which scenarios

### P2 — Large datasets handled via table_data contract

**Given** a tool returns >50 rows of tabular data
**When** the response uses the `table_data` contract (see `specs/large-table-handling/`)
**Then** the Super Agent hook strips rows before the LLM sees them
**And** the UI receives full data via SSE for table rendering

---

## Requirements

### FR-001: No LLM needed

MCP servers do NOT need an LLM.  No `.env` LLM configuration, no LiteLLM, no
API keys for language models.  The only config needed is for the domain APIs
the server wraps.

```env
# MCP server .env — NO LLM config needed
SERVER_HOST=0.0.0.0
SERVER_PORT=8999

# Domain-specific only
SEED_BEES_URL=https://flash.seedbees.walmart.com/search
DEFAULT_INCIDENT_WINDOW_HOURS=3
```

### FR-002: FastMCP server definition

Use `FastMCP` from the MCP Python SDK.  One server instance, imported by tools.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="my-mcp-server",
    version="1.0.0",
)
```

### FR-003: Tools as `@mcp.tool()` decorated async functions

```python
@mcp.tool(
    name="fetch_incidents",
    description=(
        "Search incidents with flexible filters.\n"
        "Use for: 'show active incidents', 'P1 incidents in Mexico'.\n\n"
        "Parameters:\n"
        "  is_active — 'true' or 'false'\n"
        "  priority — e.g. '1 - Critical'\n"
    ),
)
async def fetch_incidents(is_active: str = "", priority: str = "") -> dict:
    ...
```

### FR-004: Agent guide resource (auto-discovered)

The most important resource.  Super Agent auto-discovers any resource whose
URI ends with `://agent-guide` and injects it into the LLM's system prompt.

```python
@mcp.resource("my-server://agent-guide")
async def agent_guide() -> str:
    return """\
## My Server — Tool Routing Guide

### Tools available
- **fetch_data**: Use when user asks about X
- **get_details**: Use when user asks about Y

### Domain constraints
- Always use epoch milliseconds for timestamps
- Priority format: '1 - Critical', '2 - High', '3 - Medium', '4 - Low'
"""
```

### FR-005: Mount at `/mcp/` via FastAPI

```python
from fastapi import FastAPI
from src.server import mcp

app = FastAPI()
app.mount("/mcp", mcp.streamable_http_app())
```

Super Agent connects to: `POST http://<host>:<port>/mcp/`

### FR-006: Tool schema compliance (Anthropic/Claude)

Tools must comply with Anthropic's JSON schema requirements:

| Rule | Details |
|---|---|
| Top-level type | MUST be `"object"` |
| No `"default"` | Remove default values from parameter schemas |
| No `"$ref"` | Inline all references |
| No `"definitions"` | Remove definition blocks |
| No `"if"/"then"/"else"` | Not supported |
| Unique names | Tool names must be unique across ALL MCP servers |

### FR-007: Large dataset handling

When a tool returns >50 rows of tabular data, use the `table_data` contract
from `specs/large-table-handling/`:

```python
response = {
    "summary":    _build_summary(results, filters_applied),
    "incidents":  results[:25],  # inline sample for LLM
    "table_data": {
        "columns": list(_DISPLAY_COLUMNS),
        "rows":    [{col: r.get(col) for col in _DISPLAY_COLUMNS} for r in results],
    },
}
```

---

## Real-World Example: Incident MCP Server

A production MCP server wrapping ServiceNow incident data.

### Project structure

```text
maof-incident-agent/
├── main.py                           # Entry point
├── src/
│   ├── incident_agent.py             # FastAPI app + REST endpoints
│   ├── mcp_server/
│   │   ├── server.py                 # FastMCP("incident-agent")
│   │   ├── tools/
│   │   │   └── incident.py           # 7 MCP tools
│   │   └── resources_and_prompts.py  # agent-guide + prompt templates
│   ├── utils/
│   │   ├── config.py                 # pydantic-settings
│   │   ├── seedbees_client.py        # HTTP client for SeedBees API
│   │   └── incident_service.py       # Business logic (no MCP deps)
│   └── models/
│       ├── request_models.py
│       └── response_models.py
├── .env
├── Dockerfile
└── kitt.yml
```

### Key design patterns

1. **Separation of concerns**:
   - `seedbees_client.py` — HTTP calls only
   - `incident_service.py` — business logic (no MCP, no HTTP dependencies)
   - `tools/incident.py` — thin `@mcp.tool()` wrappers over service layer
   - `resources_and_prompts.py` — agent-guide + workflow templates

2. **Shared response builder**:
   ```python
   def _build_list_response(results, filters_applied, extra=None):
       # ALL list tools call this — single point of change
   ```

3. **`_DISPLAY_COLUMNS` constant**:
   ```python
   _DISPLAY_COLUMNS = [
       "incidentNumber", "shortDescription", "priority",
       "isActive", "isMajorIncident", "type", "department", "createdAt",
   ]
   ```

4. **Rich summary for LLM**:
   ```python
   def _build_summary(results, filters_applied):
       # Total/active/inactive, major breakdown, priority distribution,
       # latest per priority — LLM uses this instead of scanning rows
   ```

5. **Prompt templates for workflows**:
   ```python
   @mcp.prompt("investigate_incident")
   def investigate_incident(incident_number: str) -> str:
       """Root-cause investigation workflow"""

   @mcp.prompt("daily_incident_report")
   def daily_incident_report(market: str = "") -> str:
       """Active + major incidents daily summary"""
   ```

### Tools overview

| Tool | Purpose | Args |
|---|---|---|
| `fetch_incidents` | Flexible search with filters | is_active, priority, market, timestamps... |
| `fetch_active_incidents` | Shortcut: active only | market |
| `fetch_major_incidents` | Shortcut: major only | market, is_active |
| `fetch_mx_incidents` | Mexico market + banner | epoch window, banner |
| `fetch_ca_incidents` | Canada market + banner | epoch window, banner |
| `fetch_cl_incidents` | Chile market + banner | epoch window, banner |
| `fetch_incident_details` | Single incident detail | incident_number |

---

## MCP Server vs ADK Agent — When to Use Which

| Question | MCP Server | ADK Agent |
|---|---|---|
| Has its own LLM? | **No** — just a tool provider | Yes — reasons autonomously |
| Who decides which tool to call? | Super Agent's LLM | Agent's own LLM |
| User configures LLM in `.env`? | **No** — no LLM needed | Yes |
| Token cost | **Zero** — no LLM tokens | Higher — runs its own LLM |
| Multi-step reasoning? | No — one tool call at a time | Yes — chains tool calls |
| Best for | Data fetching, CRUD, lookups, metrics | Complex workflows, investigation, analysis |

**Rule of thumb**: If the task just needs **data** (fetch incidents, query
metrics, list apps), use an MCP server.  If it needs **reasoning** (investigation,
analysis, multi-step workflows), use an ADK agent.

---

## Success Criteria

- **SC-001**: MCP server starts and responds to `tools/list` and `tools/call` JSON-RPC requests
- **SC-002**: All tools return structured JSON with correct field types
- **SC-003**: Agent guide is auto-discovered and injected into Super Agent's system prompt
- **SC-004**: Tool schemas pass Anthropic compliance validation (no `default`, `$ref`, etc.)
- **SC-005**: Large datasets use `table_data` contract → hook strips rows → UI renders full table
- **SC-006**: Health check at `/health` returns server name, version, and tool list
- **SC-007**: Server is registered in Super Agent's `mcp_servers.yml` or Redis config
