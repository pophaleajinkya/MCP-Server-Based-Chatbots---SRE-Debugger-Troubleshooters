# MCP Tool Schema Compatibility — Anthropic Reserved Keywords & Forbidden Fields

How to write MCP tool schemas that pass Anthropic's strict JSON Schema
validation, and how to fix tools that fail at startup.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Anthropic Reserved Keywords](#2-anthropic-reserved-keywords)
3. [The `default` Key — Most Common Violation](#3-the-default-key--most-common-violation)
4. [How super-agent Detects Violations](#4-how-super-agent-detects-violations)
5. [How to Fix — Schema Pattern](#5-how-to-fix--schema-pattern)
6. [How to Fix — FastMCP / Pydantic Auto-Generated Schemas](#6-how-to-fix--fastmcp--pydantic-auto-generated-schemas)
7. [Other Forbidden Schema Fields](#7-other-forbidden-schema-fields)
8. [Tool Naming Rules](#8-tool-naming-rules)
9. [Validation Endpoint](#9-validation-endpoint)
10. [Quick Reference — Dos and Don'ts](#10-quick-reference--dos-and-donts)

---

## 1. The Problem

Anthropic uses **JSON Schema draft 2020-12** for tool `inputSchema` validation.
Their validator is stricter than the JSON Schema specification itself — it
rejects certain valid JSON Schema keywords that could conflict with Anthropic's
internal processing grammars.

When a tool schema contains a forbidden keyword, the Anthropic API returns a
schema validation error and **refuses to process the entire tool list**. This
means one bad tool blocks ALL tools from working.

```
400 Bad Request — tools.3.input_schema: Additional properties are not allowed ('default' was unexpected)
```

super-agent detects these issues at startup and logs warnings, but Anthropic's
API will hard-reject the request at runtime.

---

## 2. Anthropic Reserved Keywords

### Forbidden Names (Tool Names & Parameter Names)

Anthropic reserves these names — they **cannot** be used as tool names or
parameter names:

| Reserved Name | Scope |
|---|---|
| `default` | Tool names, parameter names |
| `anthropic` | Tool names, parameter names |
| `claude` | Tool names, parameter names |

### Tool Name Formatting Rules

| Rule | Requirement |
|---|---|
| Case | Lowercase only |
| Characters | Letters, numbers, hyphens, and underscores |
| Length | 64 characters or fewer |
| Uniqueness | Must be unique across ALL MCP servers connected to super-agent |

---

## 3. The `default` Key — Most Common Violation

The most frequent schema violation is having a `"default"` **key** inside a
property definition in `inputSchema`. Anthropic's validator rejects the
`"default"` key entirely — regardless of what value it holds.

### Why it happens

JSON Schema draft 2020-12 supports `"default"` as an annotation keyword.
Most schema generators (Pydantic, FastMCP, OpenAPI) automatically include it
when a parameter has a default value. But Anthropic strips or rejects it.

### What triggers it

Any `"default"` key anywhere in the `inputSchema` object tree:

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "organization": {
        "type": "string",
        "description": "O2 org ID",
        "default": "default"          ← REJECTED by Anthropic
      },
      "limit": {
        "type": "integer",
        "description": "Max results",
        "default": 10                  ← REJECTED by Anthropic
      },
      "verbose": {
        "type": "boolean",
        "description": "Enable verbose output",
        "default": false               ← REJECTED by Anthropic
      }
    }
  }
}
```

**All three are rejected** — it doesn't matter whether the default value is a
string, integer, boolean, or null. The `"default"` **key** itself is forbidden.

---

## 4. How super-agent Detects Violations

### Startup Warning Scan

At startup, `factory.py` scans every MCP tool's `inputSchema` using
`find_suspicious_fields()` from `runner.py`:

```
File: src/app/services/runner.py (line 106)

_SUSPICIOUS_KEYS = {
    "default",                # annotation — Anthropic strict validator rejects it
    "definitions",            # replaced by $defs in draft 2020-12
    "$ref",                   # can cause issues with Anthropic's validator
    "id",                     # replaced by $id in draft 2020-12
    "$schema",                # not allowed inside sub-schemas
    "if", "then", "else",    # conditional keywords — often rejected
}
```

When violations are found, you'll see startup warnings like:

```
WARNING  Tool[3] 'execute_sql' — suspicious schema fields that Anthropic may reject:
    ['input_schema.properties.organization.default="default"',
     'input_schema.properties.limit.default=1000',
     'input_schema.properties.time_range.default="1h"']
```

### Runtime Error Detection

If a bad schema slips through to Anthropic, runner.py catches the API error and
logs the specific tool + suspicious fields to help you find the problem fast.

### Validation Endpoint

Use `POST /mcp/validate` to scan any MCP server before onboarding.
See [Section 9](#9-validation-endpoint) for details.

---

## 5. How to Fix — Schema Pattern

### The correct pattern

1. **Remove** the `"default"` key from the property definition
2. **Document** the default behavior in the `description` text
3. **Omit** the parameter from the `required` array (makes it optional)
4. **Handle** the default in your implementation logic

### Before (fails Anthropic validation)

```json
{
  "type": "object",
  "properties": {
    "namespace": {
      "type": "string",
      "description": "Kubernetes namespace"
    },
    "limit": {
      "type": "integer",
      "description": "Max results to return",
      "default": 10
    },
    "organization": {
      "type": "string",
      "description": "O2 org ID",
      "default": "default"
    }
  },
  "required": ["namespace"]
}
```

### After (passes Anthropic validation)

```json
{
  "type": "object",
  "properties": {
    "namespace": {
      "type": "string",
      "description": "Kubernetes namespace"
    },
    "limit": {
      "type": "integer",
      "description": "Max results to return. Defaults to 10 if not provided."
    },
    "organization": {
      "type": "string",
      "description": "O2 org ID. Defaults to 'default' if not provided."
    }
  },
  "required": ["namespace"]
}
```

### Implementation logic handles the default

```python
async def my_tool(namespace: str, limit: int = 0, organization: str = "") -> dict:
    # Handle defaults in code — NOT in the schema
    limit = limit or 10
    organization = organization or "default"
    ...
```

---

## 6. How to Fix — FastMCP / Pydantic Auto-Generated Schemas

FastMCP (used by `@mcp.tool` and `@provider.tool` decorators) auto-generates
`inputSchema` from Python function signatures via Pydantic's
`model_json_schema()`. **Any Python default value produces a `"default"` key
in the JSON Schema.**

### The problem

```python
@mcp.tool()
async def execute_sql(
    sql_query: str,
    organization: str = "default",    # ← Pydantic will emit "default": "default"
    limit: int = 1000,                # ← Pydantic will emit "default": 1000
    token: str = "",                  # ← Pydantic will emit "default": ""
) -> dict:
    ...
```

Generated `inputSchema`:
```json
{
  "properties": {
    "sql_query": {"type": "string"},
    "organization": {"type": "string", "default": "default"},
    "limit": {"type": "integer", "default": 1000},
    "token": {"type": "string", "default": ""}
  },
  "required": ["sql_query"]
}
```

All three `"default"` keys will be rejected by Anthropic.

### The fix

Remove the Python default value from the function signature so Pydantic does
not emit a `"default"` key. Move the default handling into the function body.

```python
@mcp.tool()
async def execute_sql(
    sql_query: str,
    organization: str,    # ← no default → no "default" key in schema
    limit: int,           # ← no default → no "default" key in schema
    token: str,           # ← no default → no "default" key in schema
) -> dict:
    """
    Execute SQL query.

    Parameters:
        sql_query:    SQL SELECT statement.
        organization: O2 org ID. Pass "default" for the default organization.
        limit:        Max rows. Pass 1000 for the default limit.
        token:        Auth token. Pass "" to use the server's default token.
    """
    # Handle defaults in implementation
    organization = organization or "default"
    limit = limit or 1000
    ...
```

### Important: Only change the MCP tool layer

If your MCP server has a service layer (e.g., `github_service.py`,
`o2_service.py`) that other Python code calls internally, **keep the defaults
in the service layer**. Only the `@mcp.tool` decorated functions need their
defaults removed.

```
┌─────────────────────────┐     ┌─────────────────────────┐
│  MCP Tool Layer          │     │  Service Layer           │
│  @mcp.tool decorated     │     │  Internal Python API     │
│                          │     │                          │
│  NO Python defaults      │────▶│  KEEP Python defaults    │
│  (avoids schema issue)   │     │  (used by other code)    │
│                          │     │                          │
│  organization: str       │     │  organization: str = ""  │
│  limit: int              │     │  limit: int = 1000       │
└─────────────────────────┘     └─────────────────────────┘
```

---

## 7. Other Forbidden Schema Fields

Beyond `"default"`, these JSON Schema keywords are also rejected or cause
issues with Anthropic's validator:

| Keyword | Status | Replacement |
|---|---|---|
| `"default"` | **Rejected** | Document in `description`, handle in code |
| `"definitions"` | **Rejected** | Use `"$defs"` (JSON Schema draft 2020-12) |
| `"$ref"` | **Rejected** | Inline the referenced schema directly |
| `"id"` | **Rejected** | Use `"$id"` (draft 2020-12) |
| `"$schema"` | **Rejected** | Remove — not allowed inside sub-schemas |
| `"if"` / `"then"` / `"else"` | **Rejected** | Flatten into separate properties |

### Top-level `type` requirement

The `inputSchema` top-level `type` **must** be `"object"`. Never use `"array"`
or `"string"` at the top level.

```json
// ❌ Rejected
{ "type": "array", "items": { "type": "string" } }

// ✅ Correct
{ "type": "object", "properties": { "items": { "type": "array", "items": { "type": "string" } } } }
```

---

## 8. Tool Naming Rules

| Rule | Example |
|---|---|
| Lowercase only | `check_health` ✅ &nbsp; `Check_Health` ❌ |
| Letters, numbers, hyphens, underscores | `wcnp-check-health` ✅ &nbsp; `wcnp.check.health` ❌ |
| 64 characters max | Keep it concise |
| No reserved words | `default_check` ❌ &nbsp; `anthropic_tool` ❌ &nbsp; `claude_helper` ❌ |
| Unique across all MCP servers | No two servers can register `list_items` |

---

## 9. Validation Endpoint

super-agent exposes `POST /mcp/validate` to pre-check any MCP server's schemas
before connecting it to production.

```bash
curl -X POST http://localhost:8010/mcp/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://my-mcp-server.stage.walmart.com/mcp/",
    "transport": "streamable_http"
  }'
```

Response includes per-tool validation results:

```json
{
  "tools": [
    {
      "name": "execute_sql",
      "status": "warning",
      "issues": [
        "Suspicious field: input_schema.properties.organization.default='default'",
        "Suspicious field: input_schema.properties.limit.default=1000"
      ]
    }
  ],
  "summary": {
    "tools_total": 11,
    "tools_ok": 9,
    "tools_warnings": 2,
    "overall_status": "warning"
  }
}
```

**Run this before every deployment** to catch schema issues before they reach
Anthropic's API.

---

## 10. Quick Reference — Dos and Don'ts

### Schema Properties

```
✅ DO                                          ❌ DON'T
─────────────────────────────────────          ─────────────────────────────────────
"count": {                                     "count": {
  "type": "integer",                             "type": "integer",
  "description": "Items to fetch.                "description": "Items to fetch",
    Defaults to 10 if not provided."             "default": 10
}                                              }

"required": ["namespace"]                      "required": ["namespace", "count"]
  (omit optional params)                         (don't force params that have defaults)
```

### Python Function Signatures (FastMCP)

```
✅ DO                                          ❌ DON'T
─────────────────────────────────────          ─────────────────────────────────────
@mcp.tool()                                    @mcp.tool()
async def my_tool(                             async def my_tool(
    required_param: str,                           required_param: str,
    optional_param: str,                           optional_param: str = "default",
    limit: int,                                    limit: int = 100,
) -> dict:                                     ) -> dict:
    optional_param = optional_param or "default"
    limit = limit or 100
```

### Descriptions

```
✅ DO                                          ❌ DON'T
─────────────────────────────────────          ─────────────────────────────────────
"O2 org ID. Pass 'default' for the            "O2 org ID (default: 'default')"
 default organization."                          ↑ Technically fine, but the schema
                                                   still has "default" key = rejected

"Max rows. Defaults to 1000 if not             (no description — LLM won't know
 provided."                                      what value to pass)
```

### Service Layer vs MCP Tool Layer

```
✅ DO                                          ❌ DON'T
─────────────────────────────────────          ─────────────────────────────────────
Keep defaults in the service layer:            Remove defaults from the service layer
  class MyService:                               (breaks internal Python callers)
    def query(self, org="default"): ...

Remove defaults from MCP tool layer:           Keep defaults in MCP tool layer
  @mcp.tool()                                    (produces "default" key in schema)
  async def query(org: str): ...
```

---

## Appendix: Grep Commands for Auditing

Find all `"default"` key violations in an MCP server's tool functions:

```bash
# Find Python defaults in @mcp.tool / @provider.tool decorated functions
grep -n '= "default"' src/providers/*.py

# Find all parameter defaults (broader — review each manually)
grep -n 'def.*=.*:' src/providers/*.py

# Check generated schemas at runtime (start the server, then curl tools/list)
curl -s http://localhost:8999/mcp/ \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  -H 'Content-Type: application/json' | python -m json.tool | grep '"default"'
```

---

## Appendix: Files in super-agent That Enforce These Rules

| File | What it does |
|---|---|
| `src/app/services/runner.py` (line 106) | Defines `_SUSPICIOUS_KEYS` and `find_suspicious_fields()` |
| `src/app/factory.py` (line 157) | Scans all tools at startup, logs warnings for violations |
| `src/app/routers/mcp_validate.py` | `POST /mcp/validate` endpoint for pre-deployment checks |
