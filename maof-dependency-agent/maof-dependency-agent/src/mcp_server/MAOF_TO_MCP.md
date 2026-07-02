# MAOF Agent → MCP Server Conversion

This document records exactly how the `dependency-agent` MAOF agent was converted
to an MCP server.  Use it as a reference when converting other MAOF agents.

---

## The fundamental shift

| | MAOF agent | MCP server |
|---|---|---|
| **Intelligence lives** | Inside the agent (LLM extracts params) | On the client (ADK/Claude decides) |
| **Input** | Natural language `query` + `session_id` | Explicit typed parameters per tool |
| **LLM usage** | Yes — `_parse_query` node uses Azure OpenAI | No — tools are pure service calls |
| **Routing** | LangGraph graph (`parse → fetch → format`) | Client LLM picks the right tool |
| **State** | `DependencyAgentState` TypedDict | Stateless — no shared state between calls |
| **Session** | `session_id` + conversation history via Redis | No session — each tool call is independent |
| **Entry points** | 3 FastAPI endpoints | 9 MCP tools |

---

## What the MAOF agent looked like

```
POST /dependencies           ← WCNP natural-language query
POST /dependencies/oneops    ← OneOps natural-language query
POST /dependencies/managed-service  ← Managed service natural-language query

Each endpoint:
  QueryRequest(session_id, query)
      │
      ▼
  get_conversation_history(session_id)   ← Redis / conversation API
      │
      ▼
  DependencyAgent.process_query()        ← LangGraph workflow
      │
      ▼ LangGraph graph:
  parse_query (LLM: extract params from NL query + history)
      ├─► fetch_wcnp            → merge_service → SRE-OPS + Topology
      ├─► suggest_wcnp          → DX Console
      ├─► fetch_oneops          → SRE-OPS
      ├─► fetch_managed_service → SRE-OPS
      └─► format_response
              │
             END
      │
      ▼
  AgentResponse(status, query, data, error)
```

---

## What the MCP server looks like

```
POST /mcp/   ← single JSON-RPC endpoint (FastMCP stateless HTTP)

Client LLM reads tool list + resource guide, picks tool, calls it directly:

  list_apps_in_namespace(namespace)
      → DX Console (_get_apps_for_namespace)

  fetch_wcnp_upstream_dependencies(app_name, namespace)
  fetch_wcnp_downstream_dependencies(app_name, namespace)
      → merge_service → SRE-OPS

  fetch_oneops_upstream_dependencies(org, platform, assembly)
  fetch_oneops_downstream_dependencies(org, platform, assembly)
      → sre_ops_service directly

  fetch_cassandra_upstream_dependencies(assembly, platform)
  fetch_meghacache_upstream_dependencies(assembly, platform)
  fetch_cosmos_upstream_dependencies(resource_group, subscription_id, database_name)
  fetch_sqlserver_upstream_dependencies(resource_group, subscription_id, database_name)
      → sre_ops_service directly
```

---

## How each MAOF component mapped to MCP

### Endpoints → Tools

Every MAOF endpoint was one coarse-grained entry point that handled all cases internally.
In MCP, each distinct operation becomes its own tool with explicit parameters.

| MAOF endpoint | MAOF internal routing | MCP tool |
|---|---|---|
| `POST /dependencies` | `suggest_wcnp` (namespace only) | `list_apps_in_namespace(namespace)` |
| `POST /dependencies` | `fetch_wcnp` direction=upstream | `fetch_wcnp_upstream_dependencies(app_name, namespace)` |
| `POST /dependencies` | `fetch_wcnp` direction=downstream | `fetch_wcnp_downstream_dependencies(app_name, namespace)` |
| `POST /dependencies/oneops` | `fetch_oneops` direction=upstream | `fetch_oneops_upstream_dependencies(org, platform, assembly)` |
| `POST /dependencies/oneops` | `fetch_oneops` direction=downstream | `fetch_oneops_downstream_dependencies(org, platform, assembly)` |
| `POST /dependencies/managed-service` | `fetch_managed_service` type=cassandra | `fetch_cassandra_upstream_dependencies(assembly, platform)` |
| `POST /dependencies/managed-service` | `fetch_managed_service` type=meghacache | `fetch_meghacache_upstream_dependencies(assembly, platform)` |
| `POST /dependencies/managed-service` | `fetch_managed_service` type=cosmos | `fetch_cosmos_upstream_dependencies(resource_group, subscription_id, database_name)` |
| `POST /dependencies/managed-service` | `fetch_managed_service` type=sqlserver | `fetch_sqlserver_upstream_dependencies(resource_group, subscription_id, database_name)` |

