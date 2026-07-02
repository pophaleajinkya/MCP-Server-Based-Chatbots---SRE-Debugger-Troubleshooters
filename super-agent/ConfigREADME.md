# Configuration Guide

All configuration is centralised in [`src/app/config.py`](src/app/config.py) using
[Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

## How it works

```
.env  /  /secrets/.env*  (environment variables)
        │
        ▼
  pydantic BaseSettings        ← auto-maps UPPER_SNAKE_CASE env vars
        │                        to snake_case Python fields
        ▼
  get_settings()               ← singleton, cached via @lru_cache
        │
        ▼
  All application code         ← imports get_settings() from app.config
```

### Naming convention

| Python field (config.py) | Environment variable (.env) |
|---|---|
| `snake_case` | `UPPER_SNAKE_CASE` |
| `llm_timeout_seconds` | `LLM_TIMEOUT_SECONDS` |
| `agent_env` | `AGENT_ENV` |
| `redis_host` | `REDIS_HOST` |

This mapping is automatic — Pydantic `BaseSettings` converts field names to
uppercase env var names. No manual wiring needed.

### Precedence

```
Environment variable  >  .env file  >  default in config.py
```

If `LLM_TIMEOUT_SECONDS=120` is in `.env`, it overrides the default `60` in `config.py`.
If neither exists, the default `60` is used.

### .env file loading order

The agent loads `.env*` files from two locations (maof-compatible strategy):

1. Current working directory — `.env`, `.env.redis-config`, etc.
2. `/secrets/` — WCNP Akeyless-mounted secrets (`.env.redis-config`, etc.)

Excluded: `.env.test`, `.env.example` (never loaded at runtime).

When duplicate keys exist across files, later files override earlier ones
(`override=True`).

---

## All configuration fields

### Server

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `AGENT_HOST` | `agent_host` | `str` | `0.0.0.0` | Bind address for the agent HTTP server |
| `AGENT_PORT` | `agent_port` | `int` | `8001` | Port for the agent HTTP server |

### OpenAI / Walmart Element Gateway

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `ELEMENT_GATEWAY_BASE_URL` | `element_gateway_base_url` | `str` | `""` | Base URL for the Walmart Element Gateway |
| `ELEMENT_GATEWAY_API_KEY` | `element_gateway_api_key` | `str` | `""` | JWT token for Element Gateway auth |
| `ELEMENT_GATEWAY_API_VERSION` | `element_gateway_api_version` | `str` | `2024-10-21` | Azure OpenAI API version |
| `OPENAI_MODEL` | `openai_model` | `str` | `gpt-4.1` | Model deployment name |

### Claude / Walmart Stage Gateway

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `CLAUDE_GATEWAY_URL` | `claude_gateway_url` | `str` | `""` | URL for Claude Messages API |
| `CLAUDE_API_KEY` | `claude_api_key` | `str` | `""` | JWT token for Claude gateway auth |
| `CLAUDE_MODEL` | `claude_model` | `str` | `claude-opus-4-6` | Claude model name |
| `CLAUDE_ANTHROPIC_VERSION` | `claude_anthropic_version` | `str` | `vertex-2023-10-16` | Anthropic API version header |
| `CLAUDE_IS_PRIMARY_LLM` | `claude_is_primary_llm` | `bool` | `false` | Set `true` to use Claude instead of OpenAI |

### Redis

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `REDIS_HOST` | `redis_host` | `str` | `""` | Redis Cluster host |
| `REDIS_PORT` | `redis_port` | `int` | `6379` | Redis port |
| `REDIS_USERNAME` | `redis_username` | `str` | `appuser` | Redis auth username |
| `REDIS_PASSWORD` | `redis_password` | `str` | `""` | Redis auth password |
| `REDIS_SSL` | `redis_ssl` | `bool` | `true` | Enable TLS for Redis connections |
| `REDIS_SESSION_TTL_SECONDS` | `redis_session_ttl_seconds` | `int` | `604800` | Session expiry (default 7 days) |

### Agent behaviour

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `MAX_TOOL_ROUNDS` | `max_tool_rounds` | `int` | `8` | Max MCP tool-call rounds per query |
| `LLM_TIMEOUT_SECONDS` | `llm_timeout_seconds` | `int` | `60` | Timeout for each LLM API call |
| `MCP_TIMEOUT_SECONDS` | `mcp_timeout_seconds` | `int` | `30` | Timeout for each MCP tool call |
| `LLM_HISTORY_TURNS` | `llm_history_turns` | `int` | `0` | Number of previous turns sent as context (0 = no memory) |

### Environment / Group (MCP discovery)

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `AGENT_ENV` | `agent_env` | `str` | `prod` | Environment name. Set `local` for local YAML mode; all other values (dev, stage, prod) use Redis |
| `AGENT_GROUP` | `agent_group` | `str` | `sre` | Agent group name — used in the Redis key |
| `MCP_SERVERS_FILE` | `mcp_servers_file` | `str` | `""` | Path to local YAML file (required when `AGENT_ENV=local`) |

### CORS / Trusted Hosts

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `cors_allowed_origins` | `list[str]` | *(see config.py)* | JSON array of allowed CORS origins |
| `ALLOWED_HOSTS` | `allowed_hosts` | `list[str]` | *(see config.py)* | JSON array of trusted host headers |

### Secrets

| Env var | Python field | Type | Default | Description |
|---|---|---|---|---|
| `SECRETS_PATH` | `secrets_path` | `str` | `/secrets/` | Mount path for Akeyless secrets |

---

## Computed fields (read-only, not settable via .env)

These are derived automatically from other fields — no env var needed.

| Python field | Derived from | Example value |
|---|---|---|
| `openai_url` | `element_gateway_base_url` + `openai_model` + `element_gateway_api_version` | `https://…/deployments/gpt-4.1/chat/completions?api-version=2024-10-21` |
| `openai_headers` | `element_gateway_api_key` | `{"Content-Type": "…", "api-key": "…"}` |
| `claude_headers` | `claude_api_key` + `claude_anthropic_version` | `{"Content-Type": "…", "x-api-key": "…"}` |
| `active_llm` | `claude_is_primary_llm` | `"claude"` or `"openai"` |
| `active_llm_endpoint` | `claude_is_primary_llm` + gateway URLs | The active gateway URL |
| `mcp_config_key` | `agent_env` + `agent_group` | `super_agent:config:mcp_servers:prod:sre:config` |

---

## How to add a new config field

1. **Add the field** in `src/app/config.py` inside the `Settings` class:

```python
class Settings(BaseSettings):
    # ── Your section ──────────────────────────────────────────────────────
    my_new_setting: int = 42  # DEFAULT value if env var is not set
```

2. **Use it** anywhere via `get_settings()`:

```python
from app.config import get_settings

s = get_settings()
print(s.my_new_setting)  # reads MY_NEW_SETTING from env, falls back to 42
```

3. **Document it** in `.env.example`:

```bash
# ── Your section ──────────────────────────────────────────────────────
MY_NEW_SETTING=42
```

4. **Override at runtime** in `.env` (or as a real env var in WCNP):

```bash
MY_NEW_SETTING=100
```

### Rules

- **Never use `os.getenv()` directly** — always go through `get_settings()`.
- Field names must be `snake_case` — Pydantic auto-maps to `UPPER_SNAKE_CASE` env vars.
- Use Python type hints (`str`, `int`, `bool`, `list[str]`) — Pydantic validates and coerces automatically.
- For derived/computed values, use `@computed_field` — these are read-only and not settable via `.env`.
- Secrets (API keys, passwords) should **never** have defaults — leave them as `""` so deployment fails fast if not configured.
- Update this file and `.env.example` when adding new fields.
