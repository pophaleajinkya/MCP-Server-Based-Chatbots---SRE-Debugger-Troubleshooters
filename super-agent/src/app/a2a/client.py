"""A2A agent registry — loads remote subagent configs from Redis or YAML.

Mirrors the MCP client pattern exactly:
  - Local mode  (AGENT_ENV=local): reads A2A_AGENTS_FILE (YAML)
  - All other envs:               reads Redis key derived from env + group

Redis key format:
  super_agent:config:a2a_agents:<agent_env>:<agent_group>:config

Each subagent exposes a standard A2A 0.3 Agent Card at:
  GET {url}/.well-known/agent.json

super-agent calls this endpoint at startup to discover the agent's
``name``, ``description``, and ``skills`` — zero manual config needed
when the subagent serves a proper Agent Card.

Startup behaviour:
  - Empty Redis key / missing file  → no subagents (non-fatal, startup continues)
  - Agent Card fetch failure        → warning logged, description falls back to config value
  - Enabled=false entries           → silently skipped
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from redis.asyncio.cluster import ClusterNode, RedisCluster

from app.config import get_settings

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 8.0
_READ_TIMEOUT    = 15.0


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class A2AAgentConfig:
    """Configuration for a single remote A2A subagent.

    Attributes:
        name:        Unique snake_case identifier used as the ADK FunctionTool name.
                     Hyphens are automatically converted to underscores.
        url:         Base URL of the remote A2A agent (without trailing slash).
                     Agent Card is fetched from  {url}/.well-known/agent.json.
                     A2A calls go to            {url}/a2a  (message/send).
        enabled:     Set False to skip this agent without removing the config.
        headers:     Optional HTTP headers forwarded on every A2A call
                     (e.g. auth tokens, internal routing headers).
        description: Human-readable description used as the FunctionTool docstring.
                     If empty, super-agent auto-populates from the Agent Card.
    """
    name: str
    url: str
    enabled: bool = True
    headers: dict = field(default_factory=dict)
    description: str = ""


_REQUIRED_FIELDS = {"name", "url", "enabled"}


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_and_parse(entries: list[dict], source: str) -> list[A2AAgentConfig]:
    """Validate raw config dicts and return enabled A2AAgentConfig objects.

    Args:
        entries: Raw list of config dicts (from YAML or Redis JSON).
        source:  Human-readable label for error messages (file path or Redis key).

    Returns:
        List of enabled A2AAgentConfig objects.

    Raises:
        ValueError: If any enabled entry is missing required fields.
    """
    if not entries:
        raise ValueError(f"A2A agent config from {source!r} is empty — no entries found")

    configs: list[A2AAgentConfig] = []
    for i, entry in enumerate(entries):
        missing = _REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(
                f"A2A agent entry [{i}] in {source!r} is missing required fields: "
                f"{sorted(missing)}"
            )
        if not entry.get("enabled"):
            log.debug("A2A agent entry [%d] %r disabled — skipping", i, entry.get("name"))
            continue

        configs.append(A2AAgentConfig(
            name=entry["name"].replace("-", "_"),    # ADK requires valid Python identifiers
            url=entry["url"].rstrip("/"),
            enabled=True,
            headers=entry.get("headers") or {},
            description=entry.get("description") or "",
        ))

    if not configs:
        raise ValueError(
            f"A2A agent config from {source!r} has entries but none are enabled — "
            "set enabled: true on at least one agent"
        )

    log.info("A2A agents parsed from %r: %d enabled", source, len(configs))
    return configs


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_from_file(path: str) -> list[dict]:
    """Read and parse a YAML A2A agents file.

    Args:
        path: Absolute or relative path to the YAML file.

    Returns:
        Raw list of config dicts.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError:        If the file is empty or has no ``a2a_agents`` key.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"A2A_AGENTS_FILE not found: {path} — "
            "create the file or point A2A_AGENTS_FILE at an existing YAML config"
        )
    with p.open() as f:
        doc = yaml.safe_load(f)
    if not doc:
        raise ValueError(
            f"A2A_AGENTS_FILE {path!r} is empty — "
            "add at least one agent entry (see a2a_agents.yml.example)"
        )
    entries = doc.get("a2a_agents", doc.get("agents"))
    if not entries:
        raise ValueError(
            f"A2A_AGENTS_FILE {path!r} has no 'a2a_agents' key or the list is empty"
        )
    return entries