**Rule:** One MAOF routing branch = one MCP tool.
Never bundle multiple routing branches into a single tool with optional params.

---

### LangGraph nodes → removed

The entire LangGraph workflow was removed from the MCP layer.
The nodes' logic was NOT ported — it moved to the **client LLM**.

| LangGraph node | What it did | MCP equivalent |
|---|---|---|
| `parse_query` | LLM extracts params from NL query | Client LLM (no code needed in server) |
| `fetch_wcnp` | Calls `merge_service` | Body of `fetch_wcnp_upstream/downstream_dependencies` |
| `suggest_wcnp` | Calls DX Console | Body of `list_apps_in_namespace` |
| `fetch_oneops` | Calls `sre_ops_service` | Body of `fetch_oneops_upstream/downstream_dependencies` |
| `fetch_managed_service` | Calls `sre_ops_service` | Body of `fetch_*_upstream_dependencies` per type |
| `format_response` | Builds `AgentResponse` | Each tool returns its own dict directly |
| `_route_after_parse` | Routes based on `next_step` | Client LLM picks the tool |

---

### DependencyAgentState → removed

The TypedDict state with 20+ fields was eliminated.
State only existed to carry parameters between LangGraph nodes.
In MCP, each tool takes exactly the parameters it needs — no shared state.

```python
# MAOF: one monolithic state shared across all nodes
class DependencyAgentState(TypedDict):
    query: str
    session_id: str
    query_type: Optional[str]
    app_name: Optional[str]
    namespace: Optional[str]
    org: Optional[str]
    platform: Optional[str]
    assembly: Optional[str]
    service_type: Optional[str]
    resource_group: Optional[str]
    ...20 more fields

# MCP: each tool declares only what it needs
async def fetch_wcnp_upstream_dependencies(app_name: str, namespace: str) -> dict: ...
async def fetch_oneops_upstream_dependencies(org: str, platform: str, assembly: str) -> dict: ...
async def fetch_cosmos_upstream_dependencies(resource_group: str, subscription_id: str, database_name: str) -> dict: ...
```

---

### Service layer → reused as-is

The service layer was **not changed**.  MCP tools call it directly.

| Service function | Used by MAOF via | Used by MCP tool directly |
|---|---|---|
| `_get_apps_for_namespace()` | `_suggest_wcnp` node | `list_apps_in_namespace` tool |
| `merge_service.get_upstream_and_downstream_dependencies()` | `_fetch_wcnp` node | `fetch_wcnp_upstream/downstream_dependencies` tools |
| `sre_ops_service.fetch_oneops_upstream_dependencies()` | `_fetch_oneops` node | `fetch_oneops_upstream_dependencies` tool |
| `sre_ops_service.fetch_oneops_downstream_dependencies()` | `_fetch_oneops` node | `fetch_oneops_downstream_dependencies` tool |
| `sre_ops_service.fetch_managed_service_upstream_dependencies()` | `_fetch_managed_service` node | All 4 managed service tools via `_fetch()` helper |

**Rule:** The service layer is the boundary.  MCP tools sit above it; the service layer is unchanged below it.

---

### MAOF input model → MCP tool parameters

```python
# MAOF: one request model for all endpoints
class QueryRequest(BaseModel):
    session_id: str     # ← not needed in MCP (no session)
    query: str          # ← natural language — not needed in MCP (client LLM extracts params)

# MCP: explicit params per tool, no model needed for simple tools
async def list_apps_in_namespace(namespace: str) -> dict:
async def fetch_wcnp_upstream_dependencies(app_name: str, namespace: str) -> dict:
```

`session_id` was dropped entirely — MCP is stateless.
`query` (natural language) was dropped — the client LLM owns NL→params extraction.

---

### MAOF output model → MCP tool return dict

