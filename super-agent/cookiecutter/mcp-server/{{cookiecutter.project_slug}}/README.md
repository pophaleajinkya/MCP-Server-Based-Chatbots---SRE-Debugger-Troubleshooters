# {{cookiecutter.project_name}}

{{cookiecutter.server_description}}

Built with **MCP Python SDK 1.x** + **FastAPI** — ready to register with super-agent.

---

## Quick start

```bash
# 1. Create virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env with your domain-specific settings

# 4. Run the server
uvicorn src.main:app --reload --port {{cookiecutter.server_port}}

# 5. Verify health
curl http://localhost:{{cookiecutter.server_port}}/health | jq .

# 6. Verify MCP tools
curl -X POST http://localhost:{{cookiecutter.server_port}}/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq .

# 7. Run tests (all schema compliance tests must pass before registering)
pytest
```

---

## Project structure

```
src/
  server.py    ← MCP tools, resources, and prompts (the main file to edit)
  config.py    ← Settings loaded from .env
  main.py      ← FastAPI app + MCP mount at /mcp/
tests/
  test_tools.py   ← Tool schema compliance tests (run before registering!)
  test_health.py  ← Health + MCP endpoint tests
```

---

## Adding tools

Edit `src/server.py`:

```python
@mcp.tool()
async def my_new_tool(
    namespace: str,
    app: str = "",
) -> str:
    """Short, specific description of what this tool does.

    Use this tool when the user asks about <your domain scenario>.
    Returns a JSON object with ...

    Args:
        namespace: The Kubernetes namespace (e.g. 'iro-prod').
        app:       Optional app name to filter results.
    """
    # Your implementation here
    result = {"status": "ok", "namespace": namespace}
    return json.dumps(result)
```

**Schema rules (must pass before registering with super-agent):**
- ❌ No `default` values in parameters
- ❌ No `$ref`, `definitions`, `$schema`
- ❌ No `if`/`then`/`else`
- ✅ Return JSON string or plain text
- ✅ Include `chart_data` / `table_data` / `grafana_url` for rich UI

---

## Registering with super-agent

### Local dev

Add to `mcp_servers.yml` in super-agent:

```yaml
servers:
  - name: {{cookiecutter.server_name}}
    url: http://localhost:{{cookiecutter.server_port}}/mcp/
    transport: streamable_http
    enabled: true
    description: "{{cookiecutter.server_description}}"
    headers: {}
```

### Production

```bash
redis-cli SET "super_agent:config:mcp_servers:<env>:<group>:config" '[
  {
    "name": "{{cookiecutter.server_name}}",
    "url": "https://{{cookiecutter.project_slug}}.stage.walmart.com/mcp/",
    "transport": "streamable_http",
    "enabled": true,
    "description": "{{cookiecutter.server_description}}",
    "headers": {}
  }
]'
```

> ⚠️ MCP servers are **required** — if any registered server fails to connect,
> super-agent aborts startup. Test connectivity before updating Redis.

---

## Customisation checklist

- [ ] Replace `example_tool` in `src/server.py` with your real domain tools
- [ ] Update `agent_guide` resource with tool routing rules for the LLM
- [ ] Add domain-specific prompt templates with `@mcp.prompt()`
- [ ] Add config fields in `src/config.py` for your env vars
- [ ] Run `pytest` — ALL schema compliance tests must pass before registering
- [ ] Test with super-agent locally using `mcp_servers.yml`
