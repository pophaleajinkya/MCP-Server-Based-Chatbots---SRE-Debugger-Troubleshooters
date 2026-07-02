# MAOF → MCP Conversion Manifest
> Agent instructions for converting a Walmart MAOF (LangGraph) agent into a FastMCP server.
> Feed this file directly to an AI agent as its system prompt or task instructions.

---

## Context — What You Are Converting

A **MAOF agent** is a LangGraph-based Python service with:
- A `parse_query` node that uses an internal LLM (Azure OpenAI) to extract intent + parameters from natural language
- A routing node that sends the parsed intent to one of N fetch nodes
- N fetch nodes that each call a downstream service (SRE-OPS, DX Console, Azure, etc.)
- A `format_response` node that builds a unified `AgentResponse`
- FastAPI endpoints that accept `{"session_id": "...", "query": "..."}` as input

An **MCP server** exposes those same service calls as discrete, typed, stateless tools.
The intelligence moves from inside the agent to the client LLM (ADK or Claude).
The service layer is **reused unchanged**.

---

## What to Convert — Core Tools Only

Only convert the **fetch nodes** — the parts that call downstream services.
**Do NOT convert:**
- `parse_query` node → dropped (client LLM handles NL → params)
- routing / conditional edges → dropped (client LLM picks tool)
- `format_response` node → dropped (each tool returns its own dict)
- Agent state (`TypedDict`) → dropped (MCP is stateless, no shared state)
- Session management (`session_id`, Redis, conversation history) → dropped
- `QueryRequest` input model → dropped
- `AgentResponse` output model → dropped

Each **routing branch after parse_query = one MCP tool** with explicit typed parameters.

---

## Required Folder Structure

When creating the MCP layer, use this structure inside the **existing project**:

```
src/
├── mcp_models/                        ← Pydantic schemas for MCP tools
│   ├── __init__.py                    ← Re-export all models
│   ├── base.py                        ← MCPInputBase, MCPOutputBase, BaseDepsOutput
│   └── <domain>_models.py             ← One file per service domain
│
└── mcp_server/                        ← FastMCP server + tools
    ├── server.py                      ← FastMCP instance (import tools AFTER this)
    ├── resources_and_prompts.py       ← @mcp.resource + @mcp.prompt
    └── tools/
        └── <domain>.py               ← One file per service domain (@mcp.tool decorators)
```

The **existing** `src/services/` layer is **not touched**. Tools call it directly.

---

## Conversion Rules

### RULE 1 — One routing branch = one MCP tool
Each distinct service call (differentiated by platform, direction, service type) becomes its own tool.
Never bundle variants with optional/conditional parameters.

```
# MAOF: one endpoint, direction= param
POST /dependencies?direction=upstream|downstream

# MCP: two tools
fetch_<platform>_upstream_dependencies(...)
fetch_<platform>_downstream_dependencies(...)
```

### RULE 2 — Tool function signature = only the params the service needs
Remove `session_id`, `query`, `direction`, `service_type` from inputs.
The tool name encodes direction and type — not the parameters.

```python
# WRONG — MAOF-style
async def fetch_dependencies(query: str, session_id: str, direction: str) -> dict:

# CORRECT — MCP-style
async def fetch_wcnp_upstream_dependencies(app_name: str, namespace: str) -> dict:
```

### RULE 3 — Tools are thin; no LLM inside
```python
@mcp.tool(name="fetch_wcnp_upstream_dependencies", description="...")
async def fetch_wcnp_upstream_dependencies(app_name: str, namespace: str) -> dict:
    try:
        result = await sre_ops_service.fetch_upstream(app_name, namespace)
        return {"status": "success", "app_name": app_name, "namespace": namespace,
                "direction": "upstream", "dependencies": result, "total_count": len(result),
                "message": f"Found {len(result)} upstream dependencies"}
    except Exception as e:
        return {"status": "error", "app_name": app_name, "namespace": namespace,
                "direction": "upstream", "dependencies": [], "total_count": 0, "error": str(e)}
```

### RULE 4 — Always return a status dict; never raise
- Success: `{"status": "success", <echo input params>, <domain fields>, "message": "..."}`
- Error:   `{"status": "error",   <echo input params>, "error": str(e), <empty domain fields>}`
- Always echo input parameters so the client can correlate multi-tool calls.

### RULE 5 — Tool description format (≤ 8 lines)
```
Line 1: What the tool does.
Line 2: Domain note (e.g. "Upstream = services that call INTO this app").
Line 3: When to use it (vs. related tools).
Line 4+: Parameters: name — type hint, e.g. 'example'
```
No JSON examples in descriptions. No prose > 8 lines.