```python
# MAOF: one response model wrapping everything
class AgentResponse(BaseModel):
    status: str
    query: str       # ← echoes back the NL query
    data: Optional[Dict[str, Any]]
    error: Optional[str]

# MCP: each tool returns a flat dict with only its own fields
return {
    "status": "success",
    "app_name": app_name,
    "namespace": namespace,
    "direction": "upstream",
    "dependencies": upstream,
    "source_breakdown": breakdown,
    "total_count": len(upstream),
    "message": f"Found {len(upstream)} upstream dependencies...",
}
```

`query` was dropped — tools don't echo back the natural language.
`data: Dict[str, Any]` was replaced with flat typed fields per tool.

---

### What was added: resources and prompts

MAOF had no equivalent. These are MCP-native concepts.

**Resource** — static context the client LLM loads once at startup:

```python
@mcp.resource("dependency://agent-guide")
def agent_guide() -> str:
    """Decision tree: which tool to call for which scenario."""
    return _AGENT_GUIDE   # markdown with tool selection logic
```

The resource replaces the routing logic that lived in `_route_after_parse` and
`PARAMETER_EXTRACTION_PROMPT`.  Instead of the agent routing internally, the
client LLM reads the guide and decides which tool to call.

**Prompt** — reusable template for multi-tool workflows:

```python
@mcp.prompt("trace_wcnp_app")
def trace_wcnp_app(app_name: str, namespace: str) -> str:
    """Returns instructions to call upstream + downstream tools and summarise."""
    ...
```

MAOF implicitly did both calls in `_fetch_wcnp` (direction=None).
In MCP, the client LLM makes two separate tool calls; the prompt template
tells it to do so and how to summarise the combined result.

---

## Complete file mapping

| MAOF file | MCP file | Relationship |
|---|---|---|
| `main.py` (`/dependencies`) | `src/mcp_server/tools/wcnp.py` | Same service calls, no LLM |
| `main.py` (`/dependencies/oneops`) | `src/mcp_server/tools/oneops.py` | Same service calls, no LLM |
| `main.py` (`/dependencies/managed-service`) | `src/mcp_server/tools/managed_service.py` | One tool per service type |
| `src/agent/agent.py` | `src/mcp_server/server.py` + tools | LangGraph removed; tools = node bodies |
| `src/models/query.py` (`QueryRequest`) | *(removed)* | Replaced by explicit tool params |
| `src/models/agent_response.py` (`AgentResponse`) | *(removed)* | Each tool returns its own dict |
| `src/models/agent_state.py` (`DependencyAgentState`) | *(removed)* | No shared state needed |
| `src/prompts/system_prompts.py` | `src/mcp_server/resources_and_prompts.py` | Resource = guide; Prompt = workflow template |
| `src/services/sre_ops_service.py` | *unchanged* | Reused directly |
| `src/services/merge_service.py` | *unchanged* | Reused directly |

---

## MCP server bootstrap (main.py)

```python
# 1. Create FastMCP instance with server instructions
mcp = FastMCP("dependency-agent", streamable_http_path="/", stateless_http=True,
              instructions="...")

# 2. Import tool modules after mcp is defined (decorators register at import time)
from src.mcp_server.tools import wcnp, oneops, managed_service
from src.mcp_server import resources_and_prompts

# 3. Mount into FastAPI alongside MAOF endpoints
_mcp_sub_app = mcp.streamable_http_app()
app.mount("/mcp", _mcp_sub_app)

# 4. Run session manager in FastAPI lifespan
@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield
```

---

## Conversion checklist for other agents

- [ ] Identify all LangGraph routing branches → one MCP tool each
- [ ] Identify service functions called by each node → call them directly in the tool
- [ ] Remove LLM from tools — the client LLM owns parameter extraction
- [ ] Remove `session_id` and `query` from tool inputs
- [ ] Replace monolithic state TypedDict with per-tool explicit parameters
- [ ] Replace `AgentResponse` wrapper with flat typed dict per tool
- [ ] Add a `dependency://agent-guide` resource with tool selection decision tree
- [ ] Add `@mcp.prompt` for any workflow that requires calling 2+ tools in sequence
- [ ] For tools with multiple variants (e.g. 4 managed service types): one tool per variant
- [ ] Mount at `/mcp` in FastAPI and run `mcp.session_manager` in lifespan
