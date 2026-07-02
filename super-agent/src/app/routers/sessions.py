"""
Sessions API — list and inspect Redis-backed ADK conversation sessions.

GET /sessions?user_id=admin
    Returns a list of conversation sessions for the given user,
    sorted by most recently updated. Each entry includes session_id,
    title (first user message), and last_update_time.

GET /sessions/{session_id}/messages?user_id=admin
    Returns the ordered message history for a session as
    [{role, content, timestamp}] suitable for rendering in the UI.

POST /sessions/{session_id}/inject_message
    Append out-of-band content to a session — for use by automated
    subsystems (e.g. openclaw monitoring, alertmanager, deployment-agent)
    that need to surface updates in the chat without going through the
    normal /a2a chat flow. Writes to the UI replay log AND the live SSE
    stream AND a per-turn LLM-priming queue, but NEVER to ``adk:events``,
    so the LLM's persistent conversation memory is untouched.

GET /sessions/{session_id}/events/subscribe
    SSE endpoint that the UI keeps open while a session is loaded; emits
    a frame for each event injected via POST /inject_message above.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field


from app.constants import APP_NAME as _APP_NAME, DEFAULT_USER_ID as _DEFAULT_USER, SKILL_TOOLS as _SKILL_TOOLS
from app.store.keys import (
    key_sessions_index as _key_sessions_index,
    key_sessions_zset as _key_sessions_zset,
    key_session_meta as _key_session_meta,
    key_session as _key_session,
    key_events as _key_events,
    key_ui_events as _key_ui_events,
    key_ui_stream as _key_ui_stream,
    key_llm_pending as _key_llm_pending,
    key_idem_inject as _key_idem_inject,
    key_sessions_public as _key_sessions_public,
    key_session_shared as _key_session_shared,
    key_session_visibility as _key_session_visibility,
)

# ── Idempotency TTL for inject_message dedup markers ──────────────────────────
# The window must be long enough to cover realistic producer retry budgets
# (scheduler retries, nginx ingress timeouts, mobile-client-resume scenarios)
# but short enough that the keyspace doesn't grow unbounded.  One hour is a
# pragmatic default — extend if producers retry over longer windows.
_INJECT_IDEM_TTL_SECONDS = 3600

# Max length of the Idempotency-Key header we accept.  Defends against callers
# jamming a 1 MB string in here and blowing up Redis keyspace.
_INJECT_IDEM_MAX_LEN = 256


class VisibilityUpdate(BaseModel):
    public: bool = False
    tags: list[str] = []
    user_id: str = _DEFAULT_USER

log = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])


# ── GET /sessions ─────────────────────────────────────────────────────────────

@router.get("/sessions", summary="List conversation sessions for a user")
async def list_sessions(
    request: Request,
    user_id: str = Query(default=_DEFAULT_USER, description="User ID (default: admin)"),
) -> JSONResponse:
    """Return all conversation sessions for *user_id*, newest first.

    Reads session IDs from the Redis set index, fetches metadata for each,
    and uses the first user message as the conversation title.

    Args:
        request: FastAPI request; accesses ``app.state.runner.session_service._redis``.
        user_id: The user whose sessions to list (default: ``"admin"``).

    Returns:
        JSON object with a ``sessions`` list, each item containing
        ``session_id``, ``title``, ``last_update_time``, and ``user_id``.
    """
    redis    = request.app.state.runner.session_service._redis
    zset_key = _key_sessions_zset(_APP_NAME, user_id)
    meta_key = _key_session_meta(_APP_NAME, user_id)

    # ── Fast path: ZSET + meta hash (2 commands, sub-millisecond) ─────────────
    # New sessions are indexed in a ZSET scored by last_update_time so we get
    # the sorted list and titles without touching individual session docs at all.
    try:
        sid_score_pairs, title_map = await asyncio.gather(
            redis.zrevrange(zset_key, 0, -1, withscores=True),
            redis.hgetall(meta_key),
        )
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("Redis error listing sessions for %s: %s", user_id, exc)
        return JSONResponse({"sessions": [], "error": "session store temporarily unavailable"})

    # ── Public / shared sessions (participants=all) ────────────────────────────
    # Fetch sessions shared with everyone and merge into the user's list.
    public_sessions: list[dict] = []
    try:
        pub_pairs = await asyncio.wait_for(
            redis.zrevrange(_key_sessions_public(_APP_NAME), 0, 49, withscores=True),
            timeout=3.0,
        )
        # Filter to only other-user sessions, then batch-fetch titles + visibility
        other_pub: list[tuple[str, str, float]] = []   # (owner_id, sid, ts)
        for member, ts in pub_pairs:
            parts = member.split(":", 1)
            if len(parts) == 2:
                owner_id, sid = parts
                if owner_id and sid and owner_id != user_id:
                    other_pub.append((owner_id, sid, ts))

        if other_pub:
            # Pipeline: 1 round-trip for ALL public session metadata
            async with redis.pipeline(transaction=False) as pipe:
                for owner_id, sid, _ in other_pub:
                    pipe.hget(_key_session_meta(_APP_NAME, owner_id), sid)
                    pipe.get(_key_session_visibility(_APP_NAME, sid))
                pub_results = await asyncio.wait_for(pipe.execute(), timeout=3.0)

            for idx, (owner_id, sid, ts) in enumerate(other_pub):
                title   = pub_results[idx * 2]
                vis_raw = pub_results[idx * 2 + 1]
                tags: list[str] = []
                public_flag = True
                if vis_raw:
                    try:
                        vis = json.loads(vis_raw)
                        tags = vis.get("tags", [])
                        public_flag = vis.get("public", True)
                    except Exception:
                        pass
                public_sessions.append({
                    "session_id":       sid,
                    "title":            title or "Shared analysis",
                    "last_update_time": ts,
                    "user_id":          owner_id,
                    "shared_by":        owner_id,
                    "permission":       "write",
                    "public":           public_flag,
                    "tags":             tags,
                })
    except Exception as exc:
        log.debug("Could not fetch public sessions: %s", exc)

    if sid_score_pairs or public_sessions:
        # Pipeline: batch-fetch shared + visibility for ALL own sessions (1 round-trip)
        own_sessions = []
        own_results: list = []
        if sid_score_pairs:
            try:
                async with redis.pipeline(transaction=False) as pipe:
                    for sid, _ in sid_score_pairs:
                        pipe.get(_key_session_shared(_APP_NAME, sid))
                        pipe.get(_key_session_visibility(_APP_NAME, sid))
                    own_results = await asyncio.wait_for(pipe.execute(), timeout=5.0)
            except (asyncio.TimeoutError, Exception) as exc:
                log.warning("Redis pipeline error fetching session metadata for %s: %s", user_id, exc)

            for idx, (sid, ts) in enumerate(sid_score_pairs):
                entry: dict = {
                    "session_id":       sid,
                    "title":            title_map.get(sid) or "New conversation",
                    "last_update_time": ts,
                    "user_id":          user_id,
                }
                try:
                    shared_raw = own_results[idx * 2]
                    vis_raw    = own_results[idx * 2 + 1]
                    if shared_raw:
                        meta = json.loads(shared_raw)
                        owner = meta.get("owner_id", user_id)
                        if owner != user_id:
                            entry["shared_by"]  = owner
                            entry["permission"] = meta.get("permission", "read")
                            entry["user_id"]    = owner
                    if vis_raw:
                        vis = json.loads(vis_raw)
                        entry["public"] = vis.get("public", False)
                        entry["tags"]   = vis.get("tags", [])
                except Exception:
                    pass
                own_sessions.append(entry)

        # Merge and sort by last_update_time descending
        all_sessions = sorted(
            own_sessions + public_sessions,
            key=lambda s: s["last_update_time"],
            reverse=True,
        )
        log.debug("list_sessions (zset) user=%s → %d own + %d shared", user_id, len(own_sessions), len(public_sessions))
        return JSONResponse({"sessions": all_sessions})

    # ── Legacy fallback: old SET index (sessions created before ZSET migration) ─
    # Runs only for users who have never created a session since the migration.
    # Once they send their first new message, the ZSET path takes over forever.
    try:
        sids: set = await asyncio.wait_for(
            redis.smembers(_key_sessions_index(_APP_NAME, user_id)), timeout=5.0
        )
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("Redis timeout listing sessions (legacy) for %s: %s", user_id, exc)
        return JSONResponse({"sessions": [], "error": "session store temporarily unavailable"})

    if not sids:
        return JSONResponse({"sessions": []})

    sid_list = list(sids)
    try:
        async with redis.pipeline(transaction=False) as pipe:
            for sid in sid_list:
                pipe.get(_key_session(_APP_NAME, user_id, sid))
            raws: list = await asyncio.wait_for(pipe.execute(), timeout=10.0)
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("Redis error fetching session docs (legacy) for %s: %s", user_id, exc)
        return JSONResponse({"sessions": [], "error": "session store temporarily unavailable"})

    missing_title_sids = [
        sid for sid, raw in zip(sid_list, raws)
        if raw is not None and not json.loads(raw).get("title")
    ]
    events_by_sid: dict[str, list] = {}
    if missing_title_sids:
        try:
            async with redis.pipeline(transaction=False) as pipe:
                for sid in missing_title_sids:
                    pipe.lrange(_key_events(_APP_NAME, user_id, sid), 0, 5)
                results = await asyncio.wait_for(pipe.execute(), timeout=10.0)
            events_by_sid = dict(zip(missing_title_sids, results))
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("Redis timeout fetching events for title resolution (%s): %s", user_id, exc)

    sessions = []
    for sid, raw in zip(sid_list, raws):
        if raw is None:
            continue

        doc         = json.loads(raw)
        last_update = doc.get("last_update_time", 0.0)
        title       = doc.get("title")

        if not title:
            title = "New conversation"
            for ev_raw in events_by_sid.get(sid, []):
                ev      = json.loads(ev_raw)
                content = ev.get("content") or {}
                if content.get("role") == "user":
                    for part in content.get("parts", []):
                        text = (part.get("text") or "").strip()
                        if text:
                            title = text[:60] + ("…" if len(text) > 60 else "")
                            break
                    if title != "New conversation":
                        break

        sessions.append({
            "session_id":       sid,
            "title":            title,
            "last_update_time": last_update,
            "user_id":          user_id,
        })

    sessions.sort(key=lambda s: s["last_update_time"], reverse=True)
    log.debug("list_sessions (legacy) user=%s → %d sessions", user_id, len(sessions))
    return JSONResponse({"sessions": sessions})


# ── GET /sessions/{session_id}/messages ───────────────────────────────────────

@router.get(
    "/sessions/{session_id}/messages",
    summary="Get message history for a session",
)
async def get_session_messages(
    session_id: str,
    request: Request,
    user_id: str = Query(default=_DEFAULT_USER, description="User ID (default: admin)"),
) -> JSONResponse:
    """Return all user and assistant messages for *session_id*.

    Reads events from the Redis LIST, filters for ``user`` and ``model``
    role entries, and extracts text content.

    Args:
        session_id: The Redis session ID to fetch.
        request:    FastAPI request; accesses the Redis client.
        user_id:    The user who owns this session (default: ``"admin"``).

    Returns:
        JSON object with ``session_id`` and ``messages`` list.
        Each message has ``role`` (``"user"``/``"assistant"``),
        ``content`` (plain text), and ``timestamp`` (Unix float).
    """
    redis = request.app.state.runner.session_service._redis

    # ── New path: UI event log (event-sourced, exact replay) ──────────────────
    try:
        ui_raw = await asyncio.wait_for(
            redis.lrange(_key_ui_events(_APP_NAME, user_id, session_id), 0, -1),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("Redis timeout fetching ui_events for session %s: %s", session_id, exc)
        return JSONResponse({"session_id": session_id, "messages": [], "events": [],
                             "error": "session store temporarily unavailable"}, status_code=503)
    # ── Shared session fallback: if viewer's user_id owns no data, check exact keys first ─────────
    if not ui_raw:
        owner_uid: str | None = None
        # 1. Check explicit sharing
        raw_shared = await redis.get(_key_session_shared(_APP_NAME, session_id))
        if raw_shared:
            try:
                owner_uid = json.loads(raw_shared).get("owner_id")
            except Exception:
                pass
        
        # 2. Check public visibility
        if not owner_uid:
            raw_vis = await redis.get(_key_session_visibility(_APP_NAME, session_id))
            if raw_vis:
                try:
                    vis = json.loads(raw_vis)
                    if vis.get("public", False) and "owner_id" in vis:
                        owner_uid = vis["owner_id"]
                except Exception:
                    pass

        # 3. Fallback to slow scan if still not found
        if not owner_uid:
            scan_pattern = _key_ui_events(_APP_NAME, "*", session_id)
            try:
                async def _scan_owner():
                    async for raw_key in redis.scan_iter(match=scan_pattern, count=200):
                        raw_key = raw_key if isinstance(raw_key, str) else raw_key.decode()
                        prefix = f"agent:ui_events:{_APP_NAME}:"
                        suffix = f":{session_id}"
                        if raw_key.startswith(prefix) and raw_key.endswith(suffix):
                            return raw_key[len(prefix):-len(suffix)]
                    return None
                owner_uid = await asyncio.wait_for(_scan_owner(), timeout=3.0)
            except (asyncio.TimeoutError, Exception) as exc:
                log.warning("Redis scan for shared session %s failed: %s", session_id, exc)

        if owner_uid and owner_uid != user_id:
            log.debug("get_session_messages: shared session %s owned by %s (viewer: %s)", session_id, owner_uid, user_id)
            try:
                ui_raw = await asyncio.wait_for(
                    redis.lrange(_key_ui_events(_APP_NAME, owner_uid, session_id), 0, -1),
                    timeout=5.0,
                )
                user_id = owner_uid  # use owner for legacy fallback too
            except (asyncio.TimeoutError, Exception) as exc:
                log.warning("Redis error fetching shared session %s for owner %s: %s", session_id, owner_uid, exc)

    if ui_raw:
        events = [json.loads(r) for r in ui_raw]

        # Also build legacy messages shape for backward-compat consumers (useChat.ts etc.)
        messages: list[dict] = []
        pending_tool_calls: list[dict] = []
        for ev in events:
            t = ev.get("type")
            if t == "user":
                pending_tool_calls = []
                msg_entry = {"role": "user", "content": ev.get("text", ""), "timestamp": ev.get("ts", 0.0)}
                if "user_id" in ev:
                    msg_entry["user_id"] = ev["user_id"]
                if "user_name" in ev:
                    msg_entry["user_name"] = ev["user_name"]
                messages.append(msg_entry)
            elif t == "progress" and ev.get("args"):
                tc_entry: dict = {"name": ev["tool"], "args": ev["args"]}
                if "category" in ev:
                    tc_entry["category"] = ev["category"]
                if "label" in ev:
                    tc_entry["label"] = ev["label"]
                pending_tool_calls.append(tc_entry)
            elif t == "complete":
                entry: dict = {"role": "assistant", "content": ev.get("text", ""), "timestamp": ev.get("ts", 0.0)}
                if pending_tool_calls:
                    entry["tool_calls"] = pending_tool_calls
                messages.append(entry)
                pending_tool_calls = []

        log.debug("get_session_messages user=%s session=%s → %d events (event-sourced)", user_id, session_id, len(events))
        return JSONResponse({"session_id": session_id, "messages": messages, "events": events})

    # ── Fallback 1: reconstruct from ADK events under the caller's user_id ──────
    # (covers sessions created before the ui_events migration)
    try:
        events_raw = await asyncio.wait_for(
            redis.lrange(_key_events(_APP_NAME, user_id, session_id), 0, -1),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("Redis timeout fetching events for session %s: %s", session_id, exc)
        return JSONResponse({"session_id": session_id, "messages": [], "events": [],
                             "error": "session store temporarily unavailable"}, status_code=503)

    # ── Fallback 2: scan for ADK events under ANY user_id ─────────────────────
    # This handles sessions where the frontend request had no loginId header so
    # ADK stored events under A2A_USER_{contextId} instead of the real user.
    if not events_raw:
        adk_scan_pattern = _key_events(_APP_NAME, "*", session_id)
        adk_owner_uid: str | None = None
        try:
            async def _scan_adk_owner():
                async for raw_key in redis.scan_iter(match=adk_scan_pattern, count=200):
                    raw_key = raw_key if isinstance(raw_key, str) else raw_key.decode()
                    prefix  = f"adk:events:{_APP_NAME}:"
                    suffix  = f":{session_id}"
                    if raw_key.startswith(prefix) and raw_key.endswith(suffix):
                        uid = raw_key[len(prefix):-len(suffix)]
                        if uid:  # guard against empty owner
                            return uid
                return None
            adk_owner_uid = await asyncio.wait_for(_scan_adk_owner(), timeout=3.0)
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("Redis scan for adk:events of session %s failed: %s", session_id, exc)

        if adk_owner_uid and adk_owner_uid != user_id:
            log.debug("get_session_messages: adk fallback — session %s owned by %s (viewer: %s)",
                      session_id, adk_owner_uid, user_id)
            try:
                events_raw = await asyncio.wait_for(
                    redis.lrange(_key_events(_APP_NAME, adk_owner_uid, session_id), 0, -1),
                    timeout=5.0,
                )
            except (asyncio.TimeoutError, Exception) as exc:
                log.warning("Redis error fetching adk:events for owner %s session %s: %s",
                            adk_owner_uid, session_id, exc)

    messages = []
    for ev_raw in events_raw:
        ev      = json.loads(ev_raw)
        content = ev.get("content") or {}
        role    = content.get("role", "")
        if role not in ("user", "model"):
            continue
        parts     = content.get("parts", [])
        text_bits = [p.get("text", "").strip() for p in parts if p.get("text")]
        text      = "\n".join(text_bits).strip()
        tool_calls = []
        for part in parts:
            fc   = part.get("function_call") or part.get("functionCall") or {}
            name = fc.get("name") or ""
            if name:
                cat = "skill" if name in _SKILL_TOOLS else "tool"
                tool_calls.append({"name": name, "args": fc.get("args") or {}, "category": cat})
        if not text and not tool_calls:
            continue
        entry = {"role": "user" if role == "user" else "assistant", "content": text, "timestamp": ev.get("timestamp", 0.0)}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        messages.append(entry)

    log.debug("get_session_messages user=%s session=%s → %d messages (legacy ADK fallback)", user_id, session_id, len(messages))
    return JSONResponse({"session_id": session_id, "messages": messages})


# ── PATCH /sessions/{session_id}/visibility ───────────────────────────────────

@router.patch(
    "/sessions/{session_id}/visibility",
    summary="Set session visibility and custom tags",
)
async def update_session_visibility(
    session_id: str,
    request: Request,
    body: VisibilityUpdate = Body(...),
) -> JSONResponse:
    """Make a session public and/or attach custom tags (e.g. 'Alert', 'Incident').

    - ``public=true``  → session appears in everyone's Public section
    - ``tags=["Alert"]`` → session appears in named tag sections
    - ``user_id`` must be the session owner

    Public sessions are added to the global public ZSET so all users see them.
    Visibility metadata is stored separately from event data.
    """
    redis   = request.app.state.runner.session_service._redis
    ttl     = request.app.state.runner.session_service._ttl
    user_id = body.user_id
    now     = __import__("time").time()

    vis_key = _key_session_visibility(_APP_NAME, session_id)
    vis_data = {
        "public": body.public,
        "tags": body.tags,
        "owner_id": user_id,
        "adk_user_id": f"A2A_USER_{session_id}"
    }

    ops = [redis.set(vis_key, json.dumps(vis_data), ex=ttl)]

    if body.public:
        pub_key = _key_sessions_public(_APP_NAME)
        ops.append(redis.zadd(pub_key, {f"{user_id}:{session_id}": now}))
        ops.append(redis.expire(pub_key, ttl))
    else:
        # Remove from public index if set to private
        pub_key = _key_sessions_public(_APP_NAME)
        ops.append(redis.zrem(pub_key, f"{user_id}:{session_id}"))

    await asyncio.gather(*ops)
    log.info("session_visibility user=%s session=%s public=%s tags=%s",
             user_id, session_id, body.public, body.tags)
    return JSONResponse({"session_id": session_id, "public": body.public, "tags": body.tags})


# ── Generic out-of-band injection (lifecycle / monitoring / external producers) ──
#
# The two endpoints below let external producers (openclaw monitoring loops,
# alertmanager, deployment-agent, manual operators) push content into a session
# without going through the chat /a2a path.  super-agent is intentionally
# AGNOSTIC about content semantics:
#
#   - Body is just ``{ "content": "<markdown>" }``.
#   - No alert_id, verdict, source, or any other producer-specific field.
#   - Producers are expected to embed any structure they need INSIDE the
#     markdown content (headings, callouts, tables, links).
#
# Three writes happen on inject_message; NONE of them touch ``adk:events`` so
# the LLM's persistent memory (Store B) is never contaminated:
#
#   1. ``agent:ui_events``  (LIST)   – appended for replay on session-open
#                                       via GET /sessions/{id}/messages.
#   2. ``agent:ui_stream``  (STREAM) – tailed by /events/subscribe SSE so live
#                                       viewers see the update immediately.
#   3. ``agent:llm_pending`` (STREAM) – drained by inject_pending_observations
#                                       on the next user turn and inserted into
#                                       the in-memory session.events as an
#                                       ephemeral [SYSTEM CONTEXT] block.


class InjectMessageBody(BaseModel):
    """Generic injection payload — single ``content`` field, nothing else."""
    content: str = Field(..., min_length=1, description="Markdown content to surface in the session.")


def _user_id_from_headers(request: Request, query_uid: str) -> str:
    """Resolve the effective user_id for a request.

    Priority:
      1. Explicit ``?user_id=`` query param if it differs from the system default
         (i.e. the caller deliberately set it).
      2. Standard identity headers used everywhere else in the system —
         ``x-login-id`` first, then ``wm_llm_gw.user_name`` / ``WM_LLM_GW.USER_NAME``,
         then plain ``loginId``.
      3. Fall back to the query param value (which may be the default).

    This lets external producers (openclaw, alertmanager, deployment-agent, …)
    forget about ``?user_id=`` and just send the same identity headers the rest
    of super-agent already honors. Without this fallback, any producer that
    omits ``?user_id=`` would write to ``_DEFAULT_USER``'s key namespace while
    the UI subscribes under the actual loginId — and the UI would silently see
    nothing.
    """
    if query_uid and query_uid != _DEFAULT_USER:
        return query_uid

    headers = request.headers  # case-insensitive
    for h in ("x-login-id", "wm_llm_gw.user_name", "loginid"):
        v = headers.get(h)
        if v and v.strip():
            return v.strip()
    return query_uid


async def _resolve_session_owner(redis, session_id: str, fallback_uid: str) -> str:
    """Resolve the canonical owner uid for a session.

    Priority:
      1. ``agent:session_shared``  → owner_id (explicit share record)
      2. ``agent:session_visibility`` → owner_id (public visibility record)
      3. ``fallback_uid`` (the caller-supplied / header-derived user_id)

    We deliberately do NOT scan keyspace here — that's a slow O(N) op and
    inject_message is on a hot path (every monitoring tick).  Producers are
    expected to either pass the right user_id query param / header or to have
    the session marked public/shared first.
    """
    try:
        raw_shared = await redis.get(_key_session_shared(_APP_NAME, session_id))
        if raw_shared:
            owner = json.loads(raw_shared).get("owner_id")
            if owner:
                return owner
    except Exception as exc:
        log.debug("_resolve_session_owner shared-lookup failed for %s: %s", session_id, exc)

    try:
        raw_vis = await redis.get(_key_session_visibility(_APP_NAME, session_id))
        if raw_vis:
            vis = json.loads(raw_vis)
            if vis.get("owner_id"):
                return vis["owner_id"]
    except Exception as exc:
        log.debug("_resolve_session_owner visibility-lookup failed for %s: %s", session_id, exc)

    return fallback_uid


@router.post(
    "/sessions/{session_id}/inject_message",
    summary="Append out-of-band markdown content to a session (UI replay + live SSE + next-turn LLM context)",
)
async def inject_message(
    session_id: str,
    body: InjectMessageBody,
    request: Request,
    user_id: str = Query(default=_DEFAULT_USER),
) -> JSONResponse:
    """Generic injection endpoint for any external producer.

    Writes to three independent Redis keys:
      - ``agent:ui_events``  (LIST)   – replay on session open
      - ``agent:ui_stream``  (STREAM) – live SSE delivery
      - ``agent:llm_pending`` (STREAM) – primed into LLM context on next turn

    Never writes to ``adk:events`` (Store B); the LLM's persistent
    conversation memory is uncontaminated.
    """
    redis = request.app.state.runner.session_service._redis
    ttl   = request.app.state.runner.session_service._ttl
    effective_uid = _user_id_from_headers(request, user_id)
    owner = await _resolve_session_owner(redis, session_id, effective_uid)
    ts    = time.time()

    # ── Idempotency ──────────────────────────────────────────────────────────
    # Producers that retry on network failure (scheduler ticks, ingress
    # timeouts, mobile reconnects) must carry a STABLE ``Idempotency-Key``
    # header derived from the logical event — e.g.
    # ``lc:<alert_id>:<kind>:<verdict>:<attempt>``.  First arrival: we SET NX
    # the dedup marker (atomic "claim") and perform the triple-write.
    # Any subsequent arrival carrying the same key sees the marker already
    # exists and is short-circuited with ``deduplicated=true`` — no
    # additional writes, no duplicate UI card, no duplicate LLM observation.
    #
    # When the header is absent we fall through to the normal write path
    # (producers that don't care about retries don't pay any cost).  We do
    # NOT auto-generate a key on behalf of the caller: that would defeat the
    # purpose (different retries would get different keys).
    idem_header = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    if idem_header:
        idem_header = idem_header.strip()[:_INJECT_IDEM_MAX_LEN]
    if idem_header:
        idem_key = _key_idem_inject(_APP_NAME, owner, session_id, idem_header)
        try:
            claimed = await redis.set(idem_key, str(ts), nx=True, ex=_INJECT_IDEM_TTL_SECONDS)
        except Exception as exc:
            # Redis failure on the dedup marker must NOT block the underlying
            # write — fall through and treat as first-arrival.  We'd rather
            # over-deliver than drop a lifecycle update.
            log.warning(
                "inject_message idempotency SET NX failed (falling through): %s", exc,
            )
            claimed = True
        if not claimed:
            log.info(
                "inject_message session=%s owner=%s deduplicated key=%s",
                session_id, owner, idem_header[:64],
            )
            return JSONResponse({
                "ok": True,
                "ts": ts,
                "session_id": session_id,
                "deduplicated": True,
            })

    payload = json.dumps({
        "type":    "injection",
        "content": body.content,
        "ts":      ts,
    })

    ui_events_k   = _key_ui_events(_APP_NAME,   owner, session_id)
    ui_stream_k   = _key_ui_stream(_APP_NAME,   owner, session_id)
    llm_pending_k = _key_llm_pending(_APP_NAME, owner, session_id)

    pipe = redis.pipeline(transaction=False)
    pipe.rpush(ui_events_k, payload)
    pipe.expire(ui_events_k, ttl)
    pipe.xadd(ui_stream_k,   {"data": payload}, maxlen=1000, approximate=True)
    pipe.expire(ui_stream_k, ttl)
    pipe.xadd(llm_pending_k, {"data": payload}, maxlen=1000, approximate=True)
    pipe.expire(llm_pending_k, ttl)
    await pipe.execute()

    log.info(
        "inject_message session=%s owner=%s len=%d idem=%s",
        session_id, owner, len(body.content), (idem_header or "-")[:64],
    )
    return JSONResponse({"ok": True, "ts": ts, "session_id": session_id})


@router.get(
    "/sessions/{session_id}/events/subscribe",
    summary="SSE subscription for live session events (out-of-band injections)",
)
async def subscribe_events(
    session_id: str,
    request: Request,
    user_id: str = Query(default=_DEFAULT_USER),
):
    """SSE stream that tails ``agent:ui_stream`` for this session.

    Delivery model:
      - Default first-connect (no ``Last-Event-ID`` header): deliver only
        entries added *after* the subscription starts.  Matches the original
        behaviour so existing clients see no change.
      - Reconnect (EventSource auto-sends the last ``id:`` it saw as
        ``Last-Event-ID``): replay every Stream entry newer than that id, then
        continue tailing.  This is what rescues the UI from laptop-sleep /
        network-blip gaps without a page refresh.

    Each SSE frame carries an ``id: <redis_stream_id>`` line so the browser's
    EventSource stashes it in ``.lastEventId`` and resends it on reconnect —
    no UI-side replay bookkeeping required.

    Heartbeat: a ``: ping`` comment every 15s keeps proxies / load-balancers
    from idling the connection.
    """
    redis    = request.app.state.runner.session_service._redis
    effective_uid = _user_id_from_headers(request, user_id)
    owner    = await _resolve_session_owner(redis, session_id, effective_uid)
    stream_k = _key_ui_stream(_APP_NAME, owner, session_id)

    # ── Resume cursor ────────────────────────────────────────────────────────
    # Redis Stream IDs look like ``1776734822169-0``; any non-empty header that
    # doesn't match this shape is ignored and we fall back to "$" to avoid
    # triggering Redis errors from malformed client input.  ``?last_event_id=``
    # is accepted as a query-param fallback for clients that can't set the
    # header (rare, but makes debugging with curl easy).
    last_event_id = (
        request.headers.get("last-event-id")
        or request.query_params.get("last_event_id")
        or ""
    ).strip()
    if last_event_id and _is_valid_stream_id(last_event_id):
        initial_id = last_event_id
        log.info(
            "subscribe_events resume session=%s owner=%s from=%s",
            session_id, owner, last_event_id,
        )
    else:
        initial_id = "$"

    async def event_iter():
        last_id = initial_id
        _consecutive_failures = 0
        _MAX_FAILURES_BEFORE_REINIT = 5
        while True:
            if await request.is_disconnected():
                return
            try:
                resp = await redis.xread({stream_k: last_id}, block=15_000, count=20)
                _consecutive_failures = 0  # reset on success
            except Exception as exc:
                _consecutive_failures += 1
                log.warning("subscribe_events xread failed for %s (%d): %s",
                            session_id, _consecutive_failures, exc)
                # After several consecutive failures, force cluster slot re-discovery.
                # This recovers from stale topology cache after transient network blips.
                if _consecutive_failures >= _MAX_FAILURES_BEFORE_REINIT:
                    try:
                        await redis.initialize()
                        log.info("subscribe_events: cluster re-initialized for %s", session_id)
                        _consecutive_failures = 0
                    except Exception as reinit_exc:
                        log.warning("subscribe_events: cluster re-init failed for %s: %s",
                                    session_id, reinit_exc)
                yield ": ping\n\n"
                await asyncio.sleep(1)
                continue
            if not resp:
                yield ": ping\n\n"
                continue
            for _stream_name, entries in resp:
                for entry_id, fields in entries:
                    last_id = entry_id if isinstance(entry_id, str) else entry_id.decode()
                    # decode_responses=True on the cluster gives str keys, but be
                    # defensive: try both str and bytes key forms.
                    raw = None
                    if isinstance(fields, dict):
                        raw = fields.get("data")
                        if raw is None:
                            raw = fields.get(b"data")
                    if raw is None:
                        continue
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode()
                    # SSE ``id:`` line → browser stashes it on EventSource and
                    # resends as Last-Event-ID on auto-reconnect.  Must be a
                    # single line (no newlines in Redis IDs, so safe).
                    yield f"id: {last_id}\ndata: {raw}\n\n"

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Stream-ID validation ──────────────────────────────────────────────────────
# Redis XADD returns IDs of the shape "<milliseconds>-<seq>" (e.g.
# "1776734822169-0").  We accept only this exact pattern from clients to avoid
# forwarding arbitrary strings into XREAD, which would either error or — worse
# — be interpreted as special values like "$" / "0-0" / ">".
import re as _re  # local import keeps module-top imports minimal
_STREAM_ID_RE = _re.compile(r"^\d+-\d+$")


def _is_valid_stream_id(s: str) -> bool:
    """True if *s* is a well-formed Redis Stream entry ID (``ms-seq``)."""
    return bool(s) and bool(_STREAM_ID_RE.match(s))
