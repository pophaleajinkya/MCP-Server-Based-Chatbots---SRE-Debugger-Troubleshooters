# Tasks: MCP Server — Build Checklist

**Feature**: `mcp-server` | **Date**: 2026-04-02
**Spec**: `spec.md` | **Plan**: `plan.md`

> Checklist for building a new MCP server from scratch.  Each task is
> independently verifiable.  No LLM configuration needed.

---

## Scaffold

- [ ] Run `cookiecutter cookiecutter/mcp-server/` with your project details
- [ ] Copy `.env.example` to `.env`
- [ ] Fill in domain-specific config (API URLs, keys — NO LLM keys)
- [ ] `pip install -e .` — verify dependencies install

**Verify**: `python -c "from src.config import get_settings; print(get_settings().server_port)"`

---

## Configuration

- [ ] Add domain-specific settings to `src/config.py` (API URLs, timeouts)
- [ ] Add matching env vars to `.env` and `.env.example`
- [ ] No LLM env vars needed (no `CLAUDE_*`, no `OPENAI_*`)

**Verify**: `get_settings()` loads all values correctly.

---

## HTTP Client

- [ ] Create `src/services/api_client.py` — all network calls in one place
- [ ] Use `httpx.AsyncClient` with timeout + `verify=False`
- [ ] Handle errors: return `None` for 404, raise for 5xx
- [ ] Test client independently with mock HTTP responses

**Verify**: Client returns data when called with valid params.

---

## Service Layer

- [ ] Create `src/services/data_service.py` — business logic
- [ ] Service depends on client only (no MCP, no HTTP imports)
- [ ] Transform raw API data into clean domain objects
- [ ] Test service independently (mock the client)

**Verify**: Service returns expected output with mocked client.

---

## MCP Tools

- [ ] Define `@mcp.tool()` decorated async functions in `src/server.py`
- [ ] Each tool has `name` and detailed `description` in the decorator
- [ ] Description says **when to use** and lists **parameters** with examples
- [ ] Tools are thin wrappers — call service, format response, return dict
- [ ] Return `dict` (not string) with `status`, `summary`, and domain data
- [ ] Tool names are globally unique (won't collide with other MCP servers)
- [ ] No `default` values in parameter schemas (Anthropic requirement)

**Verify**: `tools/list` JSON-RPC returns all tools with correct schemas.

---

## Large Dataset Handling (if applicable)

- [ ] Define `_DISPLAY_COLUMNS` — column list for table rendering
- [ ] Project rows: `{col: r.get(col) for col in _DISPLAY_COLUMNS}`
- [ ] Add `table_data: {"columns": [...], "rows": [...]}}` to response
- [ ] Cap inline sample at 25 items (e.g., `"apps": results[:25]`)
- [ ] Build `_build_summary()` with counts, distribution, latest-per-category
- [ ] Remove old bulk keys (`full_results_data`, etc.)

**Verify**: Response with >50 rows includes `table_data` with projected rows.

See `specs/large-table-handling/` for the full contract and examples.

---

## Agent Guide Resource

- [ ] Define `@mcp.resource("{server-name}://agent-guide")`
- [ ] List all tools with "when to use" and "required args"
- [ ] List prompt templates with "when to use"
- [ ] Add domain constraints the LLM must follow
- [ ] URI ends with `://agent-guide` (required for auto-discovery)

**Verify**: Super Agent logs show agent-guide loaded at startup.

---

## Prompt Templates (optional)

- [ ] Define `@mcp.prompt()` for reusable workflows
- [ ] Each prompt has parameters and returns a step-by-step instruction string
- [ ] Prompts reference specific tool names the LLM should call

**Verify**: `prompts/list` JSON-RPC returns all prompts.

---

## FastAPI Integration

- [ ] Mount MCP at `/mcp/`: `app.mount("/mcp", mcp.streamable_http_app())`
- [ ] Add health check at `GET /health` (returns server name, version, tool list)
- [ ] Start MCP session manager in FastAPI lifespan context
- [ ] CORS middleware allows all origins (for local dev)

**Verify**:
```bash
# Health
curl http://localhost:8020/health

# List tools
curl -X POST http://localhost:8020/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Call tool
curl -X POST http://localhost:8020/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"your_tool","arguments":{"arg":"value"}}}'
```

---

## Register with Super Agent

- [ ] Add server to `mcp_servers.yml`:
  ```yaml
  - name: your-server-name
    description: "What this server does"
    url: http://localhost:8020/mcp/
    transport: streamable_http
    enabled: true
    headers: {}
  ```
- [ ] Restart Super Agent
- [ ] Verify: Super Agent logs show tools discovered from your server
- [ ] Test: Ask Super Agent a question in your server's domain

---

## Tests

- [ ] `test_health.py` — health endpoint returns ok
- [ ] `test_tools.py` — each tool returns valid structured response
- [ ] Unit tests for service layer (mock client)
- [ ] Unit tests for client (mock httpx)
- [ ] Integration test: JSON-RPC `tools/call` → valid response

---

## Comparison: MCP Server vs ADK Agent Checklist

| Task | MCP Server | ADK Agent |
|---|---|---|
| LLM in `.env` | **No** | Yes — Claude/GPT credentials |
| Tool decorator | `@mcp.tool()` | Plain `async def` (ADK wraps) |
| System prompt | `://agent-guide` resource | `_INSTRUCTION` in agent.py |
| Transport | JSON-RPC at `/mcp/` | A2A JSON-RPC at `/a2a` |
| Reasoning | None — just returns data | LLM reasons + chains tools |
| Large datasets | `table_data` contract | Not applicable (agent reasons) |
| Registration | `mcp_servers.yml` | A2A agents config |
