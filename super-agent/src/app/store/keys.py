"""Redis key builders for ADK session storage.

Single source of truth for every Redis key pattern used by both the session
service and the sessions router.  Import from here — never define key patterns
inline in calling code.

Key scheme
----------
  adk:session:{app}:{uid}:{sid}       – JSON session document (state, last_update_time, title)
  adk:events:{app}:{uid}:{sid}        – Redis LIST of serialised Event blobs (LLM context)
  adk:app_state:{app}                 – JSON dict of app-scoped state
  adk:user_state:{app}:{uid}          – JSON dict of user-scoped state
  adk:sessions:{app}:{uid}            – Redis SET of session IDs (legacy — kept for compat)
  adk:sessions_z:{app}:{uid}          – Redis ZSET scored by last_update_time (fast listing)
  adk:session_meta:{app}:{uid}        – Redis HASH  {session_id → title} (fast title lookup)
  agent:ui_events:{app}:{uid}:{sid}   – Redis LIST of UI events for chat replay
  agent:ui_stream:{app}:{uid}:{sid}   – Redis STREAM for live SSE delivery of injected events
  agent:llm_pending:{app}:{uid}:{sid} – Redis STREAM of injected events not yet primed into LLM
  agent:idem_inject:{app}:{uid}:{sid}:{key} – SET-NX dedup marker for inject_message
  agent:mcp_servers                   – JSON array of MCP server config objects (persistent)
"""

# ── Global config keys ─────────────────────────────────────────────────────────

MCP_SERVERS_KEY = "agent:mcp_servers"
"""Redis key that stores the list of MCP server configs as a JSON array.

Set by operators (no TTL — persistent config key).  Format::

    [
      {
        "name": "wcnp-health-agent",
        "description": "...",
        "url": "https://your-mcp-server/mcp/",
        "transport": "streamable_http",
        "enabled": true,
        "headers": {}
      }
    ]
"""


A2A_AGENTS_KEY = "agent:a2a_agents"
"""Redis key that stores the list of remote A2A subagent configs as a JSON array.

Actual key used at runtime is derived from env + group:
  ``super_agent:config:a2a_agents:<agent_env>:<agent_group>:config``
e.g. ``super_agent:config:a2a_agents:stage:sre:config``

Set by operators (no TTL — persistent config key).  Format::

    [
      {
        "name": "sre-agent",
        "url": "https://sre-agent.dev.walmart.com",
        "enabled": true,
        "headers": {},
        "description": ""
      }
    ]

``description`` is optional — if empty, super-agent fetches it automatically
from ``{url}/.well-known/agent.json`` (A2A 0.3 Agent Card) at startup.
Missing / unreachable agents are logged as warnings; startup continues.
"""


def key_session(app: str, uid: str, sid: str) -> str:
    """Return the key for a session document.

    Args:
        app: ADK application name (e.g. ``"health_agent"``).
        uid: User identifier.
        sid: Session identifier.

    Returns:
        Redis key string.
    """
    return f"adk:session:{app}:{uid}:{sid}"


def key_events(app: str, uid: str, sid: str) -> str:
    """Return the key for a session's event list.

    Args:
        app: ADK application name.
        uid: User identifier.
        sid: Session identifier.

    Returns:
        Redis key string.
    """
    return f"adk:events:{app}:{uid}:{sid}"


def key_app_state(app: str) -> str:
    """Return the key for app-scoped state.

    Args:
        app: ADK application name.

    Returns:
        Redis key string.
    """
    return f"adk:app_state:{app}"


def key_user_state(app: str, uid: str) -> str:
    """Return the key for user-scoped state.

    Args:
        app: ADK application name.
        uid: User identifier.

    Returns:
        Redis key string.
    """
    return f"adk:user_state:{app}:{uid}"


def key_sessions_index(app: str, uid: str) -> str:
    """Return the key for the set that indexes a user's sessions.

    Args:
        app: ADK application name.
        uid: User identifier.

    Returns:
        Redis key string.
    """
    return f"adk:sessions:{app}:{uid}"