---

## Schema Rules (Anthropic + ADK Hard Constraints)

Anthropic's JSON Schema validator and ADK enforce these at runtime.
Violations are **silent gateway rejections** — not Python errors at startup.

### RULE S1 — Max 2 levels of hierarchy in input AND output schemas
ADK supports only 2 levels of property nesting in tool schemas.
Anthropic's validator rejects schemas deeper than 2 levels.

```
Level 1: root object properties  { app_name, namespace, ... }
Level 2: properties of a direct child object or list item  { name, type, ... }
Level 3+: FORBIDDEN
```

Nested Pydantic models generate `$defs` + `$ref` chains — each hop is one level.
Use `list[dict]` instead of `list[NestedModel]` when items have variable shape.
Flatten fields directly into the input model instead of composing sub-models.

### RULE S2 — No Optional[Any] or Dict[str, Any]
`Optional[Any]` → `{}` in schema (LLM gets no guidance). Always use `Optional[str]`, `Optional[int]`, etc.
`Dict[str, Any]` → `{}`. Replace with explicit typed fields or `list[dict]`.

### RULE S3 — No enums in schemas
Enums generate `$defs` + `$ref`. Use plain `str` and document allowed values in `description`.
```python
# WRONG
class Direction(str, Enum): upstream = "upstream"
direction: Direction

# CORRECT
direction: str = Field("", description="upstream or downstream")
```

### RULE S4 — No Union / anyOf / oneOf / allOf on top-level fields
Use separate tool models per variant instead of union types.

### RULE S5 — No nullable: true
Use `Optional[T]` → generates `{"anyOf": [{"type":"T"},{"type":"null"}]}` — valid.
Never use `Field(..., nullable=True)`.

### RULE S6 — No field aliases
```python
# WRONG
app_name: str = Field(..., alias="appName")

# CORRECT
app_name: str = Field(...)   # client passes app_name directly
```
Aliases cause schema key / runtime argument mismatch in FastMCP.

### RULE S7 — Description length limits
| Location | Max chars | Format |
|---|---|---|
| Input field `description` | 60 | `"noun phrase, e.g. 'value'"` |
| Output field `description` | 40 | `"noun phrase"` |
| Class docstring | 80 | `"Input: one-line summary."` |
| Status/enum-like field | 30 | `"success or error"` |

---

## Pydantic Base Classes

Use these base classes. They are already defined in `src/mcp_models/base.py`.

```python
class MCPInputBase(BaseModel):
    """Base for MCP tool input models — strict, no extra fields."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    # → "additionalProperties": false in schema

class MCPOutputBase(BaseModel):
    """Base for MCP tool output models — permissive, passthrough OK."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

class BaseDepsOutput(MCPOutputBase):
    """Common fields for dependency-fetch tools."""
    status: str = Field("", description="success or error")
    direction: str = Field("", description="upstream or downstream")
    dependencies: list[dict] = Field(default_factory=list, description="Dependency list")
    total_count: int = Field(0, description="Total dependencies found")
    message: str = Field("", description="Summary message")
    error: str = Field("", description="Error detail when status=error")
```

**Input models** → inherit `MCPInputBase`
**Output models** → inherit `MCPOutputBase` or `BaseDepsOutput`
**Do NOT** add `$schema` to `json_schema_extra` — the base already handles it.

---

## Server Bootstrap

`src/mcp_server/server.py` — create the FastMCP instance here, import tools after.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "<agent-name>",
    streamable_http_path="/",
    stateless_http=True,          # no session-ID — Istio-friendly
    instructions="<compact tool guide string>"
)

# Import AFTER mcp is defined — @mcp.tool decorators register at import time
from src.mcp_server.tools import domain_a, domain_b, domain_c  # noqa
from src.mcp_server import resources_and_prompts               # noqa
```

Mount in the existing FastAPI `main.py` — **additive, never replace existing endpoints**:

```python
from contextlib import asynccontextmanager
from src.mcp_server.server import mcp

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield

app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())
# existing MAOF endpoints remain unchanged below
```

---

## Resource and Prompt Rules

### Add one `@mcp.resource` as an agent guide
Register a resource at `<agent-name>://agent-guide` that returns a markdown decision tree:
- Which tool to call for which scenario
- What parameters are required per path
- Pre-step hints (e.g. "if no app name, call list_X first")
- Domain semantics (upstream vs downstream)

The resource is loaded by ADK at session start — not triggered per query.
It replaces the routing logic that was inside `_route_after_parse`.

