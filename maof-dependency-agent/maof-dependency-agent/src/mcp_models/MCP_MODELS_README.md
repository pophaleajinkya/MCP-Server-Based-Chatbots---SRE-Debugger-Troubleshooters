# MAOF → MCP Model Conversion Rules

Use this document every time you convert a MAOF agent to an MCP server.
The rules below are derived from Anthropic's JSON Schema (draft 2020-12) requirements
for `input_schema` and `output_schema`.

---

## TL;DR — The 5 conversion rules

| # | MAOF pattern | MCP replacement |
|---|---|---|
| 1 | `BaseModel` | `MCPInputBase` (input) / `MCPOutputBase` (output) |
| 2 | `Field(..., alias="camelCase")` | `Field(...)` — no aliases, use `snake_case` |
| 3 | `Dict[str, Any]` | Separate typed fields, or a separate model per variant |
| 4 | `Optional[Any]` | `Optional[str]` / `Optional[int]` / etc. — always concrete |
| 5 | Long multi-line descriptions | Single-line: `"<noun>, e.g. '<value>'"` ≤ 60 chars |

---

## Rule 1 — Base class

**Input models** must inherit from `MCPInputBase`.
This automatically injects:
- `"additionalProperties": false` — via `extra="forbid"`
- `"$schema": "https://json-schema.org/draft/2020-12/schema"`

**Output models** must inherit from `MCPOutputBase` (or `BaseDepsOutput` for dependency tools).
This automatically injects:
- `"additionalProperties": true` — via `extra="allow"` (SRE-OPS passthrough)
- `"$schema": "https://json-schema.org/draft/2020-12/schema"`

```python
# BEFORE (MAOF)
class QueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    ...

# AFTER (MCP input)
class MyToolInput(MCPInputBase):
    ...

# AFTER (MCP output)
class MyToolOutput(MCPOutputBase):
    ...
```

---

## Rule 2 — No aliases

Aliases (`alias="toolName"`) cause a mismatch: the JSON schema uses the alias as the key,
but FastMCP passes arguments by Python field name.
Always use `snake_case` field names directly.

```python
# BEFORE (MAOF)
tool_name: str = Field(..., alias="toolName")
session_id: str = Field(..., alias="sessionId")

# AFTER (MCP)
tool_name: str = Field(...)      # key in schema = "tool_name"
session_id: str = Field(...)     # key in schema = "session_id"
```

---

## Rule 3 — No `Dict[str, Any]`

`Dict[str, Any]` generates `{}` in the schema — "accept anything".
The LLM gets no guidance on what to send.

**If the fields are always the same:** replace with explicit typed fields.

```python
# BEFORE (MAOF)
parameters: Dict[str, Any] = Field(default_factory=dict)

# AFTER (MCP) — explicit fields
app_name: str = Field(..., description="App name, e.g. 'payment-service'")
namespace: str = Field(..., description="Namespace, e.g. 'prod'")
```

**If different tools need different fields:** create one model per tool (see `managed_service_models.py`).
Never use `Optional` fields as a workaround — that pollutes `required` and confuses the LLM.

```python
# AFTER (MCP) — separate model per variant
class CassandraInput(MCPInputBase):
    assembly: str = Field(...)
    platform: str = Field(...)

class CosmosInput(MCPInputBase):
    resource_group: str = Field(...)
    subscription_id: str = Field(...)
    database_name: str = Field(...)
```

---

## Rule 4 — No `Optional[Any]`

`Optional[Any]` generates `{}` (unrestricted).
Always specify the actual type.

```python
# BEFORE (MAOF)
data: Optional[Any] = Field(None)

# AFTER (MCP)
data: Optional[str] = Field(None)           # if string
results: list[DependencyItem] = Field(...)  # if list of objects
count: Optional[int] = Field(None)          # if number
```

`Optional[str]` generates `{"anyOf": [{"type": "string"}, {"type": "null"}]}` —
valid draft 2020-12 (NOT `nullable: true`).

---

## Rule 5 — Normalize descriptions

Descriptions appear in the schema and are read by the LLM.
Keep them short, scannable, and functional.

| Location | Format | Max length |
|---|---|---|
| Input field | `"<noun phrase>, e.g. '<value>'"` | 60 chars |
| Output field | `"<noun phrase>"` | 40 chars |
| Enum/status field | `"success or error"` / `"upstream or downstream"` | 30 chars |
| Class docstring | `"Input: <one line>."` / `"Output: <one line>."` | 80 chars |

```python
# BEFORE (MAOF / verbose)
session_id: str = Field(
    ...,
    alias="session_id",
    description="Session identifier for tracking or fetching context from previous interactions",
)

# AFTER (MCP / normalized)
session_id: str = Field(..., description="Session ID, e.g. 'abc-123'")
```

**Never put JSON examples in docstrings** — they end up in `schema.description` and waste LLM tokens.
Put them in `#` comments above the class instead.

---

## Anthropic draft 2020-12 rules (hard requirements)

These will cause a gateway rejection if violated:

| Rule | Wrong | Correct |
|---|---|---|
| Root type | `"type": "string"` at root | `"type": "object"` at root |
| Nullable | `"nullable": true` | `{"anyOf": [{"type":"string"},{"type":"null"}]}` |
| Remote ref | `"$ref": "https://..."` | `"$ref": "#/$defs/..."` (local only) |
| Array items | `"items": ["string", "int"]` (tuple) | `"items": {"type": "string"}` |
| Extra fields | no constraint on inputs | `"additionalProperties": false` on inputs |

All of these are handled automatically by `MCPInputBase` / `MCPOutputBase`.

---

## Conversion checklist

Run this before registering any tool in FastMCP:

```python
import json
schema = MyToolInput.model_json_schema()
assert schema["type"] == "object"
assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
assert schema["additionalProperties"] == False          # inputs only
assert "nullable" not in json.dumps(schema)
assert "http" not in json.dumps(schema).replace("https://json-schema.org", "")
for field_name, field_schema in schema["properties"].items():
    assert len(field_schema.get("description", "x")) <= 60
```

Or run the audit script:
```bash
python -m pytest tests/ -k "mcp_schema"
```

---

## Quick file map

```
src/mcp_models/
├── __init__.py                  re-exports all models
├── base.py                      MCPInputBase, MCPOutputBase, DependencyItem,
│                                SourceBreakdown, BaseDepsOutput, StatusEnum, DirectionEnum
├── wcnp_models.py               ListAppsInput/Output, WcnpDepsInput/Output
├── oneops_models.py             OneOpsDepsInput/Output
├── managed_service_models.py    CassandraInput, MeghaCacheInput, CosmosInput,
│                                SqlServerInput, ManagedServiceOutput
└── MCP_MODELS_README.md         this file — conversion rules
```
