"""
Redis-backed ADK session service.

Implements ``BaseSessionService`` using Redis Cluster as the persistence layer,
following the same patterns as ADK's ``DatabaseSessionService`` (state delta
extraction, merging, append_event semantics).

Redis key patterns are defined in ``app.store.keys`` and imported here to keep
a single source of truth.  All session-scoped keys share a TTL (default 7 days),
refreshed on every write.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from redis.asyncio.cluster import RedisCluster
from redis.asyncio.cluster import ClusterNode
from redis.exceptions import (
    RedisClusterException,
    TimeoutError as RedisTimeoutError,
    ConnectionError as RedisConnectionError,
)
from typing_extensions import override

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.session import Session
from google.adk.sessions.state import State

from app.config import get_settings
from app.store.keys import (
    key_session as _key_session,
    key_events as _key_events,
    key_app_state as _key_app_state,
    key_user_state as _key_user_state,
    key_sessions_index as _key_sessions_index,
    key_sessions_zset as _key_sessions_zset,
    key_session_meta as _key_session_meta,
    key_ui_events as _key_ui_events,
    key_session_shared as _key_session_shared,
    key_session_visibility as _key_session_visibility,
)

log = logging.getLogger(__name__)

# ── Retry decorator ────────────────────────────────────────────────────────────

_RETRYABLE_ERRORS = (RedisClusterException, RedisTimeoutError, RedisConnectionError)

_F = TypeVar("_F", bound=Callable)


def _redis_retry(fn: _F) -> _F:
    """Decorator that retries an async method on transient Redis errors.

    Retry count and initial backoff are read from settings at call-time so
    they can be overridden via env vars without restarting.  Backoff doubles
    on every attempt (exponential).

    On the last retry before raising, attempts ``self._redis.initialize()``
    to force cluster slot re-discovery — this recovers from stale topology
    cache after transient network blips or cluster failovers.
    """
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        from app.config import get_settings  # local import avoids circular dep
        settings = get_settings()
        max_attempts: int = settings.redis_retry_attempts
        delay: float = settings.redis_retry_backoff_seconds

        for attempt in range(1, max_attempts + 1):
            try:
                return await fn(self, *args, **kwargs)
            except _RETRYABLE_ERRORS as exc:
                if attempt == max_attempts:
                    # Last chance — force cluster re-init before giving up
                    try:
                        await self._redis.initialize()
                        log.info("_redis_retry: cluster re-initialized after %d failures in %s",
                                 max_attempts, fn.__name__)
                        return await fn(self, *args, **kwargs)
                    except Exception as reinit_exc:
                        log.error(
                            "Redis operation %s failed after %d attempt(s) + re-init: %s (reinit: %s)",
                            fn.__name__, max_attempts, exc, reinit_exc,
                        )
                    raise
                log.warning(
                    "Redis operation %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    fn.__name__, attempt, max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2  # exponential backoff

    return wrapper  # type: ignore[return-value]


def _tcp_keepalive_options() -> dict:
    """Return TCP keepalive socket options available on the current OS.

    Uses integer socket constants as keys (not strings) — redis-py's SSL
    socket layer cannot resolve string option names on all platforms.
    TCP_KEEPIDLE is Linux-only; macOS omits it silently.
    """
    import socket
    opts: dict = {}
    for name, value in [("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)]:
        const = getattr(socket, name, None)
        if const is not None:
            opts[const] = value   # integer key, not string
    return opts

# ── Helpers (mirrors DatabaseSessionService) ──────────────────────────────────

def _extract_state_delta(
    state: dict[str, Any],
) -> tuple[dict, dict, dict]:
    """Split a flat state dict into (app_delta, user_delta, session_delta)."""
    app_delta, user_delta, session_delta = {}, {}, {}
    if state:
        for key, val in state.items():
            if key.startswith(State.APP_PREFIX):
                app_delta[key.removeprefix(State.APP_PREFIX)] = val
            elif key.startswith(State.USER_PREFIX):
                user_delta[key.removeprefix(State.USER_PREFIX)] = val
            elif not key.startswith(State.TEMP_PREFIX):
                session_delta[key] = val
    return app_delta, user_delta, session_delta


def _merge_state(
    app_state: dict, user_state: dict, session_state: dict
) -> dict:
    """Merge app / user / session states into a single dict (ADK convention)."""
    merged = copy.deepcopy(session_state)
    for k, v in app_state.items():
        merged[State.APP_PREFIX + k] = v
    for k, v in user_state.items():
        merged[State.USER_PREFIX + k] = v
    return merged


# ── Event serialisation ────────────────────────────────────────────────────────

def _event_to_dict(event: Event) -> dict:
    """Serialise an ADK Event to a plain JSON-safe dict."""
    return event.model_dump(mode="json", exclude_none=True)


def _dict_to_event(data: dict) -> Event:
    """Deserialise an ADK Event from a plain dict."""
    return Event.model_validate(data)


# ── Service ────────────────────────────────────────────────────────────────────

class RedisSessionService(BaseSessionService):
    """ADK ``BaseSessionService`` backed by Redis Cluster.

    Designed for a Redis LB that fronts a cluster (e.g. Walmart's
    ms-df-redis).  Uses ``redis.asyncio.cluster.RedisCluster`` so that
    commands are routed to the correct cluster node transparently.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        settings = get_settings()
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.redis_session_ttl_seconds

        startup_nodes = [ClusterNode(settings.redis_host, settings.redis_port)]
        self._redis: RedisCluster = RedisCluster(
            startup_nodes=startup_nodes,
            username=settings.redis_username or None,
            password=settings.redis_password,
            decode_responses=True,
            ssl=settings.redis_ssl,
            ssl_cert_reqs=None,                              # internal Walmart cert — skip verify
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_timeout=settings.redis_socket_timeout,
            socket_keepalive=True,
            socket_keepalive_options=_tcp_keepalive_options(),
            max_connections=settings.redis_max_connections,
            health_check_interval=30,
            # NOTE: retry_on_timeout is NOT supported by RedisCluster (standalone Redis only)
        )
        log.info(
            "RedisSessionService ready — host=%s port=%s ttl=%ds "
            "socket_timeout=%ds connect_timeout=%ds max_connections=%d",
            settings.redis_host, settings.redis_port, self._ttl,
            settings.redis_socket_timeout, settings.redis_socket_connect_timeout,
            settings.redis_max_connections,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _resolve_owner_id(self, app: str, uid: str, sid: str) -> str:
        """Resolve the effective owner of a session (to support shared/public sessions).
        If the session is explicitly shared or marked public, returns the owner's ID
        so ADK retrieves and appends events to the original session history.
        """
        # 0. If session exists under the requested uid, use it directly
        #    (covers A2A_USER_* where the same contextId means the same session)
        raw_direct = await self._redis.get(_key_session(app, uid, sid))
        if raw_direct is not None:
            return uid

        # 1. Check explicit sharing
        raw = await self._redis.get(_key_session_shared(app, sid))
        if raw:
            try:
                vis = json.loads(raw)
                owner = vis.get("adk_user_id") or vis.get("owner_id")
                if owner: return owner
            except Exception:
                pass
        # 2. Check public visibility
        raw_vis = await self._redis.get(_key_session_visibility(app, sid))
        if raw_vis:
            try:
                vis = json.loads(raw_vis)
                if vis.get("public", False):
                    owner = vis.get("adk_user_id") or vis.get("owner_id")
                    if owner: return owner
            except Exception:
                pass
        # Fallback to the requested uid (either it's their own session or unshared)
        return uid

    async def _get_app_state(self, app: str) -> dict:
        raw = await self._redis.get(_key_app_state(app))
        return json.loads(raw) if raw else {}

    async def _get_user_state(self, app: str, uid: str) -> dict:
        raw = await self._redis.get(_key_user_state(app, uid))
        return json.loads(raw) if raw else {}

    async def _set_app_state(self, app: str, state: dict) -> None:
        await self._redis.set(_key_app_state(app), json.dumps(state))

    async def _set_user_state(self, app: str, uid: str, state: dict) -> None:
        k = _key_user_state(app, uid)
        await self._redis.set(k, json.dumps(state))
        await self._redis.expire(k, self._ttl)

    async def _refresh_ttl(self, app: str, uid: str, sid: str) -> None:
        """Touch TTL on all session-scoped keys."""
        await asyncio.gather(
            self._redis.expire(_key_session(app, uid, sid), self._ttl),
            self._redis.expire(_key_events(app, uid, sid), self._ttl),
            self._redis.expire(_key_ui_events(app, uid, sid), self._ttl),
            self._redis.expire(_key_sessions_index(app, uid), self._ttl),
            self._redis.expire(_key_sessions_zset(app, uid), self._ttl),
            self._redis.expire(_key_session_meta(app, uid), self._ttl),
        )

    # ── create_session ─────────────────────────────────────────────────────────

    @_redis_retry
    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        sid = (session_id.strip() if session_id and session_id.strip()
               else str(uuid.uuid4()))

        # Fetch persisted app / user state in parallel
        app_state, user_state = await asyncio.gather(
            self._get_app_state(app_name),
            self._get_user_state(app_name, user_id),
        )

        # Split incoming state into scoped deltas
        app_delta, user_delta, session_state = _extract_state_delta(state or {})

        # Apply deltas and persist writes in parallel
        app_state.update(app_delta)
        user_state.update(user_delta)

        write_tasks = []
        if app_delta:
            write_tasks.append(self._set_app_state(app_name, app_state))
        if user_delta:
            write_tasks.append(self._set_user_state(app_name, user_id, user_state))

        # Persist session metadata + index entries in parallel
        now = time.time()
        session_doc = {"state": session_state, "last_update_time": now}
        sk  = _key_session(app_name, user_id, sid)
        idx = _key_sessions_index(app_name, user_id)
        zsk = _key_sessions_zset(app_name, user_id)
        write_tasks += [
            self._redis.set(sk, json.dumps(session_doc)),
            self._redis.expire(sk, self._ttl),
            # Legacy SET index — kept so old list_sessions fallback still works
            self._redis.sadd(idx, sid),
            self._redis.expire(idx, self._ttl),
            # ZSET index scored by timestamp — enables O(1) sorted listing
            self._redis.zadd(zsk, {sid: now}),
            self._redis.expire(zsk, self._ttl),
        ]
        # Limit concurrency so bursts don't exhaust the connection pool.
        # Each gather fires up to 10 commands at a time instead of all at once.
        sem = asyncio.Semaphore(10)

        async def _guarded(coro):
            async with sem:
                return await coro

        await asyncio.gather(*(_guarded(t) for t in write_tasks))

        merged = _merge_state(app_state, user_state, session_state)
        session = Session(
            app_name=app_name,
            user_id=user_id,
            id=sid,
            state=merged,
            last_update_time=now,
        )
        log.debug("Created session %s/%s/%s", app_name, user_id, sid)
        return session

    # ── get_session ────────────────────────────────────────────────────────────

    @_redis_retry
    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        owner_id = await self._resolve_owner_id(app_name, user_id, session_id)
        sk = _key_session(app_name, owner_id, session_id)
        raw = await self._redis.get(sk)
        if raw is None:
            return None

        doc = json.loads(raw)
        session_state: dict = doc.get("state", {})
        last_update_time: float = doc.get("last_update_time", 0.0)

        # Load events and scoped states in parallel
        ek = _key_events(app_name, owner_id, session_id)
        raw_events, app_state, user_state = await asyncio.gather(
            self._redis.lrange(ek, 0, -1),
            self._get_app_state(app_name),
            self._get_user_state(app_name, owner_id),
        )
        events: list[Event] = [_dict_to_event(json.loads(r)) for r in raw_events]

        # Apply config filters (mirrors InMemorySessionService)
        if config:
            if config.after_timestamp:
                events = [e for e in events if e.timestamp >= config.after_timestamp]
            if config.num_recent_events:
                events = events[-config.num_recent_events:]
        merged = _merge_state(app_state, user_state, session_state)

        session = Session(
            app_name=app_name,
            user_id=owner_id,
            id=session_id,
            state=merged,
            last_update_time=last_update_time,
        )
        session.events = events
        return session

    # ── list_sessions ──────────────────────────────────────────────────────────

    @_redis_retry
    @override
    async def list_sessions(
        self, *, app_name: str, user_id: str
    ) -> ListSessionsResponse:
        idx = _key_sessions_index(app_name, user_id)
        session_ids: set[str] = await self._redis.smembers(idx)

        sid_list = list(session_ids)
        raws = await asyncio.gather(
            *[self._redis.get(_key_session(app_name, user_id, sid)) for sid in sid_list]
        )
        sessions: list[Session] = [
            Session(
                app_name=app_name,
                user_id=user_id,
                id=sid,
                state={},
                last_update_time=json.loads(raw).get("last_update_time", 0.0),
            )
            for sid, raw in zip(sid_list, raws)
            if raw is not None  # skip stale index entries with expired TTL
        ]
        return ListSessionsResponse(sessions=sessions)

    # ── delete_session ─────────────────────────────────────────────────────────

    @_redis_retry
    @override
    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        # Delete keys individually — Redis Cluster rejects multi-key DEL when
        # keys hash to different slots (CROSSSLOT error).  Run in parallel instead.
        await asyncio.gather(
            self._redis.delete(_key_session(app_name, user_id, session_id)),
            self._redis.delete(_key_events(app_name, user_id, session_id)),
            self._redis.delete(_key_ui_events(app_name, user_id, session_id)),
            self._redis.srem(_key_sessions_index(app_name, user_id), session_id),
            self._redis.zrem(_key_sessions_zset(app_name, user_id), session_id),
            self._redis.hdel(_key_session_meta(app_name, user_id), session_id),
        )
        log.debug("Deleted session %s/%s/%s", app_name, user_id, session_id)

    # ── append_event ───────────────────────────────────────────────────────────

    @_redis_retry
    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        """Persist event to Redis, then delegate to super() for in-memory update."""
        if event.partial:
            # Partial streaming chunks — only update in-memory, skip persistence
            return await super().append_event(session=session, event=event)

        app_name = session.app_name
        user_id = session.user_id
        session_id = session.id

        sk = _key_session(app_name, user_id, session_id)
        raw = await self._redis.get(sk)
        if raw is None:
            log.warning(
                "append_event: session %s/%s/%s not found in Redis — skipping persist",
                app_name, user_id, session_id,
            )
            return await super().append_event(session=session, event=event)

        doc = json.loads(raw)
        session_state: dict = doc.get("state", {})
        now = time.time()

        # Handle state deltas (same logic as DatabaseSessionService)
        if event.actions and event.actions.state_delta:
            app_delta, user_delta, session_delta = _extract_state_delta(
                event.actions.state_delta
            )
            if app_delta:
                app_state = await self._get_app_state(app_name)
                app_state.update(app_delta)
                await self._set_app_state(app_name, app_state)
            if user_delta:
                user_state = await self._get_user_state(app_name, user_id)
                user_state.update(user_delta)
                await self._set_user_state(app_name, user_id, user_state)
            if session_delta:
                session_state.update(session_delta)

        # Cache title from first user message so list_sessions never needs lrange
        new_title: str | None = None
        if not doc.get("title") and event.content and event.content.role == "user":
            for part in (event.content.parts or []):
                text = (getattr(part, "text", None) or "").strip()
                if text:
                    new_title = text[:60] + ("…" if len(text) > 60 else "")
                    doc["title"] = new_title
                    break

        # Update session doc
        doc["state"] = session_state
        doc["last_update_time"] = now

        zsk = _key_sessions_zset(app_name, user_id)
        persist_tasks: list = [
            self._redis.set(sk, json.dumps(doc)),
            # Keep ZSET score current so list_sessions returns newest-first
            self._redis.zadd(zsk, {session_id: now}),
        ]
        if new_title:
            # Write title to the meta hash so the sessions router avoids
            # fetching individual session docs just to read titles
            persist_tasks.append(
                self._redis.hset(_key_session_meta(app_name, user_id), session_id, new_title)
            )
        await asyncio.gather(*persist_tasks)

        # Append event
        ek = _key_events(app_name, user_id, session_id)
        await self._redis.rpush(ek, json.dumps(_event_to_dict(event)))

        # Refresh TTLs
        await self._refresh_ttl(app_name, user_id, session_id)

        # Update in-memory session object (ADK contract)
        session.last_update_time = now
        await super().append_event(session=session, event=event)
        return event