### Add `@mcp.prompt` for every multi-tool workflow
Any workflow requiring 2+ tools in sequence gets a prompt template.
The prompt tells the client LLM which tools to call and how to combine results.
MAOF did multi-step work inside a single graph — MCP externalises it here.

```python
@mcp.resource("<agent-name>://agent-guide")
def agent_guide() -> str:
    return _AGENT_GUIDE_MARKDOWN

@mcp.prompt("trace_<platform>_app")
def trace_platform_app(param1: str, param2: str) -> str:
    return f"Steps:\n1. Call tool_A(...)\n2. Call tool_B(...)\n3. Summarise results."
```

---

## Schema Validation — Run Before Committing Any Model

```python
import json

def validate_mcp_schema(model_cls, is_input: bool = True):
    schema = model_cls.model_json_schema()
    s = json.dumps(schema)

    assert schema.get("type") == "object", "Root must be type:object"
    assert "nullable" not in s, "Use Optional[T], not nullable:true"
    if is_input:
        assert schema.get("additionalProperties") == False, "Inputs need additionalProperties:false"

    props = schema.get("properties", {})
    for field_name, field_schema in props.items():
        desc = field_schema.get("description", "x")
        limit = 60 if is_input else 40
        assert len(desc) <= limit, f"{field_name}.description too long ({len(desc)} > {limit})"
        # Check max 2 levels
        if "properties" in field_schema:
            for sub_name, sub_schema in field_schema["properties"].items():
                assert "properties" not in sub_schema, \
                    f"3-level nesting detected: root → {field_name} → {sub_name} → ..."
```

---

## Conversion Checklist

Run through this for every MAOF agent being converted:

**Structural**
- [ ] Every routing branch mapped to one MCP tool
- [ ] All LangGraph nodes removed from tool logic
- [ ] Agent state TypedDict removed
- [ ] `session_id` and `query` removed from all tool inputs
- [ ] `AgentResponse` / `QueryRequest` replaced with per-tool dicts
- [ ] Service layer unchanged and called directly from tools

**Models**
- [ ] Input models inherit `MCPInputBase`
- [ ] Output models inherit `MCPOutputBase` or `BaseDepsOutput`
- [ ] No field aliases
- [ ] No `Dict[str, Any]` or bare `Any`
- [ ] No `Optional[Any]` — always `Optional[T]`
- [ ] No enums — plain `str` with description
- [ ] No `Union` / `anyOf` / `oneOf` / `allOf` on root fields
- [ ] Max 2 levels of schema nesting (verified by validator above)
- [ ] All field descriptions within length limits

**Tools**
- [ ] No LLM calls inside any tool
- [ ] All tools return error dict instead of raising
- [ ] Input params echoed in output dict

**Server**
- [ ] `FastMCP` uses `stateless_http=True`
- [ ] Tool modules imported after `mcp` is defined
- [ ] Mounted at `/mcp` — existing MAOF endpoints untouched
- [ ] `mcp.session_manager` runs inside FastAPI lifespan

**Resource + Prompts**
- [ ] `@mcp.resource("<name>://agent-guide")` registered
- [ ] `@mcp.prompt` for every multi-tool workflow

---

## Reference — Dependency Agent Conversion (Worked Example)

| MAOF component | MCP equivalent |
|---|---|
| `POST /dependencies` (WCNP) | `list_apps_in_namespace`, `fetch_wcnp_upstream_dependencies`, `fetch_wcnp_downstream_dependencies` |
| `POST /dependencies/oneops` | `fetch_oneops_upstream_dependencies`, `fetch_oneops_downstream_dependencies` |
| `POST /dependencies/managed-service` (cassandra) | `fetch_cassandra_upstream_dependencies` |
| `POST /dependencies/managed-service` (meghacache) | `fetch_meghacache_upstream_dependencies` |
| `POST /dependencies/managed-service` (cosmos) | `fetch_cosmos_upstream_dependencies` |
| `POST /dependencies/managed-service` (sqlserver) | `fetch_sqlserver_upstream_dependencies` |
| `parse_query` node | Dropped |
| `_route_after_parse` | Dropped → replaced by `dependency://agent-guide` resource |
| `format_response` node | Dropped → each tool returns its own dict |
| `DependencyAgentState` | Dropped |
| `QueryRequest` | Dropped |
| `AgentResponse` | Dropped |
| `src/services/` | Unchanged |

Implemented models live in `src/mcp_models/`.
Implemented tools live in `src/mcp_server/tools/`.
