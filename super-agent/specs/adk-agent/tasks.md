# Tasks: ADK Agent — Build Checklist

**Feature**: `adk-agent` | **Date**: 2026-04-02
**Spec**: `spec.md` | **Plan**: `plan.md`

> Checklist for building a new ADK agent from scratch.  Each task is independently
> verifiable.

---

## Scaffold

- [ ] Run `cookiecutter cookiecutter/a2a-agent/` with your project details
- [ ] Copy `.env.example` to `.env`
- [ ] Fill in LLM credentials (Claude or Azure OpenAI)
- [ ] `pip install -e .` — verify dependencies install

**Verify**: `python -c "from src.config import get_settings; print(get_settings().claude_model)"`

---

## Configuration

- [ ] Add domain-specific settings to `src/config.py` (API URLs, keys, etc.)
- [ ] Add matching env vars to `.env` and `.env.example`
- [ ] Verify: `get_settings()` loads all values correctly

---

## Tools

- [ ] Create tool files in `src/tools/` (one file per tool group)
- [ ] Each tool is an `async def` with typed args and a detailed docstring
- [ ] Tool docstring says **when to use** and **what it returns**
- [ ] Tools return `dict[str, Any]` (not strings) — structured data for LLM reasoning
- [ ] Tools handle errors gracefully (return `{"status": "error"}`, don't raise)
- [ ] Tools use `httpx.AsyncClient` with timeout + `verify=False`
- [ ] Test each tool independently: `await fetch_wcnp_apps("intl-sre")`

**Verify**: Each tool returns a valid dict when called with sample args.

---

## Agent

- [ ] Write `_INSTRUCTION` in `src/agent/agent.py` — domain knowledge + tool descriptions
- [ ] Import all tools and list them in the `Agent()` constructor
- [ ] Set `model=_llm` (LiteLLM instance from `.env` config)
- [ ] Set unique `name` and descriptive `description`

**Verify**: `create_agent()` returns an Agent without errors.

---

## LLM

- [ ] LiteLLM model is created from `.env` values (not hardcoded)
- [ ] `litellm.ssl_verify = False` is set before any LLM call
- [ ] For Claude: `api_base` strips `/v1/messages` suffix from gateway URL
- [ ] For Claude: `extra_headers` includes `anthropic-version`
- [ ] For Azure: `api_base` includes `/deployments/{model}` path

**Verify**: Agent responds to a simple test question via A2A endpoint.

---

## A2A Endpoint

- [ ] FastAPI app exposes `POST /a2a` — JSON-RPC endpoint
- [ ] Agent Card at `GET /.well-known/agent.json` is correct
- [ ] Health check at `GET /health` returns status

**Verify**:
```bash
# Agent Card
curl http://localhost:8002/.well-known/agent.json

# A2A call
curl -X POST http://localhost:8002/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"type":"text","text":"hello"}],"messageId":"t1"}}}'
```

---

## Integration with Super Agent

- [ ] Add agent to A2A agents config (YAML or Redis)
- [ ] Super Agent discovers Agent Card at startup
- [ ] Test delegation: ask Super Agent a question in your agent's domain
- [ ] Verify Super Agent delegates to your agent and returns the answer

---

## Tests

- [ ] `test_agent_card.py` — Agent Card has correct name, description, capabilities
- [ ] `test_a2a_endpoint.py` — A2A endpoint responds to `message/send`
- [ ] Unit tests for each tool (mock HTTP calls)
- [ ] Integration test: end-to-end question → tool call → answer

---

## Example: WCNP Operations Agent

| Step | File | What to do |
|---|---|---|
| Settings | `src/config.py` | Add `dx_api_base: str = "https://dx.walmart.com"` |
| Tool 1 | `src/tools/wcnp_tools.py` | `fetch_wcnp_apps(namespace, profile)` → calls `/proxy/wcnp-apps/apps` |
| Tool 2 | `src/tools/user_tools.py` | `fetch_user_info(service_id)` → calls `/common/api/people/users/{id}` |
| Instruction | `src/agent/agent.py` | Describe capabilities, tool routing rules, output format |
| Agent | `src/agent/agent.py` | `Agent(model=_llm, tools=[fetch_wcnp_apps, fetch_user_info])` |
| `.env` | `.env` | `DX_API_BASE=https://dx.walmart.com` + LLM credentials |
