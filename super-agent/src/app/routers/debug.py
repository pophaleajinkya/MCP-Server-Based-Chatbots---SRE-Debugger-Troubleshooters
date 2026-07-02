"""
Debug endpoints — inspect raw ADK session state, events, and tool calls.

GET /debug/session/{session_id}?user_id=admin
    Full session dump: state, ADK events (with tool call args + responses),
    and UI events (SSE progress log).

Intended for local development and incident triage only.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.constants import APP_NAME as _APP_NAME, DEFAULT_USER_ID as _DEFAULT_USER, SKILL_TOOLS as _SKILL_TOOLS
from app.store.keys import (
    key_events as _key_events,
    key_session as _key_session,
    key_ui_events as _key_ui_events,
    key_app_state as _key_app_state,
    key_user_state as _key_user_state,
)

from app.config import get_settings
from app.pingfed.store import _keys as _pingfed_keys, _bare_host, _get_redis as _get_pingfed_redis

log = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])


def _tool_category(name: str) -> str:
    """Return ``'skill'`` for SkillToolset tools, ``'tool'`` otherwise."""
    return "skill" if name in _SKILL_TOOLS else "tool"


def _parse_tool_calls(events: list[dict]) -> list[dict]:
    """Walk raw ADK events and extract tool call / response pairs.

    Each returned entry has:
      - ``turn``      – 0-based turn counter (increments on each user message)
      - ``call_id``   – function call id (or name when id absent)
      - ``tool``      – tool name
      - ``category``  – ``'skill'`` or ``'tool'``
      - ``label``     – human-friendly display label
      - ``args``      – full args dict
      - ``response``  – full response dict (None until the response event arrives)
      - ``ts_call``   – timestamp of the function_call event
      - ``ts_response`` – timestamp of the function_response event (None until seen)
    """
    calls: dict[str, dict] = {}  # keyed by call_id
    ordered: list[dict] = []
    turn = 0

    for ev in events:
        content = ev.get("content") or {}
        if content.get("role") == "user":
            turn += 1

        for part in content.get("parts") or []:
            fc = part.get("function_call") or part.get("functionCall")
            if fc:
                name = fc.get("name") or ""
                cid  = fc.get("id") or name or "<unknown>"
                category = _tool_category(name)
                label = f"🧩 {name}" if category == "skill" else (name or "unknown")
                entry = {
                    "turn":        turn,
                    "call_id":     cid,
                    "tool":        name,
                    "category":    category,
                    "label":       label,
                    "args":        fc.get("args", {}),
                    "response":    None,
                    "ts_call":     ev.get("timestamp"),
                    "ts_response": None,
                }
                calls[cid] = entry
                ordered.append(entry)

            fr = part.get("function_response") or part.get("functionResponse")
            if fr:
                name = fr.get("name") or ""
                cid  = fr.get("id") or name or "<unknown>"
                category = _tool_category(name)
                label = f"🧩 {name}" if category == "skill" else (name or "unknown")
                if cid in calls:
                    calls[cid]["response"]    = fr.get("response")
                    calls[cid]["ts_response"] = ev.get("timestamp")
                else:
                    # response arrived without a matching call (shouldn't happen)
                    ordered.append({
                        "turn":        turn,
                        "call_id":     cid,
                        "tool":        name,
                        "category":    category,
                        "label":       label,
                        "args":        None,
                        "response":    fr.get("response"),
                        "ts_call":     None,
                        "ts_response": ev.get("timestamp"),
                    })

    return ordered


# ── GET /debug/session/{session_id} ───────────────────────────────────────────

@router.get(
    "/session/{session_id}",
    summary="Full ADK session dump — state, events, tool calls",
)
async def debug_session(
    session_id: str,
    request: Request,
    user_id: str = Query(default=_DEFAULT_USER, description="User ID (default: admin)"),
) -> JSONResponse:
    """Return a complete debug view of an ADK session stored in Redis.

    Response shape::

        {
          "session_id": "...",
          "user_id": "...",
          "state": { ... },           # merged session / user / app state
          "event_count": N,
          "tool_calls": [ ... ],      # extracted tool call+response pairs
          "adk_events": [ ... ],      # raw ADK event list (full payloads)
          "ui_events": [ ... ]        # SSE progress log (tool labels, args, status)
        }

    ``adk_events`` contains the complete function_call/function_response/model
    payloads as stored by the RedisSessionService — use this to inspect exact
    LLM request content and MCP tool responses.
    """
    redis = request.app.state.runner.session_service._redis

    session_key   = _key_session(_APP_NAME, user_id, session_id)
    events_key    = _key_events(_APP_NAME, user_id, session_id)
    ui_events_key = _key_ui_events(_APP_NAME, user_id, session_id)
    app_state_key = _key_app_state(_APP_NAME)
    user_state_key = _key_user_state(_APP_NAME, user_id)

    try:
        session_raw, events_raw, ui_raw, app_state_raw, user_state_raw = await asyncio.wait_for(
            asyncio.gather(
                redis.get(session_key),
                redis.lrange(events_key, 0, -1),
                redis.lrange(ui_events_key, 0, -1),
                redis.get(app_state_key),
                redis.get(user_state_key),
            ),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("Redis error fetching debug session %s/%s: %s", user_id, session_id, exc)
        raise HTTPException(status_code=503, detail="session store temporarily unavailable") from exc

    if session_raw is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found for user {user_id!r}")

    session_doc  = json.loads(session_raw)
    adk_events   = [json.loads(r) for r in events_raw]
    ui_events    = [json.loads(r) for r in ui_raw]
    app_state    = json.loads(app_state_raw)  if app_state_raw  else {}
    user_state   = json.loads(user_state_raw) if user_state_raw else {}

    # Merge state scopes so the caller sees the same view the agent gets
    merged_state = {**session_doc.get("state", {})}
    for k, v in app_state.items():
        merged_state[f"app:{k}"] = v
    for k, v in user_state.items():
        merged_state[f"user:{k}"] = v

    tool_calls = _parse_tool_calls(adk_events)

    log.debug(
        "debug_session user=%s session=%s → %d adk_events  %d tool_calls  %d ui_events",
        user_id, session_id, len(adk_events), len(tool_calls), len(ui_events),
    )

    return JSONResponse({
        "session_id":       session_id,
        "user_id":          user_id,
        "last_update_time": session_doc.get("last_update_time"),
        "title":            session_doc.get("title"),
        "state":            merged_state,
        "event_count":      len(adk_events),
        "tool_calls":       tool_calls,
        "adk_events":       adk_events,
        "ui_events":        ui_events,
    })


# ── GET /debug/llm ─────────────────────────────────────────────────────────────

@router.get(
    "/llm",
    summary="LLM configuration — provider, model, and prompt caching status",
)
async def debug_llm(request: Request) -> JSONResponse:
    """Return the current LLM configuration and Anthropic prompt caching status.

    Prompt caching for Anthropic requires **both** conditions to be true:

    1. ``anthropic-beta: prompt-caching-2024-07-31`` present in ``extra_headers``
    2. ``cache_control: {"type": "ephemeral"}`` blocks inside the system/user
       messages that ADK sends to LiteLLM

    This endpoint reports the static config (headers set at startup).
    Whether ``cache_control`` blocks are actually sent is logged at runtime by
    ``_HeaderInjectingClient._log_caching_status()`` on every Anthropic call.

    Response shape::

        {
          "provider": "anthropic" | "azure",
          "model": "anthropic/claude-opus-4-6",
          "api_base": "https://...",
          "is_primary_llm": true,
          "extra_headers": { "anthropic-version": "...", ... },   # api_key redacted
          "prompt_caching": {
            "beta_header_present": false,
            "beta_header_value": null,
            "status": "DISABLED",
            "note": "..."
          }
        }
    """
    s = get_settings()

    # Pull extra_headers from the live LiteLlm model object stored on the runner
    llm_model = request.app.state.runner.agent.model
    raw_extra_headers: dict = {}
    if hasattr(llm_model, "_additional_args") and isinstance(llm_model._additional_args, dict):
        raw_extra_headers = llm_model._additional_args.get("extra_headers") or {}

    # Redact sensitive values but keep key names visible
    safe_headers = {
        k: ("<redacted>" if any(tok in k.lower() for tok in ("key", "secret", "token", "auth")) else v)
        for k, v in raw_extra_headers.items()
    }

    beta_value: str | None = raw_extra_headers.get("anthropic-beta")
    _CACHE_BETA_HEADERS = ("prompt-caching-2024-07-31", "extended-cache-ttl-2025-04-11")
    beta_present = beta_value in _CACHE_BETA_HEADERS

    if s.claude_is_primary_llm:
        if beta_present:
            cache_status = "HEADER_PRESENT — caching activates only when cache_control blocks are in messages"
            cache_note = (
                "The anthropic-beta header is set. Caching will be active for any message block "
                "that carries cache_control={'type':'ephemeral'}. Check runtime logs for confirmation."
            )
        else:
            cache_status = "DISABLED"
            cache_note = (
                "Prompt caching is NOT enabled. To enable it, add "
                "'anthropic-beta': 'prompt-caching-2024-07-31' to extra_headers in agent.py "
                "and mark the system prompt / tool definitions with cache_control blocks."
            )
    else:
        cache_status = "N/A"
        cache_note = "Prompt caching only applies to Anthropic models. Current provider is Azure/OpenAI."

    provider = "anthropic" if s.claude_is_primary_llm else "azure"
    model_str = f"anthropic/{s.claude_model}" if s.claude_is_primary_llm else f"azure/{s.openai_model}"
    api_base  = s.claude_gateway_url if s.claude_is_primary_llm else s.element_gateway_base_url

    return JSONResponse({
        "provider":       provider,
        "model":          model_str,
        "api_base":       api_base,
        "is_primary_llm": s.claude_is_primary_llm,
        "extra_headers":  safe_headers,
        "prompt_caching": {
            "beta_header_present": beta_present,
            "beta_header_value":   beta_value,
            "status":              cache_status,
            "note":                cache_note,
        },
    })


# ── GET /debug/tokens ──────────────────────────────────────────────────────────

@router.get(
    "/tokens",
    summary="PingFederate bearer token status — one entry per configured O2 cluster",
)
async def debug_tokens(request: Request) -> JSONResponse:
    """Inspect the PingFederate bearer token cached in Redis for every configured
    OpenObserve cluster.

    Reports the TTL, expiry state, and the pod that last acquired each token.
    The access_token value itself is **redacted** for safety.

    Response shape::

        {
          "clusters": [
            {
              "cluster_lb":   "intl.logs.prod.walmart.com",
              "redis_key":    "agent:{auth:intl.logs.prod.walmart.com}:token",
              "status":       "valid" | "stale" | "missing",
              "expires_at":   1712345678.0,
              "refresh_at":   1712340000.0,
              "ttl_seconds":  3600,
              "seconds_until_refresh": 600,
              "acquired_by":  "<pod-uuid>",
              "acquired_at":  1712341678.0,
              "has_token":    true
            }
          ],
          "sso_configured": true
        }
    """
    s = get_settings()
    # Use the pingfed store's own Redis connection (separate from the session service Redis)
    redis = await _get_pingfed_redis()

    now = time.time()
    clusters = []

    for url in s.pingfed_url_list:
        host = _bare_host(url)
        token_key, lock_key, _ = _pingfed_keys(url)

        try:
            fields_task = asyncio.create_task(redis.hgetall(token_key))
            ttl_task    = asyncio.create_task(redis.ttl(token_key))
            fields, ttl = await asyncio.wait_for(
                asyncio.gather(fields_task, ttl_task), timeout=3.0
            )
            fields = fields or {}
            ttl = ttl if ttl is not None else -2
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("debug_tokens: Redis error for %s: %s", host, exc)
            clusters.append({
                "cluster_lb": host,
                "redis_key":  token_key,
                "status":     "redis_error",
                "error":      str(exc),
            })
            continue

        has_token = bool(fields.get("access_token"))
        expires_at = float(fields.get("expires_at") or 0)
        refresh_at = float(fields.get("refresh_at") or 0)
        acquired_by = fields.get("acquired_by", "")
        acquired_at = float(fields.get("acquired_at") or 0)

        if not has_token or ttl == -2:
            status = "missing"
        elif expires_at > 0 and now >= expires_at:
            status = "expired"
        elif refresh_at > 0 and now >= refresh_at:
            status = "stale"   # valid but background refresh should be running
        else:
            status = "valid"

        clusters.append({
            "cluster_lb":             host,
            "redis_key":              token_key,
            "status":                 status,
            "has_token":              has_token,
            "expires_at":             expires_at or None,
            "refresh_at":             refresh_at or None,
            "ttl_seconds":            ttl if ttl >= 0 else None,
            "seconds_until_expiry":   round(expires_at - now) if expires_at else None,
            "seconds_until_refresh":  round(refresh_at - now) if refresh_at else None,
            "acquired_by":            acquired_by or None,
            "acquired_at":            acquired_at or None,
        })

    return JSONResponse({
        "clusters":       clusters,
        "sso_configured": bool(s.sso_username and s.sso_password),
        "configured_urls": s.pingfed_url_list,
    })
