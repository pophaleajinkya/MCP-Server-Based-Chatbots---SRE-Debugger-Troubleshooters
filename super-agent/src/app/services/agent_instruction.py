"""Agent instruction (system prompt) loader.

Supports two sources, controlled by the ``AGENT_INSTRUCTION_FROM_REDIS`` env flag:

* **File (default)** — reads ``resources/AGENT_INSTRUCTION.md`` from disk.
  Safe for local development; no Redis required.

* **Redis** — reads the instruction stored at the key derived from
  ``Settings.agent_instruction_config_key``:
  ``super_agent:config:agent_instruction:<agent_env>:<agent_group>:config``

  Operators update the Redis key to hot-reload the system prompt without a
  code deploy or pod restart.

Fall-back chain when Redis is selected but unavailable:
  Redis key missing / empty  → log warning, fall back to the on-disk file
  Redis connection error      → log error,   fall back to the on-disk file
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_SEP = "=" * 60

# Path to the bundled fallback instruction file (relative to this file's package root)
_INSTRUCTION_FILE = Path(__file__).parents[3] / "resources" / "AGENT_INSTRUCTION.md"

_HARDCODED_FALLBACK = (
    "You are a health and dependency intelligence assistant for Walmart's infrastructure. "
    "Use the available tools to answer every question. "
    "Call tools immediately — never ask for confirmation before calling a tool. "
    "The domain-specific guides below describe how to handle each scenario. "
    "Follow them step-by-step."
)


def _load_from_file() -> str:
    """Load instruction from the bundled AGENT_INSTRUCTION.md file.

    Returns the hardcoded fallback string when the file is not found.
    """
    try:
        text = _INSTRUCTION_FILE.read_text(encoding="utf-8").strip()
        log.info(_SEP)
        log.info("[AgentInstruction] SOURCE      : FILE (disk)")
        log.info("[AgentInstruction] PATH        : %s", _INSTRUCTION_FILE)
        log.info("[AgentInstruction] STATUS      : ✅ Loaded successfully")
        log.info("[AgentInstruction] SIZE        : %d chars", len(text))
        log.info(_SEP)
        return text
    except FileNotFoundError:
        log.warning(_SEP)
        log.warning("[AgentInstruction] SOURCE      : FILE (disk)")
        log.warning("[AgentInstruction] PATH        : %s", _INSTRUCTION_FILE)
        log.warning("[AgentInstruction] STATUS      : ⚠️  File not found — using hardcoded fallback")
        log.warning(_SEP)
        return _HARDCODED_FALLBACK


async def load_agent_instruction() -> str:
    """Return the agent system-prompt instruction.

    Reads from Redis when ``AGENT_INSTRUCTION_FROM_REDIS=true``; otherwise
    (and as a fall-back on any Redis error) reads from disk.

    Returns:
        The full instruction string — never empty (falls back through the
        chain: Redis → file → hardcoded string).
    """
    from app.config import get_settings  # local import avoids circular dep

    s = get_settings()

    # ── Banner: show which source is configured ───────────────────────────────
    log.info(_SEP)
    log.info("[AgentInstruction] AGENT_INSTRUCTION_FROM_REDIS = %s", s.agent_instruction_from_redis)

    if not s.agent_instruction_from_redis:
        log.info("[AgentInstruction] SOURCE      : FILE (disk) — Redis flag is false")
        log.info(_SEP)
        return _load_from_file()

    # ── Redis path ─────────────────────────────────────────────────────────────
    redis_key = s.agent_instruction_config_key
    log.info("[AgentInstruction] SOURCE      : REDIS")
    log.info("[AgentInstruction] REDIS HOST  : %s:%s", s.redis_host, s.redis_port)
    log.info("[AgentInstruction] REDIS KEY   : %s", redis_key)
    log.info(_SEP)

    try:
        # Reuse the existing shared Redis client from pingfed.store
        from app.pingfed import store as pingfed_store
        redis = await pingfed_store._get_redis()

        log.info("[AgentInstruction] Reading key from Redis ...")

        raw: str | None = await redis.get(redis_key)

        if not raw or not raw.strip():
            log.warning(_SEP)
            log.warning("[AgentInstruction] STATUS      : ⚠️  Redis key not found or empty")
            log.warning("[AgentInstruction] REDIS KEY   : %s", redis_key)
            log.warning("[AgentInstruction] FALLBACK    : Loading from disk file instead")
            log.warning(_SEP)
            return _load_from_file()

        text = raw.strip()
        log.info(_SEP)
        log.info("[AgentInstruction] STATUS      : ✅ Loaded successfully from Redis")
        log.info("[AgentInstruction] REDIS KEY   : %s", redis_key)
        log.info("[AgentInstruction] SIZE        : %d chars", len(text))
        log.info(_SEP)
        return text

    except Exception as exc:
        log.error(_SEP)
        log.error("[AgentInstruction] STATUS      : ❌ Redis connection/read FAILED")
        log.error("[AgentInstruction] REDIS KEY   : %s", redis_key)
        log.error("[AgentInstruction] ERROR       : %s", exc)
        log.error("[AgentInstruction] FALLBACK    : Loading from disk file instead")
        log.error(_SEP)
        return _load_from_file()
