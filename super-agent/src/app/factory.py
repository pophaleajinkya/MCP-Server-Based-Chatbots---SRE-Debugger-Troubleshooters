"""FastAPI application factory for the ADK-native agent.

Separates app construction and lifespan from the entry-point (main.py)
so that create_app() can be imported in tests or alternative entry points
without side effects.
"""

import asyncio
import contextvars
import json
import logging
import re
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

# Per-request contextvars to carry real user/session identity from _before_agent
# (where RequestContext.call_context is available) into _after_event (which only
# has ExecutorContext — no call_context field).
_cv_login_id: contextvars.ContextVar[str]  = contextvars.ContextVar("login_id",     default="")
_cv_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("session_id",  default="")
_cv_user_text: contextvars.ContextVar[str]  = contextvars.ContextVar("user_text",   default="")
# participants = "all" or comma-separated user IDs; permission = "read" | "write"
_cv_participants: contextvars.ContextVar[str] = contextvars.ContextVar("participants", default="")
_cv_permission: contextvars.ContextVar[str]   = contextvars.ContextVar("permission",   default="read")
_cv_user_name: contextvars.ContextVar[str]    = contextvars.ContextVar("user_name",    default="")

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from google.adk.runners import Runner
from google.adk.tools.mcp_tool.mcp_toolset import (
    SseConnectionParams,
    StreamableHTTPConnectionParams,
)
from agent.caching_mcp_toolset import CachingMCPToolset
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor, A2aAgentExecutorConfig
from google.adk.a2a.executor.config import ExecuteInterceptor, ExecutorContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.apps.jsonrpc.jsonrpc_app import CallContextBuilder
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, InMemoryPushNotificationConfigStore
from a2a.server.agent_execution.context import RequestContext
from a2a.types import AgentCard as A2AAgentCard, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
from starlette.requests import Request as StarletteRequest

from agent import make_agent
from app.config import get_settings
from app.constants import APP_NAME as _AGENT_NAME
from app.exceptions import (
    AgentError, LLMError, MCPConnectionError,
    agent_error_handler, llm_error_handler, mcp_connection_error_handler,
)
from app.a2a.client import A2AAgentConfig, fetch_agent_card, load_a2a_agents
from app.mcp.client import MCPPool, MCPSession, load_mcp_servers
from app.tools.remote_agent import make_remote_agent_tool
from app.request_context import extract_llm_headers, set_llm_headers, clear_llm_headers, set_user_time_context
from app.routers import debug, health, mcp_proxy, mcp_validate, query, sessions, faqs
from app.routers.mcp_validate import _find_adk_unsafe_vars
from app.services.runner import find_suspicious_fields, register_mcp_servers, register_mcp_tools
from app.store.redis_session_service import RedisSessionService
from app import pingfed

log = logging.getLogger(__name__)

_AGENT_DESCRIPTION = (
    "WCNP Health Agent — provides detailed health reports for any Kubernetes "
    "namespace or namespace + app combination on WCNP clusters. Runs 17 parallel "
    "health checks across compute, mesh, pods, secrets, and configuration using "
    "live Prometheus data. Covers CPU, memory, restarts, node health, NPD events, "
    "replica readiness, scale events, pod age, rescheduling, rollout detection, "
    "external secrets, CCM config changes, and 7 Istio service-mesh checks "
    "(client/server success rate, traffic spikes, P95 latency, retries, rate "
    "limiting). Supports multi-tenant, multi-region WCNP troubleshooting for "
    "SRE and DevOps teams."
)


# ── MCP startup summary ───────────────────────────────────────────────────────

def _log_mcp_summary(mcp_pool: MCPPool) -> None:
    """Log a detailed summary of all connected MCP servers, their tools and resources."""
    SEP = "*" * 54
    sessions = mcp_pool._sessions
    connected = [s for s in sessions if s._name not in {f["name"] for f in mcp_pool.failed_servers}]

    log.info(SEP)
    log.info("Total MCP servers connected: %d", len(connected))

    for idx, s in enumerate(connected, start=1):
        log.info("")
        log.info("MCP%d: %s", idx, s._name)
        log.info("  URL       : %s", s._url)
        log.info("  Session ID: %s", s.sid or "n/a")
        log.info("  Tools (%d):", len(s.tools))
        for t in s.tools:
            desc = t.get("description", "")
            desc_short = f"  — {desc[:80]}" if desc else ""
            log.info("    - %s%s", t["name"], desc_short)
        if s.guide:
            log.info("  Resources:")
            log.info("    - wcnp://agent-guide (%d chars)", len(s.guide))
        else:
            log.info("  Resources: (none)")

    if mcp_pool.failed_servers:
        log.info("")
        log.info("Failed MCP servers (%d):", len(mcp_pool.failed_servers))
        for f in mcp_pool.failed_servers:
            log.info("  - %s (%s) — %s", f["name"], f["url"], f["error"])

    log.info(SEP)


def _sanitize_tool_prefix(server_name: str) -> str:
    """Return a safe prefix for ADK tool names derived from an MCP server name."""
    prefix = re.sub(r"[^0-9A-Za-z_]+", "_", server_name).strip("_")
    return prefix or "mcp"


# ── Tool schema validation ─────────────────────────────────────────────────────

def _validate_tool_schemas(claude_tools: list[dict]) -> None:
    """Validate every tool's input_schema at startup and log full details on failure.

    Checks each tool against the minimal requirements Anthropic enforces for
    JSON Schema draft 2020-12.  Any tool that fails is logged in full so the
    offending schema can be identified and fixed without waiting for a live error.
    """
    FORBIDDEN_LEGACY_KEYS = {"definitions"}  # replaced by $defs in draft 2020-12

    for idx, tool in enumerate(claude_tools):
        try:
            name         = tool.get("name", f"<unnamed-{idx}>")
            input_schema = tool.get("input_schema")

            if not isinstance(input_schema, dict):
                raise ValueError(f"input_schema is {type(input_schema).__name__!r}, expected dict")

            # Must be JSON-serialisable (catches circular refs / non-serialisable values)
            json.dumps(input_schema)

            # Warn on legacy keys that are invalid in draft 2020-12
            bad_keys = FORBIDDEN_LEGACY_KEYS & input_schema.keys()
            if bad_keys:
                log.warning(
                    "Tool[%d] %r — input_schema uses legacy keys %s (invalid in JSON Schema draft 2020-12)\n"
                    "Full tool details:\n%s",
                    idx, name, sorted(bad_keys), json.dumps(tool, indent=2),
                )

            # A non-object top-level type is a common source of Anthropic rejections
            schema_type = input_schema.get("type")
            if schema_type and schema_type != "object":
                log.warning(
                    "Tool[%d] %r — input_schema top-level type=%r (Anthropic requires 'object')\n"
                    "Full tool details:\n%s",
                    idx, name, schema_type, json.dumps(tool, indent=2),
                )

            # Deep-scan for suspicious fields (default, $ref, definitions, etc.)
            suspicious = find_suspicious_fields(input_schema)
            if suspicious:
                log.warning(
                    "Tool[%d] %r — suspicious schema fields that Anthropic may reject: %s",
                    idx, name, suspicious,
                )
                log.debug("Tool[%d] %r — full tool details:\n%s",
                    idx, name, json.dumps(tool, indent=2),
                )
            else:
                log.debug("Tool[%d] %r — schema OK", idx, name)

        except Exception as exc:
            log.error(
                "Tool[%d] schema validation FAILED: %s\nFull tool details:\n%s",
                idx, exc, json.dumps(tool, indent=2, default=str),
            )