async def _load_from_redis(key: str, s) -> list[dict]:
    """Read and parse the A2A agents JSON from a Redis key.

    Args:
        key: Redis key to read.
        s:   Settings instance (provides Redis connection parameters).

    Returns:
        Raw list of config dicts, or empty list if the key is unset.
    """
    redis: RedisCluster = RedisCluster(
        startup_nodes=[ClusterNode(s.redis_host, s.redis_port)],
        username=s.redis_username or None,
        password=s.redis_password,
        decode_responses=True,
        ssl=s.redis_ssl,
        ssl_cert_reqs=None,
        socket_connect_timeout=5,
        socket_timeout=10,
    )
    try:
        raw = await redis.get(key)
        if not raw:
            log.info("Redis key %r is empty or unset — no A2A subagents registered", key)
            return []
        entries = json.loads(raw)
        return entries or []
    finally:
        await redis.aclose()


async def load_a2a_agents() -> list[A2AAgentConfig]:
    """Load enabled A2A subagent configs from file (local) or Redis (prod).

    **Local mode** (``AGENT_ENV=local``):
      - ``A2A_AGENTS_FILE`` must be set → logs info and returns [] if missing.
      - File must exist → raises ``FileNotFoundError`` if absent.

    **All other environments** (dev, stage, prod, etc.):
      - Redis key: ``super_agent:config:a2a_agents:<agent_env>:<agent_group>:config``
      - Empty key → returns [] (non-fatal; subagents are optional).

    Called **once at startup** — no periodic refresh.

    Returns:
        List of enabled A2AAgentConfig objects (may be empty).
    """
    s = get_settings()

    # ── Local mode: YAML file ─────────────────────────────────────────────────
    if s.agent_env.lower() == "local":
        if not s.a2a_agents_file:
            log.info(
                "[local] A2A_AGENTS_FILE not set — starting without remote subagents. "
                "Set A2A_AGENTS_FILE=./a2a_agents.yml to load local subagents."
            )
            return []
        log.info("[local] Loading A2A agents from file: %s", s.a2a_agents_file)
        entries = _load_from_file(s.a2a_agents_file)
        configs = _validate_and_parse(entries, source=s.a2a_agents_file)
        log.info("[local] %d A2A subagent(s) loaded from file", len(configs))
        for cfg in configs:
            log.info("  agent: name=%r  url=%r", cfg.name, cfg.url)
        return configs

    # ── Redis mode (dev / stage / prod) ──────────────────────────────────────
    redis_key = s.a2a_agents_config_key
    log.info(
        "[prod] Loading A2A agents — env=%r group=%r redis_key=%r",
        s.agent_env, s.agent_group, redis_key,
    )
    entries = await _load_from_redis(redis_key, s)
    if not entries:
        log.info("[prod] No A2A subagents registered at %r — running MCP-only", redis_key)
        return []
    configs = _validate_and_parse(entries, source=f"Redis key {redis_key!r}")
    log.info("[prod] %d A2A subagent(s) loaded from Redis", len(configs))
    for cfg in configs:
        log.info("  agent: name=%r  url=%r", cfg.name, cfg.url)
    return configs


# ── Agent Card discovery ──────────────────────────────────────────────────────

async def fetch_agent_card(url: str, headers: dict | None = None) -> dict[str, Any]:
    """Fetch the A2A Agent Card from ``{url}/.well-known/agent.json``.

    The Agent Card is a standard A2A 0.3 JSON document that describes the
    agent's identity, capabilities, and skills.  super-agent uses it to
    auto-populate the FunctionTool description exposed to the orchestrator LLM.

    Args:
        url:     Base URL of the remote agent (trailing slash stripped).
        headers: Optional HTTP headers (e.g. internal auth tokens).

    Returns:
        Parsed Agent Card dict, or ``{}`` if unreachable / not an A2A agent.
        Failures are logged as warnings — they do not abort startup.
    """
    card_url = f"{url.rstrip('/')}/.well-known/agent.json"
    try:
        async with httpx.AsyncClient(
            headers={"Accept": "application/json", **(headers or {})},
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT,
                read=_READ_TIMEOUT,
                write=5.0,
                pool=5.0,
            ),
            follow_redirects=True,
        ) as client:
            resp = await client.get(card_url)
            resp.raise_for_status()
            card = resp.json()
            skill_ids = [sk.get("id", sk.get("name", "?")) for sk in card.get("skills", [])]
            log.info(
                "✅ Agent Card fetched: %s  skills=%s",
                card.get("name", url),
                skill_ids,
            )
            return card
    except httpx.HTTPStatusError as exc:
        log.warning(
            "⚠️  Agent Card at %s returned HTTP %s — "
            "falling back to config description",
            card_url, exc.response.status_code,
        )
    except Exception as exc:
        log.warning(
            "⚠️  Could not fetch Agent Card from %s: %s — "
            "falling back to config description",
            card_url, exc,
        )
    return {}