def key_sessions_zset(app: str, uid: str) -> str:
    """Return the ZSET key that indexes a user's sessions sorted by recency.

    Members are session IDs; scores are Unix timestamps (last_update_time).
    Use ZADD to write and ZREVRANGE to read newest-first — O(log N) writes,
    O(log N + M) reads for M results regardless of total session count.
    """
    return f"adk:sessions_z:{app}:{uid}"


def key_session_meta(app: str, uid: str) -> str:
    """Return the HASH key storing lightweight session metadata.

    Field → Value mapping: ``{session_id: title}``.
    Fetching titles for N sessions is a single HMGET regardless of N.
    """
    return f"adk:session_meta:{app}:{uid}"


def key_sessions_public(app: str) -> str:
    """Return the ZSET key for publicly shared sessions (participants=all).

    Members are ``{owner_id}:{session_id}`` compound strings so the event list
    key can be reconstructed without a separate lookup.
    Scored by last_update_time like the per-user ZSET.
    """
    return f"adk:sessions_public:{app}"


def key_session_visibility(app: str, sid: str) -> str:
    """Return the key for session visibility + custom tags.

    Stores JSON: ``{"public": true, "tags": ["Alert", "Incident-123"]}``
    Setting public=true also writes to key_sessions_public.
    """
    return f"agent:session_visibility:{app}:{sid}"


def key_session_shared(app: str, sid: str) -> str:
    """Return the key for session sharing metadata.

    Stores JSON: ``{"owner_id": "...", "participants": ["all"|list], "permission": "read|write"}``
    """
    return f"agent:session_shared:{app}:{sid}"


def key_ui_events(app: str, uid: str, sid: str) -> str:
    """Return the key for the UI event log used for conversation replay.

    Stores every SSE event emitted during a session (user messages, tool
    progress, render calls, final answers) so the UI can replay the exact
    visual state on page refresh — no re-derivation needed.

    Args:
        app: ADK application name.
        uid: User identifier.
        sid: Session identifier.

    Returns:
        Redis key string.
    """
    return f"agent:ui_events:{app}:{uid}:{sid}"


def key_ui_stream(app: str, uid: str, sid: str) -> str:
    """Return the Redis Stream key for live SSE delivery of injected events.

    Producers writing to ``inject_message`` XADD here; the
    ``GET /sessions/{id}/events/subscribe`` SSE endpoint XREAD-blocks on
    this key to push new events to the UI in real time without polling.

    Distinct from ``key_ui_events`` (a LIST used for one-shot replay on
    session-open) — this is a STREAM used for live tailing.
    """
    return f"agent:ui_stream:{app}:{uid}:{sid}"


def key_llm_pending(app: str, uid: str, sid: str) -> str:
    """Return the Redis Stream key holding injected events not yet primed
    into the LLM context.

    Drained by the ``inject_pending_observations`` ``before_agent_callback``
    on the next user turn: events newer than ``session.state["last_lifecycle_ts"]``
    are wrapped in a ``[SYSTEM CONTEXT]`` block and inserted into the
    in-memory ``session.events`` list (NOT persisted to ``adk:events``).

    Kept independent of ``ui_stream`` so consumers can fan out at different
    rates (UI may have multiple SSE viewers; LLM drains on each turn only).
    """
    return f"agent:llm_pending:{app}:{uid}:{sid}"


def key_idem_inject(app: str, uid: str, sid: str, idem_key: str) -> str:
    """Return the dedup marker key for ``POST /sessions/{id}/inject_message``.

    Set with ``SET ... NX EX <ttl>`` on first arrival; duplicate retries
    carrying the same ``Idempotency-Key`` header see the existing key and
    are treated as no-ops (the endpoint returns 200 with
    ``deduplicated=true``).

    Key includes ``{uid}:{sid}`` so keys from different producers writing to
    different sessions cannot collide even if they accidentally reuse the
    same idempotency string.  ``{idem_key}`` is client-supplied and must be
    stable across retries of the same logical injection (e.g.
    ``lc:INC123:verdict_change:false_positive:3``).
    """
    return f"agent:idem_inject:{app}:{uid}:{sid}:{idem_key}"