# ── ADK guide safety validation ───────────────────────────────────────────────

def _validate_guide_adk_safety(mcp_pool: MCPPool) -> None:
    """Abort startup if any MCP server guide contains bare {identifier} patterns.

    Google ADK's instruction engine runs inject_session_state() on every request.
    It substitutes {var} with session state values and raises KeyError when the
    variable is not set — killing every user request until the server restarts.

    This check prevents that by refusing to start when a loaded guide would
    produce an ADK crash at runtime.
    """
    violations: list[str] = []

    for session in mcp_pool._sessions:
        if not session.guide:
            continue
        unsafe_vars = _find_adk_unsafe_vars(session.guide)
        for var in unsafe_vars:
            violations.append(
                f"  [{session._name}] guide contains `{{{var}}}` — ADK will raise "
                f"KeyError('Context variable not found: `{var}`.') on every user request."
            )

    if violations:
        details = "\n".join(violations)
        raise RuntimeError(
            f"Startup aborted — {len(violations)} ADK template conflict(s) found in MCP guide(s).\n"
            f"Fix the guide content by replacing bare {{identifier}} with <identifier> or {{identifier?}}:\n"
            f"{details}"
        )

    log.info("ADK guide safety check passed — no template conflicts found in MCP guides")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start the ADK Runner and probe the MCP server for health-endpoint metadata.

    Stores on ``app.state``:
      - ``runner``       — ADK Runner wrapping ``root_agent``
      - ``tasks``        — in-memory A2A task registry
      - ``mcp_servers``  — list of {name, url} dicts for /health
      - ``mcp_tools``    — list of tool names for /health
      - ``a2a_agents``   — list of {name, url} dicts for registered A2A subagents
    """
    # ── CORS config (resolved before Redis connect) ──────────────────────────
    s = get_settings()
    log.info("CORS allowed origins : %s", s.cors_allowed_origins)

    # Pre-warm platform-hub JWT before loading MCP configs so required_token
    # servers can authenticate during first connect/tool-discovery.
    hub_prewarmed = False
    if s.sso_username and s.sso_password:
        try:
            await pingfed.warm_hub()
            hub_prewarmed = True
            log.info("pingfed hub pre-warm OK (before MCP load)")
        except Exception as _exc:
            log.warning("pingfed hub pre-warm failed (will retry later): %s", _exc)

    # ── MCP servers (local YAML file or Redis — banner logged on failure) ────
    server_configs = await load_mcp_servers()
    http_client    = httpx.AsyncClient(follow_redirects=True)
    sessions       = [MCPSession(http_client, cfg.url, cfg.name, headers=cfg.headers) for cfg in server_configs]
    mcp_pool       = MCPPool(sessions)

    try:
        await mcp_pool.connect()
    except Exception as exc:
        log.critical("MCP pool connect raised unexpectedly (%s) — aborting startup", exc)
        await http_client.aclose()
        raise

    if mcp_pool.failed_servers:
        for f in mcp_pool.failed_servers:
            log.critical(
                "MCP server [%s] failed to connect — url=%r error=%s — aborting startup",
                f["name"], f["url"], f["error"],
            )
        await http_client.aclose()
        failed_details = ", ".join(
            f"{f['name']} ({f['url']})" for f in mcp_pool.failed_servers
        )
        raise RuntimeError(
            f"Startup aborted — {len(mcp_pool.failed_servers)} MCP server(s) failed to connect: "
            f"{failed_details}. Fix the connection issue and restart."
        )

    app.state.mcp_servers = mcp_pool.servers
    app.state.mcp_tools   = [t["name"] for t in mcp_pool.tools]
    app.state.mcp_pool    = mcp_pool
    app.state.http_client = http_client

    # ── Validate tool schemas at startup ──────────────────────────────────────
    register_mcp_tools(mcp_pool.claude_tools)
    register_mcp_servers(mcp_pool.servers)
    _validate_tool_schemas(mcp_pool.claude_tools)

    # ── Validate MCP guide content — abort if any {identifier} would crash ADK ─
    _validate_guide_adk_safety(mcp_pool)

    # ── Generate dynamic FAQs from MCP capabilities ───────────────────────────
    app.state.dynamic_faqs = mcp_pool.generate_faqs()

    _log_mcp_summary(mcp_pool)

    # Anthropic requires globally unique tool names. Detect collisions across
    # MCP servers and apply per-server prefixes only where needed.
    failed_server_names = {f["name"] for f in mcp_pool.failed_servers}
    connected_sessions = [session for session in sessions if session._name not in failed_server_names]
    tool_name_counts = Counter(
        t["name"]
        for session in connected_sessions
        for t in session.tools
        if isinstance(t, dict) and "name" in t
    )
    duplicate_tool_names = {name for name, count in tool_name_counts.items() if count > 1}
    colliding_servers: dict[str, set[str]] = {}
    if duplicate_tool_names:
        for session in connected_sessions:
            overlaps = {
                t["name"]
                for t in session.tools
                if isinstance(t, dict) and t.get("name") in duplicate_tool_names
            }
            if overlaps:
                colliding_servers[session._name] = overlaps

        log.warning(
            "Detected duplicate MCP tool names across servers: %s",
            sorted(duplicate_tool_names),
        )
        for server_name, overlaps in sorted(colliding_servers.items()):
            log.warning(
                "MCP server '%s' has colliding tools: %s",
                server_name,
                sorted(overlaps),
            )

    # ── Header provider for required_token MCP servers ──────────────────────
    # Jira / Confluence MCP servers require a *human AD* PingFed token
    # (Infosec policy: service-account tokens are rejected).  The user's
    # token arrives from the SRE UI as an Authorization header and is stored
    # per-request in a contextvar + fallback dict by _before_agent().
    # ADK calls this provider on every tool invocation, merging the returned
    # headers *on top of* the static connection_params headers — so the
    # user's token overrides the service-account hub token at call time.
    def _user_token_header_provider(readonly_context) -> dict[str, str]:
        from app.request_context import get_user_token
        session_id = ""
        if readonly_context:
            try:
                session_id = readonly_context.session.id or ""
            except Exception:
                pass
        token = get_user_token(session_id=session_id)
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    # ── Build ADK agent + runner from Redis-loaded MCP server configs ─────────
    toolsets = []
    _mcp_timeout = s.mcp_timeout_seconds
    used_prefixes: set[str] = set()
    server_prefixes: dict[str, str] = {}
    for cfg in server_configs:
        tool_name_prefix = None
        if cfg.name in colliding_servers:
            base_prefix = _sanitize_tool_prefix(cfg.name)
            unique_prefix = base_prefix
            suffix = 2
            while unique_prefix in used_prefixes:
                unique_prefix = f"{base_prefix}_{suffix}"
                suffix += 1
            used_prefixes.add(unique_prefix)
            server_prefixes[cfg.name] = unique_prefix
            tool_name_prefix = unique_prefix

        params = (
            StreamableHTTPConnectionParams(
                url=cfg.url, headers=cfg.headers, timeout=_mcp_timeout,
            )
            if cfg.transport == "streamable_http"
            else SseConnectionParams(
                url=cfg.url, headers=cfg.headers, timeout=_mcp_timeout,
            )
        )
        # For required_token servers, inject a header_provider that overrides
        # Authorization with the user's PingFed token per tool call.
        toolset_kwargs: dict[str, Any] = {}
        if cfg.required_token:
            toolset_kwargs["header_provider"] = _user_token_header_provider
            log.info(
                "MCP [%s]: required_token=true → header_provider attached for per-user auth",
                cfg.name,
            )
        toolsets.append(
            CachingMCPToolset(
                connection_params=params,
                tool_name_prefix=tool_name_prefix,
                **toolset_kwargs,
            )
        )

    if server_prefixes:
        log.warning(
            "Applied MCP tool prefixes to avoid collisions: %s",
            server_prefixes,
        )

    # ── A2A remote subagents loaded from Redis ────────────────────────────────
    # Non-fatal: missing/empty key returns [] and startup continues.
    # Each subagent is wrapped as a FunctionTool the orchestrator LLM can call.
    remote_agent_tools: list = []
    a2a_agent_configs: list[A2AAgentConfig] = await load_a2a_agents()

    for a2a_cfg in a2a_agent_configs:
        # Fetch Agent Card to auto-discover description + skills
        card = await fetch_agent_card(a2a_cfg.url, a2a_cfg.headers or None)

        # Prefer explicit config description; fall back to Agent Card; then generic fallback
        description = (
            a2a_cfg.description
            or card.get("description", "")
            or f"Remote A2A subagent: {a2a_cfg.name} at {a2a_cfg.url}"
        )

        # Enrich description with skills so the LLM knows exactly when to delegate
        skills = card.get("skills", [])
        if skills:
            skill_lines = "\n".join(
                f"  • {sk.get('id', sk.get('name', '?'))}: {sk.get('description', '')}"
                for sk in skills
            )
            description = f"{description}\n\nCapabilities:\n{skill_lines}"

        tool = make_remote_agent_tool(
            name=a2a_cfg.name,
            description=description,
            base_url=a2a_cfg.url,
            extra_headers=a2a_cfg.headers or None,
        )
        remote_agent_tools.append(tool)
        log.info(
            "✅ A2A subagent wired: %s → %s  (skills=%d)",
            a2a_cfg.name, a2a_cfg.url, len(skills),
        )

    app.state.a2a_agents = [{"name": c.name, "url": c.url} for c in a2a_agent_configs]
    log.info(
        "A2A subagents ready — %d registered | %s",
        len(remote_agent_tools),
        [c.name for c in a2a_agent_configs] or "none",
    )

    agent = await make_agent(
        toolsets,
        guide=mcp_pool.guide,
        mcp_pool=mcp_pool,
        remote_agent_tools=remote_agent_tools,
    )
    session_service = RedisSessionService()
    # InMemoryArtifactService is required when code_executor is set on the agent.
    # Without it ADK raises "Artifact service is not initialized" when code blocks run.
    from google.adk.artifacts import InMemoryArtifactService
    runner = Runner(
        agent=agent,
        app_name=_AGENT_NAME,
        session_service=session_service,
        artifact_service=InMemoryArtifactService(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.tasks  = {}

    # ── Mount ADK-native A2A endpoint ─────────────────────────────────────────
    _mount_a2a(app, runner)

    log.info(
        "ADK Runner ready — agent: %s | model: %s | MCP servers: %s",
        agent.name, agent.model, [cfg.name for cfg in server_configs],
    )

    # ── Pre-warm PingFederate bearer tokens for all configured O2 clusters ───────
    # One pod acquires each token; all 200 pods reuse them via Redis.
    # Non-fatal — skipped when SSO_USERNAME/SSO_PASSWORD are not configured.
    # Redis key per cluster: agent:{auth:<host>}:token  (Hash)
    #   Fields: access_token, refresh_token, expires_at, refresh_at, acquired_by, acquired_at
    # Configure via PINGFED_URLS (comma-separated) or PINGFED_BASE_URL (single URL).
    if s.sso_username and s.sso_password:
        urls = s.pingfed_url_list
        log.info("pingfed warm-up: %d cluster(s) → %s", len(urls), urls)
        for _url in urls:
            try:
                await pingfed.warm(_url)
                log.info("pingfed warm-up OK: %s", _url)
            except Exception as _exc:
                log.warning("pingfed warm-up failed for %s (non-fatal): %s", _url, _exc)

        # Pre-warm platform-hub JWT (DX SSO) — used by ChangeIQ and other MCP servers.
        if not hub_prewarmed:
            try:
                await pingfed.warm_hub()
                log.info("pingfed hub warm-up OK (dx.walmart.com → platform-hub JWT)")
            except Exception as _exc:
                log.warning("pingfed hub warm-up failed (non-fatal): %s", _exc)

    yield

    await session_service._redis.aclose()
    await pingfed.close()
    await http_client.aclose()
    log.info("A2A Health Agent shut down cleanly")


# ── Graceful A2A executor (MCP error handling) ────────────────────────────────

from app.services.runner import (
    _MCP_ERROR_SIGNATURES as _A2A_MCP_SIGS,
    _mcp_server_registry as _a2a_server_registry,
)


def _a2a_friendly_message(raw_text: str) -> str:
    """Build a user-friendly MCP error for the A2A path.

    Tries to identify the specific failed server by matching registered URLs
    against the raw error text.  Falls back to listing all servers.
    """
    # Try to match a registered MCP server URL in the error text
    for url, name in _a2a_server_registry.items():
        if url in raw_text:
            return (
                f"The **{name}** service is temporarily unavailable. "
                f"Please try again in a few moments. If the issue persists, "
                f"contact the SRE Super Agent team in #sre-super-agent."
            )

    # Fallback — list all configured servers for context
    if _a2a_server_registry:
        all_names = ", ".join(sorted(_a2a_server_registry.values()))
        return (
            f"One or more backend services ({all_names}) are temporarily unavailable. "
            f"Please try again in a few moments. If the issue persists, "
            f"contact the SRE Super Agent team in #sre-super-agent."
        )

    return (
        "One or more backend services are temporarily unavailable. "
        "Please try again in a few moments. If the issue persists, "
        "contact the SRE Super Agent team in #sre-super-agent."
    )


class _MCPErrorInterceptQueue:
    """Proxy EventQueue that rewrites MCP connection error messages.

    Intercepts ``TaskStatusUpdateEvent`` with ``state=failed`` whose message
    contains MCP error signatures, and replaces the raw traceback text with
    a user-friendly message that identifies the specific failed server.
    """

    def __init__(self, inner):
        self._inner = inner

    async def enqueue_event(self, event):
        from a2a.types import TaskStatusUpdateEvent, TaskState

        if (
            isinstance(event, TaskStatusUpdateEvent)
            and event.status
            and event.status.state == TaskState.failed
            and event.status.message
            and event.status.message.parts
        ):
            # Check if any text part contains MCP error signatures
            for part in event.status.message.parts:
                root = getattr(part, "root", part)
                text = getattr(root, "text", "") or ""
                if any(sig in text for sig in _A2A_MCP_SIGS):
                    log.error("A2A MCP connection failure intercepted: %s", text[:200])
                    # Replace with friendly message that names the failed server
                    root.text = _a2a_friendly_message(text)
                    break

        return await self._inner.enqueue_event(event)

    def __getattr__(self, name):
        """Forward any other attribute access to the inner queue."""
        return getattr(self._inner, name)


class _GracefulA2aAgentExecutor(A2aAgentExecutor):
    """Wraps the ADK A2A executor to intercept MCP connection failures.

    When an MCP server is down, the base executor publishes the raw
    ``ConnectionError`` traceback as the failure message.  This subclass
    detects MCP-related failures and replaces the message with a
    user-friendly explanation before it reaches the UI.
    """

    async def execute(self, context, event_queue):
        """Delegate to the base executor, intercepting MCP errors via a proxy queue."""
        wrapped_queue = _MCPErrorInterceptQueue(event_queue)
        await super().execute(context, wrapped_queue)


# ── ADK-native A2A mounting ────────────────────────────────────────────────────

def _build_interceptors(redis_client, ttl: int, *, shared_state: dict):
    """Build after_event + after_agent interceptors that persist UI events to Redis.

    after_event:  accumulates streaming text; writes user msg + progress events.
    after_agent:  fires once when the turn completes; writes the final "complete"
                  event so session replay can reconstruct the full response.

    ``shared_state`` is a dict created by ``_mount_a2a`` so that ``_before_agent``
    can share dedup/cache sets with the interceptors (user_msg_written, session_owner_cache).
    """
    import time as _time
    from app.store.keys import (
        key_ui_events as _key_ui_events,
        key_sessions_zset as _key_sessions_zset,
        key_session_meta as _key_session_meta,
        key_sessions_public as _key_sessions_public,
        key_session_shared as _key_session_shared,
        key_session_visibility as _key_session_visibility,
    )

    # Per-session state tracked by the closure (all in-process, reset on restart).
    # _session_registered:  indexed in ZSET + meta once per session-lifetime.
    # _user_msg_written:    deduplicate user message writes per (session × text) turn.
    # _session_owner_cache: session_id → owner user_id (avoids Redis lookup per event).
    # _session_text_buf:    session_id → last non-empty ASSISTANT text this turn.
    #
    # Memory leak guard: cap all collections at 2 000 entries.  Once the limit is
    # reached the oldest half is evicted (pop-half strategy keeps O(1) amortised).
    _MAX_ENTRIES = 2_000

    _session_registered:  set[str]        = set()
    _user_msg_written:    set[str]         = shared_state["user_msg_written"]
    _session_owner_cache: dict[str, str]  = shared_state["session_owner_cache"]
    _identity_by_session: dict[str, dict] = shared_state["identity_by_session"]
    _session_text_buf:    dict[str, str]  = {}
    _session_reasoning_keys: dict[str, set[str]] = {}
    _MIN_REASONING_LEN = 8

    def _maybe_evict_set(s: set) -> None:
        if len(s) >= _MAX_ENTRIES:
            evict = list(s)[:len(s) // 2]
            for item in evict:
                s.discard(item)

    def _maybe_evict_dict(d: dict) -> None:
        if len(d) >= _MAX_ENTRIES:
            evict = list(d.keys())[:len(d) // 2]
            for key in evict:
                d.pop(key, None)

    async def _persist_reasoning_event(
        *,
        event_type: str,
        text: str,
        session_id: str,
        ui_key: str,
    ) -> None:
        """Persist reasoning/thinking with per-turn dedupe and minimum length guard."""
        text_stripped = (text or "").strip()
        if len(text_stripped) < _MIN_REASONING_LEN:
            return

        seen = _session_reasoning_keys.get(session_id)
        if seen is None:
            _maybe_evict_dict(_session_reasoning_keys)
            seen = set()
            _session_reasoning_keys[session_id] = seen

        _maybe_evict_set(seen)
        turn_bucket = int(_time.time()) // 300
        dedupe_key = f"{event_type}:{turn_bucket}:{text_stripped}"
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)

        await redis_client.rpush(
            ui_key,
            json.dumps({"type": event_type, "text": text_stripped, "ts": _time.time()}),
        )
        await redis_client.expire(ui_key, ttl)

    async def _after_event(
        executor_ctx: ExecutorContext,
        a2a_event,
        adk_event,
    ):
        try:
            # Resolve real user/session identity.  ContextVars do NOT propagate
            # when ADK spawns the agent execution in a new asyncio.Task.
            # PRIMARY source: shared_state["identity_by_session"] written by
            # _before_agent (plain dict — always visible across tasks).
            # FALLBACK 1: ContextVars (work when ADK happens to reuse the task).
            # FALLBACK 2: executor_ctx (ADK-generated IDs — last resort).
            session_id = _cv_session_id.get() or executor_ctx.session_id
            _identity  = _identity_by_session.get(session_id, {})
            user_id    = _identity.get("login_id") or _cv_login_id.get() or executor_ctx.user_id

            if not user_id or not session_id:
                log.warning("_after_event: missing user_id=%r or session_id=%r — skipping", user_id, session_id)
                return a2a_event
            log.info("_after_event: user=%r session=%r ev=%s (identity_source=%s)", user_id, session_id,
                     type(a2a_event).__name__,
                     "shared_state" if _identity.get("login_id") else ("contextvar" if _cv_login_id.get() else "executor_ctx"))

            # 1. Check explicit sharing
            if session_id not in _session_owner_cache:
                _maybe_evict_dict(_session_owner_cache)
                resolved_owner = None
                try:
                    raw = await redis_client.get(_key_session_shared(executor_ctx.app_name, session_id))
                    if raw:
                        resolved_owner = json.loads(raw).get("owner_id")
                    
                    if not resolved_owner:
                        vis_raw = await redis_client.get(_key_session_visibility(executor_ctx.app_name, session_id))
                        if vis_raw:
                            vis = json.loads(vis_raw)
                            if vis.get("public", False):
                                resolved_owner = vis.get("owner_id")
                                
                except Exception as _ce:
                    log.debug("_after_event: session owner lookup failed (%s) — using user_id", _ce)

                _session_owner_cache[session_id] = resolved_owner or user_id

            event_owner = _session_owner_cache[session_id]
            ui_key = _key_ui_events(executor_ctx.app_name, event_owner, session_id)

            # ── Resolve user text: shared_state (clean) → ContextVar → submitted event ──
            # shared_state["identity_by_session"] stores the CLEAN text captured
            # by _before_agent BEFORE the "[Question asked by user ...]" mutation.
            # Using it prevents dedup key mismatches with the eager user-msg write.
            if not _cv_user_text.get():
                _shared_text = _identity.get("user_text", "")
                if _shared_text:
                    _cv_user_text.set(_shared_text)
                    log.info("_after_event: user_text from shared_state len=%d", len(_shared_text))

            # Fallback: extract from the submitted A2A event (may contain the
            # "[Question asked by user ...]" mutation if the message object is shared).
            if not _cv_user_text.get() and isinstance(a2a_event, TaskStatusUpdateEvent):
                a2a_state = a2a_event.status.state if a2a_event.status else None
                if str(a2a_state) == "TaskState.submitted" and a2a_event.status.message:
                    submitted_parts = a2a_event.status.message.parts or []
                    submitted_bits  = []
                    for sp in submitted_parts:
                        root = getattr(sp, "root", sp)
                        if hasattr(root, "text") and root.text:
                            submitted_bits.append(root.text)
                    submitted_text = "\n".join(submitted_bits).strip()
                    if submitted_text:
                        _cv_user_text.set(submitted_text)
                        log.info("_after_event: user_text from submitted event len=%d: %r",
                                 len(submitted_text), submitted_text[:80])

            # Persist the user message ONCE per turn (not once per A2A event).
            # A single user turn produces multiple A2A events; only write the
            # user message the first time we see it for this session × turn.
            # turn_key includes a 5-minute time bucket so the same question asked
            # in a DIFFERENT turn (e.g., 10 am and 11 am) is NOT incorrectly deduped.
            # All events within the same ~5-min window ARE deduped (parallel stream events).
            user_text  = _cv_user_text.get()
            user_name  = _identity.get("user_name") or _cv_user_name.get() or (user_id.split("@")[0] if "@" in (user_id or "") else user_id or "unknown")
            turn_bucket = int(_time.time()) // 300   # 5-minute bucket
            turn_key   = f"{session_id}:{user_text}:{turn_bucket}"
            if user_text and turn_key not in _user_msg_written:
                _maybe_evict_set(_user_msg_written)
                _user_msg_written.add(turn_key)
                now = _time.time()
                await redis_client.rpush(
                    ui_key,
                    json.dumps({"type": "user", "text": user_text,
                                "user_id": user_id, "user_name": user_name, "ts": now}),
                )
                await redis_client.expire(ui_key, ttl)
                log.debug("_after_event: wrote user message for session=%s user=%s", session_id, user_id)

            # Register the session in Redis indexes the FIRST time only.
            # Always register when we have a real user_id (not A2A_USER_*) so the
            # session appears in the sidebar even if message_text() returned empty
            # (streaming requests don't always expose parts in _before_agent).
            if session_id not in _session_registered:
                _maybe_evict_set(_session_registered)
                now_reg = _time.time()
                title    = (user_text[:60] + ("…" if len(user_text) > 60 else "")
                            if user_text else "New conversation")
                zset_key = _key_sessions_zset(executor_ctx.app_name, user_id)
                meta_key = _key_session_meta(executor_ctx.app_name, user_id)
                ops = [
                    redis_client.zadd(zset_key, {session_id: now_reg}),
                    redis_client.hset(meta_key, session_id, title),
                    redis_client.expire(zset_key, ttl),
                    redis_client.expire(meta_key, ttl),
                ]

                # ── Shared session support ─────────────────────────────────
                participants_raw = _cv_participants.get()
                permission       = _cv_permission.get() or "read"
                if participants_raw:
                    ops.append(redis_client.set(
                        _key_session_shared(executor_ctx.app_name, session_id),
                        json.dumps({"owner_id": user_id, "participants": participants_raw,
                                    "permission": permission}),
                        ex=ttl,
                    ))
                    if participants_raw.strip().lower() == "all":
                        pub_key = _key_sessions_public(executor_ctx.app_name)
                        ops.append(redis_client.zadd(pub_key, {f"{user_id}:{session_id}": now_reg}))
                        ops.append(redis_client.expire(pub_key, ttl))
                    else:
                        for p in participants_raw.split(","):
                            p = p.strip()
                            if p and p != user_id:
                                p_zset = _key_sessions_zset(executor_ctx.app_name, p)
                                p_meta = _key_session_meta(executor_ctx.app_name, p)
                                ops.append(redis_client.zadd(p_zset, {session_id: now_reg}))
                                ops.append(redis_client.hset(p_meta, session_id, title))
                                ops.append(redis_client.expire(p_zset, ttl))
                                ops.append(redis_client.expire(p_meta, ttl))

                await asyncio.gather(*ops)
                _session_registered.add(session_id)
                log.debug("_after_event: registered session=%s user=%s title=%r", session_id, user_id, title)

            # Buffer the ASSISTANT's response text for the after_agent hook.
            # Rules:
            #   - Skip "submitted" state entirely — that carries the USER's question,
            #     not the LLM response. Writing it would save the question as the
            #     response if the LLM fails before emitting any "working" events.
            #   - artifact-update is authoritative (A2A 0.3 spec) — replaces buffer.
            #   - status-update "working" → keep the latest non-empty chunk.
            event_text = ""
            is_submitted = False

            if isinstance(a2a_event, TaskStatusUpdateEvent):
                a2a_state_str = str(a2a_event.status.state) if a2a_event.status else ""
                is_submitted  = (a2a_state_str == "TaskState.submitted")
                if not is_submitted and a2a_event.status and a2a_event.status.message:
                    parts = a2a_event.status.message.parts or []
                    bits: list[str] = []
                    # ── Diagnostic: count part types for thinking visibility ──
                    _n_text = _n_thought = _n_data = _n_file = 0
                    for p in parts:
                        root = getattr(p, "root", p)
                        _kind = type(root).__name__
                        if hasattr(root, "text") and root.text:
                            # ── Persist only genuine thinking for session replay ──
                            # Only adk_thought=true parts are persisted — these are
                            # real extended-thinking blocks from the LLM.  Persisting
                            # ALL text created stale "reasoning" entries that flooded
                            # the UI and hid real tool-call rendering.
                            _meta = getattr(root, "metadata", None) or {}
                            _is_thought = _meta.get("adk_thought") is True
                            if _is_thought:
                                _n_thought += 1
                                await _persist_reasoning_event(
                                    event_type="thinking",
                                    text=root.text,
                                    session_id=session_id,
                                    ui_key=ui_key,
                                )
                                # Do NOT append thought text to bits — it would
                                # leak into the visible response via _session_text_buf.
                            else:
                                _n_text += 1
                                await _persist_reasoning_event(
                                    event_type="reasoning",
                                    text=root.text,
                                    session_id=session_id,
                                    ui_key=ui_key,
                                )
                                bits.append(root.text)
                        elif _kind == "DataPart":
                            _n_data += 1
                            # ── Persist tool call / tool result progress events ──
                            _data = getattr(root, "data", None) or {}
                            _dmeta = getattr(root, "metadata", None) or {}
                            _adk_type = _dmeta.get("adk_type", "")
                            if _adk_type == "function_call" or (not _adk_type and _data.get("name") and _data.get("args") is not None):
                                _tool_name = _data.get("name", "unknown")
                                _call_id   = _data.get("id", "")
                                _tool_args = _data.get("args") or {}
                                _progress_ev = {
                                    "type": "progress", "tool": _tool_name,
                                    "call_id": _call_id, "status": "running",
                                    "args": _tool_args, "ts": _time.time(),
                                }
                                await redis_client.rpush(ui_key, json.dumps(_progress_ev))
                                await redis_client.expire(ui_key, ttl)
                            elif _adk_type == "function_response" or (not _adk_type and _data.get("response") is not None):
                                _tool_name = _data.get("name", "unknown")
                                _call_id   = _data.get("id", "")
                                _progress_ev = {
                                    "type": "progress", "tool": _tool_name,
                                    "call_id": _call_id, "status": "done",
                                    "ts": _time.time(),
                                }
                                await redis_client.rpush(ui_key, json.dumps(_progress_ev))
                                await redis_client.expire(ui_key, ttl)
                        elif _kind == "FilePart":
                            _n_file += 1
                    if _n_thought or _n_text:
                        log.info(
                            "_after_event: parts breakdown — thought=%d text=%d data=%d file=%d  session=%s",
                            _n_thought, _n_text, _n_data, _n_file, session_id,
                        )
                    event_text = "\n".join(bits)

            elif isinstance(a2a_event, TaskArtifactUpdateEvent):
                if a2a_event.artifact and a2a_event.artifact.parts:
                    bits = []
                    for p in a2a_event.artifact.parts:
                        root = getattr(p, "root", p)
                        if hasattr(root, "text") and root.text:
                            # ── Persist thinking from artifact-update events ──
                            # ADK 1.28+ sends model responses (including thought
                            # parts) as TaskArtifactUpdateEvent, not only as
                            # TaskStatusUpdateEvent.  Without this, intermediate
                            # thinking between tool calls is silently dropped.
                            _meta = getattr(root, "metadata", None) or {}
                            if _meta.get("adk_thought") is True:
                                await _persist_reasoning_event(
                                    event_type="thinking",
                                    text=root.text,
                                    session_id=session_id,
                                    ui_key=ui_key,
                                )
                            else:
                                await _persist_reasoning_event(
                                    event_type="reasoning",
                                    text=root.text,
                                    session_id=session_id,
                                    ui_key=ui_key,
                                )
                                bits.append(root.text)
                    event_text = "\n".join(bits)

            if event_text.strip() and not is_submitted:
                _maybe_evict_dict(_session_text_buf)
                if isinstance(a2a_event, TaskArtifactUpdateEvent):
                    _session_text_buf[session_id] = event_text  # authoritative — replace
                else:
                    _session_text_buf[session_id] = event_text  # keep latest working chunk

        except Exception as exc:
            log.warning("A2A ui_events persist failed (non-fatal): %s — user=%s session=%s",
                        exc, _cv_login_id.get(), _cv_session_id.get())

        return a2a_event

    async def _after_agent(
        executor_ctx: ExecutorContext,
        final_a2a_event,
    ):
        """Fires once after the agent finishes the turn.

        Writes the accumulated assistant text as a 'complete' event so the
        session replay (on page refresh) can reconstruct the full response.
        """
        try:
            session_id = _cv_session_id.get() or executor_ctx.session_id
            _identity  = _identity_by_session.get(session_id, {})
            user_id    = _identity.get("login_id") or _cv_login_id.get() or executor_ctx.user_id
            if not user_id or not session_id:
                return final_a2a_event

            event_owner = _session_owner_cache.get(session_id, user_id)
            ui_key      = _key_ui_events(executor_ctx.app_name, event_owner, session_id)
            final_text  = _session_text_buf.pop(session_id, "")

            # ── Get user question — shared_state (clean) → ContextVar → ADK events ──
            # shared_state has the CLEAN text from _before_agent (before mutation).
            # _cv_user_text may have it from _after_event.  ADK events is last resort
            # but may contain the "[Question asked by user ...]" mutation.
            user_text = _identity.get("user_text") or _cv_user_text.get()
            if not user_text:
                try:
                    from app.store.keys import key_events as _key_events_store
                    adk_evt_key = _key_events_store(
                        executor_ctx.app_name,
                        executor_ctx.user_id,   # ADK's own user_id (may be A2A_USER_*)
                        session_id,
                    )
                    raw_evts = await asyncio.wait_for(
                        redis_client.lrange(adk_evt_key, -100, -1), timeout=2.0
                    )
                    for raw in reversed(raw_evts):
                        ev_data = json.loads(raw)
                        content = ev_data.get("content") or {}
                        if content.get("role") == "user":
                            parts = content.get("parts", [])
                            
                            # Defensively exclude any event that contains function calls/responses 
                            # (some platforms shift these to the 'user' role to bypass LLM limits)
                            has_function_data = any(
                                "functionCall" in p or "functionResponse" in p or
                                "function_call" in p or "function_response" in p 
                                for p in parts
                            )
                            if has_function_data:
                                continue

                            for p in parts:
                                t = p.get("text", "").strip()
                                if t:
                                    user_text = t
                                    _cv_user_text.set(user_text)
                                    log.info("_after_agent: user_text from adk:events len=%d: %r",
                                             len(user_text), user_text[:80])
                                    break
                        if user_text:
                            break
                except Exception as _ue:
                    log.debug("_after_agent: adk:events user text lookup failed: %s", _ue)

            # ── Ordered writes: user → complete (ORDER MATTERS for replay) ─────────
            # Use same 5-min bucket as _after_event so the dedup sets stay in sync.
            turn_bucket = int(_time.time()) // 300
            turn_key    = f"{session_id}:{user_text}:{turn_bucket}"
            wrote_user  = False

            # 1. Write user message FIRST if not already written.
            if user_text and turn_key not in _user_msg_written:
                _user_msg_written.add(turn_key)
                user_name = _identity.get("user_name") or _cv_user_name.get() or (user_id.split("@")[0] if "@" in (user_id or "") else user_id or "unknown")
                await redis_client.rpush(
                    ui_key,
                    json.dumps({"type": "user", "text": user_text,
                                "user_id": user_id, "user_name": user_name,
                                "ts": _time.time()}),
                )
                wrote_user = True

            # 2. Write the assistant response AFTER user (correct replay order).
            #    Always write a "complete" event — even when final_text is empty
            #    (e.g. agent errored) — so the frontend poll detects turn completion
            #    immediately instead of waiting for the 2-minute safety cap.
            await redis_client.rpush(
                ui_key,
                json.dumps({"type": "complete", "text": final_text, "ts": _time.time()}),
            )
            await redis_client.expire(ui_key, ttl)
            _session_reasoning_keys.pop(session_id, None)
            log.info("_after_agent: wrote 'complete' session=%s user=%s len=%d wrote_user=%s",
                     session_id, user_id, len(final_text), wrote_user)

            # 3. Metadata updates (order-independent) — run concurrently.
            meta_ops = []
            if user_text:
                # Update title with real question (replaces "New conversation" placeholder).
                # Use event_owner so shared sessions update the OWNER's meta hash.
                meta_key = _key_session_meta(executor_ctx.app_name, event_owner)
                title    = user_text[:60] + ("…" if len(user_text) > 60 else "")
                meta_ops.append(redis_client.hset(meta_key, session_id, title))
            if meta_ops:
                await asyncio.gather(*meta_ops)

        except Exception as exc:
            log.warning("_after_agent complete event persist failed: %s — user=%s session=%s",
                        exc, _cv_login_id.get(), _cv_session_id.get())

        return final_a2a_event

    return _after_event, _after_agent


def _mount_a2a(app: FastAPI, runner: Runner) -> None:
    """Mount the ADK-native A2A endpoint using google-adk's A2aAgentExecutor.

    Includes:
    - POST /a2a                    — JSON-RPC message/send + message/stream (SSE)
    - GET  /.well-known/agent.json — Agent Card
    - UI event persistence via after_event interceptor
    - LLM header propagation via before_agent interceptor
    """
    agent_json_path = Path(__file__).parents[1] / "agent" / "agent.json"
    with agent_json_path.open("r", encoding="utf-8") as f:
        card_data = json.load(f)

    s = get_settings()
    base_url = f"http://{s.agent_host}:{s.agent_port}"
    card_data["url"] = f"{base_url}/a2a"
    agent_card = A2AAgentCard(**card_data)

    redis_client = runner.session_service._redis  # type: ignore[attr-defined]
    ttl = runner.session_service._ttl  # type: ignore[attr-defined]

    # Shared state between _before_agent and _build_interceptors so that the
    # user message written eagerly in _before_agent is correctly deduped by
    # the after_event/after_agent interceptors.
    _shared_state: dict = {
        "user_msg_written": set(),
        "session_owner_cache": {},
        # Maps executor_ctx.session_id (== frontend session_id == A2A context_id)
        # to {"login_id": ..., "user_name": ...}.  This is the PRIMARY identity
        # bridge from _before_agent → _after_event/_after_agent.  ContextVars do
        # NOT propagate when ADK spawns the agent in a separate asyncio.Task.
        "identity_by_session": {},
    }

    # Import key builders used by _before_agent for early user-message writes.
    from app.store.keys import key_ui_events as _key_ui_events_fn

    class _LLMHeaderContextBuilder(CallContextBuilder):
        """Captures request headers into ServerCallContext.state.

        Stores:
          - wm_llm_gw.*  headers  → propagated to the LLM gateway call
          - loginId / x-login-id  → actual user identity for Redis key generation
          - x-session-id          → frontend session ID for Redis key generation
        """
        def build(self, request: StarletteRequest) -> ServerCallContext:
            llm_headers = {
                k: v for k, v in request.headers.items()
                if k.startswith("wm_llm_gw.")
            }
            # Capture identity headers so after_event can store events under
            # the correct user/session keys instead of ADK-derived A2A_USER_* values.
            # x-login-id  — canonical header (lowercase, RFC-safe) set by a2a-client.ts
            # x-user-login-id — set by Next.js middleware on every authenticated request
            # loginid     — Starlette normalises "loginId" to lowercase; backward compat
            # wm_llm_gw.user_name — LLM-gateway user hint; last resort
            login_id = (
                request.headers.get("x-login-id")
                or request.headers.get("x-user-login-id")
                or request.headers.get("loginid")
                or request.headers.get("wm_llm_gw.user_name")
            )
            session_id = request.headers.get("x-session-id")
            state: dict[str, Any] = {}
            if llm_headers:
                state["llm_headers"] = llm_headers
            if login_id:
                state["login_id"] = login_id
            if session_id:
                state["session_id"] = session_id
            # Display name for tagging user messages in shared sessions
            user_name = (
                request.headers.get("x-user-name")
                or request.headers.get("wm_llm_gw.user_name")
                or (login_id.split("@")[0] if login_id else "")
            )
            if user_name:
                state["user_name"] = user_name
            # X-Session-Participants: "all"  or  "user1@x.com,user2@x.com"
            # X-Session-Permission:   "read" (default) | "write"
            participants = request.headers.get("x-session-participants", "")
            permission   = request.headers.get("x-session-permission", "read")
            if participants:
                state["participants"] = participants
                state["permission"]   = permission
            # User time context — sent by the browser so the LLM can resolve
            # natural-language times ("2AM to 10AM") to the correct UTC epoch ms.
            # x-user-timezone:    IANA timezone, e.g. "America/Los_Angeles"
            # x-current-epoch-ms: browser Date.now() at submit time
            if tz := request.headers.get("x-user-timezone"):
                state["timezone"]  = tz
            if epo := request.headers.get("x-current-epoch-ms"):
                state["epoch_ms"]  = epo
            # Capture user's PingFed bearer token for MCP servers that require
            # per-user auth (required_token=true — Jira, Confluence, etc.).
            # The SRE UI sends this as "Authorization: Bearer <token>" via
            # a2a-client.ts → buildUserHeaders().
            if auth := request.headers.get("authorization"):
                raw = auth.removeprefix("Bearer ").removeprefix("bearer ").strip()
                if raw:
                    state["user_token"] = raw
            return ServerCallContext(state=state)

    async def _before_agent(context: RequestContext) -> RequestContext:
        """Propagate per-request identity + LLM headers to downstream interceptors."""
        if context.call_context:
            state = context.call_context.state
            llm_headers = state.get("llm_headers", {})
            if llm_headers:
                set_llm_headers(llm_headers)
                log.debug("A2A: injected %d LLM headers from HTTP request", len(llm_headers))
            # Store real user/session IDs in contextvars so _after_event can use them.
            # ExecutorContext has no call_context field, so contextvars is the bridge.
            login_id = state.get("login_id", "")
            frontend_sid = state.get("session_id", "")
            if login_id:
                _cv_login_id.set(login_id)
            if frontend_sid:
                _cv_session_id.set(frontend_sid)
            user_name    = state.get("user_name", "")
            participants = state.get("participants", "")
            permission   = state.get("permission", "read")
            if user_name:
                _cv_user_name.set(user_name)
            if participants:
                _cv_participants.set(participants)
                _cv_permission.set(permission)
            # Propagate user time context so before_model_callback can inject
            # timezone + current epoch ms into the LLM system instruction.
            set_user_time_context(
                state.get("timezone", ""),
                state.get("epoch_ms", ""),
            )
            # Store user's PingFed bearer token so required_token MCP servers
            # (Jira, Confluence) authenticate as the real human, not the
            # service account.  Uses both contextvar (primary) and a
            # module-level dict keyed by session_id (fallback).
            user_token = state.get("user_token", "")
            if user_token:
                from app.request_context import set_user_token
                set_user_token(user_token, session_id=frontend_sid)
                log.info("A2A _before_agent: user PingFed token captured for MCP auth (len=%d)", len(user_token))

            log.info("A2A _before_agent: login_id=%r session_id=%r timezone=%r",
                     login_id, frontend_sid, state.get("timezone", ""))

            # ── PRIMARY identity bridge: shared_state (dict, not ContextVar) ──
            # ContextVars do NOT propagate when ADK spawns the agent in a new
            # asyncio.Task.  Store identity in the shared dict keyed by
            # frontend_sid (== executor_ctx.session_id == A2A context_id)
            # so _after_event/_after_agent can always resolve the real user.
            if frontend_sid and login_id:
                _shared_state["identity_by_session"][frontend_sid] = {
                    "login_id": login_id,
                    "user_name": user_name,
                }
                # Cap size — evict oldest half when over limit
                _id_map = _shared_state["identity_by_session"]
                if len(_id_map) > 2000:
                    _evict_keys = list(_id_map.keys())[:len(_id_map) // 2]
                    for _ek in _evict_keys:
                        _id_map.pop(_ek, None)

        # Extract user message text — try the official SDK helper first, then
        # fall back to manually iterating parts (belt-and-suspenders).
        try:
            user_text_captured = ""
            if context.message:
                # Method 1: official SDK helper
                sdk_text = context.message_text()
                if sdk_text and sdk_text.strip():
                    user_text_captured = sdk_text.strip()
                else:
                    # Method 2: manual iteration (fallback for SDK edge-cases)
                    for part in (context.message.parts or []):
                        root = getattr(part, "root", part)
                        t = getattr(root, "text", None)
                        if t and t.strip():
                            user_text_captured += ("\n" if user_text_captured else "") + t.strip()
            if user_text_captured:
                _cv_user_text.set(user_text_captured)

                # Store clean text in shared_state BEFORE the mutation below.
                # _after_event needs the un-mutated text for dedup consistency;
                # the "[Question asked by user ...]" prefix added later changes
                # the turn_key, causing a duplicate USER event.
                if frontend_sid and frontend_sid in _shared_state["identity_by_session"]:
                    _shared_state["identity_by_session"][frontend_sid]["user_text"] = user_text_captured

                # ── Eagerly write user message to Redis BEFORE any A2A events ──
                # ContextVars set here may not propagate to _after_event if ADK
                # spawns the event loop in a separate async Task.  Writing the
                # user message NOW guarantees it precedes thinking/progress
                # events, so a mid-stream page refresh shows the follow-up
                # question instead of orphaning intermediate events.
                import time as _ba_time
                _ba_user_name = user_name or (login_id.split("@")[0] if "@" in (login_id or "") else login_id or "unknown")
                _ba_bucket = int(_ba_time.time()) // 300
                _ba_turn_key = f"{frontend_sid}:{user_text_captured}:{_ba_bucket}"
                if _ba_turn_key not in _shared_state["user_msg_written"] and frontend_sid and login_id:
                    _shared_state["user_msg_written"].add(_ba_turn_key)
                    # Determine the event owner (session sharing support)
                    _ba_owner = _shared_state["session_owner_cache"].get(frontend_sid, login_id)
                    _ba_ui_key = _key_ui_events_fn(_AGENT_NAME, _ba_owner, frontend_sid)
                    try:
                        await redis_client.rpush(
                            _ba_ui_key,
                            json.dumps({"type": "user", "text": user_text_captured,
                                        "user_id": login_id, "user_name": _ba_user_name,
                                        "ts": _ba_time.time()}),
                        )
                        await redis_client.expire(_ba_ui_key, ttl)
                        log.info("_before_agent: eagerly wrote user message session=%s user=%s len=%d",
                                 frontend_sid, login_id, len(user_text_captured))
                    except Exception as _wr_exc:
                        # Non-fatal — _after_event will retry
                        log.warning("_before_agent: eager user-msg write failed: %s", _wr_exc)
                        _shared_state["user_msg_written"].discard(_ba_turn_key)

                # Mutate the message for the LLM context only.
                # (ui_events will read the clean _cv_user_text before this mutation takes effect).
                if login_id and hasattr(context.message, "parts") and context.message.parts:
                    root = getattr(context.message.parts[0], "root", context.message.parts[0])
                    if hasattr(root, "text"):
                        root.text = f"[Question asked by user {login_id}]:\n{root.text}"
                log.info("_before_agent: user_text captured (len=%d): %r",
                         len(user_text_captured), user_text_captured[:80])
            else:
                log.info("_before_agent: user_text NOT captured — context.message=%r parts=%r",
                         bool(context.message),
                         len(context.message.parts) if context.message and context.message.parts else 0)
        except Exception as exc:
            log.warning("_before_agent: could not extract user text: %s", exc)

        return context

    _after_event_fn, _after_agent_fn = _build_interceptors(redis_client, ttl, shared_state=_shared_state)
    interceptor = ExecuteInterceptor(
        before_agent=_before_agent,
        after_event=_after_event_fn,
        after_agent=_after_agent_fn,
    )

    config = A2aAgentExecutorConfig(
        execute_interceptors=[interceptor],
    )

    agent_executor = _GracefulA2aAgentExecutor(runner=runner, config=config)
    task_store = InMemoryTaskStore()
    push_config_store = InMemoryPushNotificationConfigStore()

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
        push_config_store=push_config_store,
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
        context_builder=_LLMHeaderContextBuilder(),
    )

    for route in a2a_app.routes(rpc_url="/a2a", agent_card_url="/.well-known/agent.json"):
        app.router.routes.append(route)

    log.info("A2A endpoint mounted — POST /a2a, GET /.well-known/agent.json (with UI event persistence)")


# ── LLM Header Middleware ──────────────────────────────────────────────────────


class LLMHeaderMiddleware:
    """Capture WM_LLM_GW.* headers from incoming requests and store them in
    async-safe contextvars so they are available deep in the call chain (LLM
    service, ADK runner, LiteLLM) without threading parameters explicitly.

    Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) to ensure
    the contextvar remains set for the full request lifecycle, including
    StreamingResponse bodies.  BaseHTTPMiddleware returns from dispatch()
    before the streaming body is iterated, so its finally-block would clear
    the contextvar before the LLM call ever runs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            set_llm_headers(extract_llm_headers(request))
            try:
                await self.app(scope, receive, send)
            finally:
                clear_llm_headers()
        else:
            await self.app(scope, receive, send)


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="A2A Health Agent",
        description=(
            "WCNP health intelligence agent. "
            "Combines MCP tool servers with Walmart LLM gateways to answer "
            "natural language questions about cluster health, latency, and deployments."
        ),
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    s = get_settings()

    # CORSMiddleware — origins and credential policy driven by settings.
    # allow_credentials=True enables the frontend to send cookies / auth headers.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # LLM Header Middleware — captures WM_LLM_GW.* headers from incoming
    # requests and stores them in async contextvars for downstream propagation
    # to LLM Gateway calls. Must be added before CORS so it runs for every request.
    application.add_middleware(LLMHeaderMiddleware)

    application.add_exception_handler(LLMError, llm_error_handler)                    # type: ignore[arg-type]
    application.add_exception_handler(MCPConnectionError, mcp_connection_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(AgentError, agent_error_handler)                # type: ignore[arg-type]

    application.include_router(health.router)
    application.include_router(query.router)
    application.include_router(sessions.router)
    application.include_router(mcp_validate.router)
    application.include_router(mcp_proxy.router)
    application.include_router(debug.router)
    application.include_router(faqs.router)

    return application
