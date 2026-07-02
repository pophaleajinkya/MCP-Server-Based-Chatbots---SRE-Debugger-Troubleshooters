# {{cookiecutter.project_name}}

{{cookiecutter.agent_description}}

Built with **Google ADK 1.28.x** + **A2A SDK 0.3** — ready to register with super-agent.

---

## Quick start

```bash
# 1. Create virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env with your LLM gateway credentials

# 4. Run the agent
uvicorn src.main:app --reload --port {{cookiecutter.agent_port}}

# 5. Verify Agent Card
curl http://localhost:{{cookiecutter.agent_port}}/.well-known/agent.json | jq .

# 6. Run tests
pytest
```

---

## Project structure

```
src/
  agent/
    agent.py        ← ADK Agent definition (tools + instruction)
  app/
    factory.py      ← FastAPI app + A2A mount + Agent Card
  tools/
    example_tool.py ← Replace with your domain tools
  config.py         ← Settings loaded from .env
  main.py           ← Uvicorn entry point
tests/
  test_agent_card.py    ← Agent Card compliance tests
  test_a2a_endpoint.py  ← A2A protocol tests
```

---

## Registering with super-agent

### Local dev

Add to `a2a_agents.yml` in super-agent:

```yaml
a2a_agents:
  - name: {{cookiecutter.agent_name}}
    url: http://localhost:{{cookiecutter.agent_port}}
    enabled: true
    description: ""   # auto-fetched from /.well-known/agent.json
    headers: {}
```

### Production

```bash
redis-cli SET "super_agent:config:a2a_agents:<env>:<group>:config" '[
  {
    "name": "{{cookiecutter.agent_name}}",
    "url": "https://{{cookiecutter.project_slug}}.stage.walmart.com",
    "enabled": true,
    "description": "",
    "headers": {}
  }
]'
```

---

## Customisation checklist

- [ ] Update `AGENT_CARD.description` in `src/app/factory.py`
- [ ] Replace `AGENT_CARD.skills` with your real skills (be specific!)
- [ ] Add your domain tools to `src/tools/` and register in `src/agent/agent.py`
- [ ] Update `_INSTRUCTION` in `src/agent/agent.py` with domain knowledge
- [ ] Connect MCP servers if needed (see `src/agent/agent.py` comments)
- [ ] Run `pytest` — all Agent Card tests must pass before registering
