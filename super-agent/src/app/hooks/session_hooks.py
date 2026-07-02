"""

Session-related ADK hook callbacks.

before_agent_callback: trim_session_history
--------------------------------------------
Controls how many previous conversation turns the LLM receives as context
on each invocation.

after_tool_callback: after_tool_handler
----------------------------------------
Generic post-processing for ALL MCP tool responses.  Domain-agnostic —
the Super Agent does not inspect or interpret any MCP server's response
schema.  Health-specific workflows (anomaly detection, RCA nudges) are
owned by health-mcp's agent-guide, prompts, and resources.

Responsibilities:
  1. Persist scalar tool arguments to session state (for follow-up queries).
  2. Strip large ``table_data.rows`` before the LLM sees the response
     (saves context tokens); runner.py restores full rows for the UI.

Why this is needed
------------------
Health-check responses are large (tool call data + markdown tables, often
50-200 K tokens each).  The ADK runner loads the *full* Redis session history
into the LLM context window on every call.  After 2-3 queries the accumulated
history exceeds the 200 K-token limit, causing a ContextWindowExceededError.

How it works
------------
``trim_session_history`` is registered as ``before_agent_callback`` on the
root agent.  ADK calls it *after* loading the session from Redis but *before*
sending context to the LLM, so:

  - The in-memory ``session.events`` list is trimmed to the last
    ``LLM_HISTORY_TURNS`` complete turns.
  - Redis is never touched — the full history is preserved for the UI sidebar.
  - Return ``None`` to let ADK continue normally.

Configuration
-------------
Set ``LLM_HISTORY_TURNS`` in your ``.env``:

  LLM_HISTORY_TURNS=0   # (default) fresh context per query — no overflow
  LLM_HISTORY_TURNS=1   # LLM sees the previous turn (enables follow-ups)
  LLM_HISTORY_TURNS=N   # LLM sees the last N turns
"""

import json
import logging
import time as _time
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.events.event import Event
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types as genai_types

from app.config import get_settings
from app.constants import APP_NAME as _APP_NAME
from app.store.keys import key_llm_pending as _key_llm_pending

log = logging.getLogger(__name__)

# Read once at import time; restart the server to pick up changes.
_MAX_HISTORY_TURNS: int = get_settings().llm_history_turns

# ── Table row cache ────────────────────────────────────────────────────────────
# When a tool response contains table_data.rows above this threshold, we strip
# the rows before the LLM sees the response (saving context tokens) and stash
# the full rows here, keyed by ``<session_id>:<call_id>``.  runner.py reads this
# cache when emitting the ``render_table_data`` SSE event so the UI gets all rows.
#
# Keys are session-scoped to prevent cross-user data leakage when multiple
# users hit the same process concurrently.
#
# Lifecycle: written here in after_tool_callback, consumed + deleted in runner.py.
# Thread-safety: asyncio is single-threaded; no lock needed.
#
# Each entry stores {"table_data": ..., "_ts": <monotonic timestamp>} so stale
# entries from dropped SSE connections can be evicted automatically.
TABLE_ROW_CACHE: dict[str, dict] = {}   # cache_key → {table_data, _ts}
_TABLE_ROW_STRIP_THRESHOLD: int = 50    # strip if more than this many rows
_CACHE_TTL_SECONDS: int = 300           # evict entries older than 5 minutes
_CACHE_MAX_ENTRIES: int = 200           # hard cap to bound memory usage

# Chart data cache — chart_data / multi_chart_data float arrays are stripped
# from the LLM response and stored here.  The LLM receives a compact summary
# (title, metric names, point count) instead of hundreds of floats.
# Unlike table rows, chart arrays are NOT restored by runner.py in the A2A
# production path — the frontend intercepts render_chart/render_multi_chart
# function_calls and converts them directly.  This cache exists purely to
# reduce LLM context tokens.
CHART_DATA_CACHE: dict[str, dict] = {}  # cache_key → {chart_data?, multi_chart_data?, _ts}


def table_row_cache_key(session_id: str, call_id: str) -> str:
    """Build a session-scoped cache key for TABLE_ROW_CACHE.

    Both session_hooks.py (writer) and runner.py (reader) must use this
    function to construct cache keys, ensuring they always agree on format.

    Args:
        session_id: ADK session identifier (unique per user conversation).
        call_id:    ADK function_call_id or tool name fallback.

    Returns:
        A composite key ``"<session_id>:<call_id>"``.
    """
    return f"{session_id}:{call_id}"


def _evict_stale_cache_entries() -> None:
    """Remove TABLE_ROW_CACHE entries older than ``_CACHE_TTL_SECONDS``.

    Called on every write to keep the cache bounded.  Runs in O(n) but n
    is bounded by ``_CACHE_MAX_ENTRIES`` (at most 200 entries).
    """
    now = _time.monotonic()
    stale_keys = [
        k for k, v in TABLE_ROW_CACHE.items()
        if now - v.get("_ts", 0) > _CACHE_TTL_SECONDS
    ]
    for k in stale_keys:
        TABLE_ROW_CACHE.pop(k, None)
    if stale_keys:
        log.debug("table_row_cache: evicted %d stale entries", len(stale_keys))

log.info("session_hooks: LLM_HISTORY_TURNS=%d", _MAX_HISTORY_TURNS)


def trim_session_history(
    callback_context: CallbackContext,
) -> Optional[genai_types.Content]:
    """ADK before_agent_callback — trim in-memory session events.

    Keeps only the last ``_MAX_HISTORY_TURNS`` complete conversation turns
    visible to the LLM.  A "turn" begins at each user-role event.

    Full history is preserved in Redis so the UI sidebar is never affected.

    Args:
        callback_context: Provided by ADK before each agent invocation.

    Returns:
        ``None`` — always continues normal ADK execution.
    """
    try:
        session = callback_context._invocation_context.session
        events  = session.events

        # Guarantee active_context exists before inject_session_state runs.
        # ADK 1.28 exposes callback_context.state as the public, delta-aware
        # State object — use it instead of the private session.state directly.
        if "active_context" not in callback_context.state:
            callback_context.state["active_context"] = ""

        if not events:
            return None

        if _MAX_HISTORY_TURNS == 0:
            # Fresh context — LLM only receives the current query.
            # ADK 1.3.0 appends the new user message to session.events *before*
            # before_agent_callback fires, so we must preserve the last event
            # (the current user turn) and only discard prior history.
            if len(events) > 1:
                removed = len(events) - 1
                del events[:-1]
                log.debug("trim_session_history: cleared %d stale events (fresh context)", removed)
            return None

        # Locate the start index of each turn (user message = turn boundary).
        turn_starts = [
            i for i, e in enumerate(events)
            if e.content and getattr(e.content, "role", None) == "user"
        ]

        if len(turn_starts) > _MAX_HISTORY_TURNS:
            keep_from = turn_starts[-_MAX_HISTORY_TURNS]
            removed   = keep_from
            del events[:keep_from]
            log.debug(
                "trim_session_history: dropped %d events, keeping last %d turn(s) (%d events remain)",
                removed, _MAX_HISTORY_TURNS, len(events),
            )

    except Exception as exc:
        # A trimming failure must never block a user query.
        log.warning(
            "trim_session_history failed (non-fatal): %s — %s",
            type(exc).__name__, exc,
        )

    return None


# ── inject_pending_observations ────────────────────────────────────────────────
# Drains the per-session ``agent:llm_pending`` Redis Stream on every turn and
# wraps any new injected content in an ephemeral [SYSTEM CONTEXT] block that
# is inserted into the in-memory ``session.events`` list ONLY for this turn.
#
# Crucial invariants:
#   - This block is NEVER persisted to ``adk:events``.  We mutate the in-memory
#     list directly; ADK's runner does not call append_event for what we add.
#   - State key ``last_lifecycle_ts`` is the high-water-mark Stream ID for this
#     session, so we never replay the same injection twice.
#   - The block is inserted immediately BEFORE the most recent user-role event
#     (the current turn) so the LLM reads it as fresh out-of-band context just
#     before the user's question.
#   - The wrapper text identifies the content as coming from automated
#     subsystems; producers (openclaw, alertmanager, ...) put any structure
#     they want inside the ``content`` markdown.

# Stream-Stream IDs are sortable lexically when zero-padded; "0-0" is "older
# than anything Redis would emit", so it's a safe initial high-water mark.
_LIFECYCLE_HWM_STATE_KEY = "last_lifecycle_ts"

# Staging key for the HWM proposed by the before-agent drain pass.  We only
# promote this into ``_LIFECYCLE_HWM_STATE_KEY`` in the after-agent callback,
# AFTER the LLM turn completes successfully.  If the LLM call throws (network
# error, rate limit, context overflow, etc.), ADK skips after-agent callbacks
# and the staged HWM is discarded — the next turn re-drains the same entries
# so the user still sees the observations in their LLM context.
#
# Trade-off: on a turn where the LLM succeeded but then ADK crashed during
# post-processing, observations could be LLM-seen twice on the retry.  In
# practice this is rare and harmless (the LLM just re-reads the same
# [SYSTEM CONTEXT] block) — far better than silently dropping observations.
_LIFECYCLE_HWM_PENDING_KEY = "_lifecycle_hwm_pending"

_LIFECYCLE_INJECT_MAX = 50  # safety cap per turn — avoid 1MB injections


async def inject_pending_observations(
    callback_context: CallbackContext,
) -> Optional[genai_types.Content]:
    """ADK before_agent_callback — pull queued out-of-band content into the LLM context.

    Reads the per-session ``agent:llm_pending`` Redis Stream for entries
    newer than the session's stored high-water-mark, builds a single
    ``[SYSTEM CONTEXT]`` user-role Event, and inserts it into the in-memory
    ``session.events`` list immediately before the latest user turn.

    The proposed new high-water-mark is STAGED on ``session.state`` under a
    private key (``_lifecycle_hwm_pending``).  It is only promoted to the
    canonical ``last_lifecycle_ts`` key by ``commit_pending_observations``
    (the ``after_agent_callback``) — i.e. AFTER the LLM turn completes
    successfully.  This prevents the "LLM failed → observations silently
    dropped" edge case noted in the original design.

    Returns ``None`` to let ADK continue normal execution. Failures are
    logged and never block the user's turn.
    """
    try:
        invocation = callback_context._invocation_context
        session    = invocation.session
        sid        = session.id
        uid        = session.user_id
        app_name   = session.app_name or _APP_NAME

        session_service = getattr(invocation, "session_service", None)
        redis           = getattr(session_service, "_redis", None) if session_service else None
        if redis is None:
            return None  # not running under RedisSessionService — nothing to do

        stream_key = _key_llm_pending(app_name, uid, sid)
        last_id    = callback_context.state.get(_LIFECYCLE_HWM_STATE_KEY) or "0-0"

        try:
            entries = await redis.xrange(stream_key, min=f"({last_id}", max="+", count=_LIFECYCLE_INJECT_MAX)
        except Exception as exc:
            log.debug("inject_pending_observations: xrange failed (%s) — skipping", exc)
            return None

        if not entries:
            # Clear any stale pending marker from a prior aborted turn.
            if _LIFECYCLE_HWM_PENDING_KEY in callback_context.state:
                callback_context.state[_LIFECYCLE_HWM_PENDING_KEY] = ""
            return None

        observations: list[str] = []
        new_hwm = last_id
        for entry_id, fields in entries:
            new_hwm = entry_id if isinstance(entry_id, str) else entry_id.decode()
            raw = fields.get(b"data") if isinstance(fields, dict) else None
            if raw is None:
                raw = fields.get("data") if isinstance(fields, dict) else None
            if raw is None:
                continue
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode()
            try:
                parsed = json.loads(raw)
                content = parsed.get("content")
                if content:
                    observations.append(content)
            except Exception:
                # Tolerate non-JSON entries — treat as raw content
                observations.append(str(raw))

        if not observations:
            # Entries existed but all payloads were unreadable — STAGE the HWM
            # so commit_pending_observations promotes it iff the turn succeeds
            # (same semantics as the productive path: avoid dropping on LLM
            # failure, but don't re-read the same unparseable entries forever).
            callback_context.state[_LIFECYCLE_HWM_PENDING_KEY] = new_hwm
            return None

        # Build the synthetic system-context block.  The framing wording is
        # generic — producers must self-identify inside their content (e.g.
        # "## openclaw monitoring update for INC...").
        block = (
            "[SYSTEM CONTEXT — out-of-band updates from automated subsystems "
            "since your last reply. These were NOT typed by the user. Acknowledge "
            "them only if directly relevant to the user's next question.]\n\n"
            + "\n\n---\n\n".join(observations)
        )

        # Insert as a synthetic user-role Event right before the most recent
        # user message (the current turn).  ADK will trim/order normally.
        synthetic = Event(
            author="system",
            invocation_id=getattr(invocation, "invocation_id", "lifecycle-injection") or "lifecycle-injection",
            content=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=block)],
            ),
        )

        events = session.events
        # Find the last user-role event index (the current turn ADK just appended).
        insert_at = len(events)
        for i in range(len(events) - 1, -1, -1):
            ev = events[i]
            if ev.content and getattr(ev.content, "role", None) == "user":
                insert_at = i
                break
        events.insert(insert_at, synthetic)

        # STAGE the HWM — do NOT commit to _LIFECYCLE_HWM_STATE_KEY here.
        # ``commit_pending_observations`` promotes this on successful turn.
        callback_context.state[_LIFECYCLE_HWM_PENDING_KEY] = new_hwm
        log.info(
            "inject_pending_observations: staged %d observation(s) into session=%s (pending_hwm→%s)",
            len(observations), sid, new_hwm,
        )

    except Exception as exc:
        log.warning(
            "inject_pending_observations failed (non-fatal): %s — %s",
            type(exc).__name__, exc,
        )

    return None


async def commit_pending_observations(
    callback_context: CallbackContext,
) -> Optional[genai_types.Content]:
    """ADK after_agent_callback — promote the staged lifecycle HWM on success.

    This runs ONLY when the agent turn has completed normally (ADK skips
    after-agent callbacks when the model call raises).  We promote the
    staged ``_lifecycle_hwm_pending`` to the canonical ``last_lifecycle_ts``
    so the next turn skips already-consumed observations.

    If the turn failed (after-agent never fires), the staged marker stays
    behind and the next turn's drain pass reads from the old HWM → the LLM
    sees the observations again.  That's the whole point of the split.

    Cheap to run (two state reads + one state write); always returns None.
    """
    try:
        state = callback_context.state
        pending = state.get(_LIFECYCLE_HWM_PENDING_KEY)
        if not pending:
            return None
        # Only promote forward — never regress the HWM (defensive against
        # out-of-order callback execution in complex agent graphs).
        current = state.get(_LIFECYCLE_HWM_STATE_KEY) or "0-0"
        if _stream_id_lt(current, pending):
            state[_LIFECYCLE_HWM_STATE_KEY] = pending
            log.info(
                "commit_pending_observations: hwm %s → %s",
                current, pending,
            )
        # Always clear the staging key so the next turn starts clean.
        state[_LIFECYCLE_HWM_PENDING_KEY] = ""
    except Exception as exc:
        log.warning(
            "commit_pending_observations failed (non-fatal): %s — %s",
            type(exc).__name__, exc,
        )
    return None


def _stream_id_lt(a: str, b: str) -> bool:
    """Return True iff Redis Stream ID *a* is strictly older than *b*.

    Stream IDs are ``<millis>-<seq>`` — both are non-negative integers.
    Lexical comparison happens to work because the millis field is
    monotonically increasing and both IDs share the same format, but we
    do the numeric compare explicitly so a malformed input can't cause a
    silent regression.
    """
    try:
        am, asq = a.split("-", 1)
        bm, bsq = b.split("-", 1)
        return (int(am), int(asq)) < (int(bm), int(bsq))
    except Exception:
        # If we can't parse, refuse to promote — safer than a regression.
        return False


# Tools whose args carry no domain identity — skip state saving entirely.
# get_mcp_prompt uses generic keys like "name" and "arguments" (raw JSON string)
# that would pollute session state and potentially shadow real domain values.
_STATE_SAVE_SKIP_TOOLS = {"get_mcp_prompt"}

# Arg keys that are internal/technical — persisted to state for ADK variable
# resolution but excluded from the human-readable active_context summary.
_SUMMARY_EXCLUDE = {
    "analysis_start_epoch",
    "analysis_end_epoch",
    "checks",
    "cluster_ids",
    "direction",          # wcnp-istio-latency direction param
}


def _save_args_to_state(args: dict[str, Any], tool_context: ToolContext, tool_name: str) -> None:
    """Persist all scalar tool arguments into session state and update active_context.

    Every scalar arg (str/int/float/bool) is written to ``tool_context.state``
    under its own key.  ADK injects ``{variable}`` placeholders from this
    state into the agent instruction before every LLM call, so follow-up
    queries like "check the same app" or "now look at 5xx errors" resolve
    correctly — regardless of provider:

      WCNP    → app, namespace, cluster_id, ...
      Cosmos  → subscription_id, resource_group, database_name, ...
      OneOps  → org, platform, assembly, ...
      Cassandra/MeghaCache → assembly, platform, ...

    Internal orchestration tools (e.g. get_mcp_prompt) are skipped entirely —
    their args carry no domain identity and would pollute session state.
    """
    if tool_name in _STATE_SAVE_SKIP_TOOLS:
        return

    summary_parts: list[str] = []
    for key, value in args.items():
        if not isinstance(value, (str, int, float, bool)):
            continue
        if value == "":
            continue
        tool_context.state[key] = value
        if key not in _SUMMARY_EXCLUDE:
            summary_parts.append(f"{key}={value}")

    if summary_parts:
        tool_context.state["active_context"] = (
            f"Last tool: {tool_name} | {', '.join(summary_parts)}"
        )


def _strip_large_table_rows(
    result: dict,
    response_text: str,
    cache_key: str | None,
    tool_name: str,
) -> tuple[dict, str, bool]:
    """Strip large table_data.rows from a parsed tool response.

    If the response carries ``table_data`` with more than
    ``_TABLE_ROW_STRIP_THRESHOLD`` rows, the full data is cached in
    ``TABLE_ROW_CACHE`` (keyed by session-scoped ``cache_key``) and the
    rows are replaced with an empty list.  runner.py restores the full
    rows when emitting the ``render_table_data`` SSE event.

    Args:
        result:        Parsed tool response dict.
        response_text: Serialized JSON string of the response.
        cache_key:     Session-scoped key from ``table_row_cache_key()``.
                       If ``None`` or empty, caching is skipped.
        tool_name:     Tool name for logging.

    Returns:
        (result, response_text, stripped) — updated result dict, serialized
        text, and a boolean indicating whether rows were stripped.
    """
    table_data = result.get("table_data")
    if not (
        cache_key
        and isinstance(table_data, dict)
        and len(table_data.get("rows") or []) > _TABLE_ROW_STRIP_THRESHOLD
    ):
        return result, response_text, False

    # Evict stale entries + enforce hard cap before inserting
    _evict_stale_cache_entries()
    if len(TABLE_ROW_CACHE) >= _CACHE_MAX_ENTRIES:
        # Drop oldest entry to make room
        oldest_key = min(TABLE_ROW_CACHE, key=lambda k: TABLE_ROW_CACHE[k].get("_ts", 0))
        TABLE_ROW_CACHE.pop(oldest_key, None)
        log.warning("table_row_cache: hit max entries (%d), evicted oldest", _CACHE_MAX_ENTRIES)

    TABLE_ROW_CACHE[cache_key] = {
        "table_data": table_data,
        "_ts": _time.monotonic(),
    }
    stripped_table = {k: v for k, v in table_data.items() if k != "rows"}
    stripped_table["rows"] = []                    # LLM sees empty rows
    stripped_table["_rows_stripped"] = True        # marker for runner
    result = {**result, "table_data": stripped_table}
    response_text = json.dumps(result)
    log.info(
        "after_tool_callback: stripped %d rows from table_data for %s (cache_key=%s)",
        len(table_data["rows"]), tool_name, cache_key,
    )
    return result, response_text, True


def _strip_chart_data(
    result: dict,
    response_text: str,
    cache_key: str | None,
    tool_name: str,
) -> tuple[dict, str, bool]:
    """Strip chart_data / multi_chart_data float arrays before the LLM sees them.

    The LLM receives a compact summary instead of hundreds of floats:
      chart_data       → {"_chart_rendered": True, "title": ..., "series_count": N, "data_points": N}
      multi_chart_data → {"_chart_rendered": True, "title": ..., "chart_count": N, "metrics": [...]}

    The full arrays are cached in CHART_DATA_CACHE for potential restore.
    Note: in the A2A production path the frontend intercepts render_* function_calls
    directly, so the cache is primarily for token reduction rather than UI restore.
    """
    cd_raw  = result.get("chart_data")
    mcd_raw = result.get("multi_chart_data")
    # Guard: skip if already slim (double-strip protection) or nothing to strip
    has_chart      = isinstance(cd_raw,  dict) and not cd_raw.get("_chart_rendered")
    has_multichart = isinstance(mcd_raw, dict) and not mcd_raw.get("_chart_rendered")
    if not (cache_key and (has_chart or has_multichart)):
        return result, response_text, False

    cache_entry: dict = {"_ts": _time.monotonic()}
    modified = dict(result)

    if has_chart:
        cd     = cd_raw  # type: ignore[assignment]
        labels = cd.get("labels", []) or []
        series = cd.get("datasets", cd.get("series", [])) or []
        if labels or series:
            cache_entry["chart_data"] = cd
            modified["chart_data"] = {
                "_chart_rendered": True,
                "title":           cd.get("title", ""),
                "chart_type":      cd.get("chart_type", "line"),
                "series_count":    len(series),
                "data_points":     len(labels),
            }
            log.info(
                "after_tool_callback: stripped chart_data for %s — %d series, %d pts",
                tool_name, len(series), len(labels),
            )

    if has_multichart:
        mcd    = mcd_raw  # type: ignore[assignment]
        charts = mcd.get("charts", []) or []
        metrics = [c.get("metric", "") for c in charts if c.get("metric")]
        pts     = len(charts[0].get("labels", [])) if charts else 0
        if charts:
            cache_entry["multi_chart_data"] = mcd
            modified["multi_chart_data"] = {
                "_chart_rendered": True,
                "title":           mcd.get("title", ""),
                "chart_count":     len(charts),
                "metrics":         metrics,
                "data_points":     pts,
            }
            log.info(
                "after_tool_callback: stripped multi_chart_data for %s — %d chart(s) [%s]",
                tool_name, len(charts), ", ".join(metrics),
            )

    if len(cache_entry) == 1:  # only "_ts" — nothing was actually stripped
        return result, response_text, False

    # Evict stale entries then enforce hard cap before writing
    _now = _time.monotonic()
    stale = [k for k, v in CHART_DATA_CACHE.items() if _now - v.get("_ts", 0) > _CACHE_TTL_SECONDS]
    for k in stale:
        CHART_DATA_CACHE.pop(k, None)
    while len(CHART_DATA_CACHE) >= _CACHE_MAX_ENTRIES:
        oldest = min(CHART_DATA_CACHE, key=lambda k: CHART_DATA_CACHE[k].get("_ts", 0))
        CHART_DATA_CACHE.pop(oldest, None)

    CHART_DATA_CACHE[cache_key] = cache_entry
    response_text = json.dumps(modified)
    return modified, response_text, True


def after_tool_handler(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict]:
    """ADK after_tool_callback — generic post-processing for all MCP tools.

    This callback is domain-agnostic.  It does NOT inspect or interpret any
    MCP server's response schema (anomalies, health checks, incidents, etc.).
    Domain-specific workflows are the responsibility of each MCP server's
    agent-guide, prompts, and resources.

    Responsibilities:
      1. Persist scalar tool arguments into session state so follow-up
         queries resolve correctly (e.g. "check the same app").
      2. Strip large ``table_data.rows`` from any tool response to save
         context tokens.  The full rows are cached for runner.py to restore
         when emitting the ``render_table_data`` SSE event.
      3. Strip ``chart_data`` / ``multi_chart_data`` float arrays — LLM
         receives a compact summary instead of hundreds of floats.

    Returns:
        Modified tool response dict if anything was stripped, else None (no-op).
    """
    # Always persist scalar args for every tool — fixes "Context variable not found" errors.
    # Wrapped in its own try/except so a crash here never blocks the callback.
    try:
        _save_args_to_state(args or {}, tool_context, tool.name)
    except Exception as exc:
        log.debug("after_tool_handler: _save_args_to_state non-fatal: %s", exc)

    try:
        response_text = ""
        if isinstance(tool_response, dict):
            content = tool_response.get("content", [])
            if isinstance(content, list) and content:
                response_text = content[0].get("text", "") if isinstance(content[0], dict) else ""
        if not response_text:
            return None

        result = json.loads(response_text)
        if not isinstance(result, dict):
            return None

        # ── Strip large table_data.rows before LLM sees them ──────────────────
        call_id = getattr(tool_context, "function_call_id", None)
        # Build session-scoped cache key to prevent cross-user data leakage.
        _cache_key: str | None = None
        if call_id:
            try:
                sid = tool_context._invocation_context.session.id
                _cache_key = table_row_cache_key(sid, call_id)
            except Exception:
                # Fallback: use call_id alone if session is unavailable.
                # Still safe — ADK UUIDs are unique within the process.
                _cache_key = call_id
        result, response_text, stripped_table = _strip_large_table_rows(
            result, response_text, _cache_key, tool.name,
        )

        result, response_text, stripped_chart = _strip_chart_data(
            result, response_text, _cache_key, tool.name,
        )

        if stripped_table or stripped_chart:
            enriched_response = dict(tool_response)
            if isinstance(enriched_response.get("content"), list) and enriched_response["content"]:
                enriched_response["content"] = [
                    {**enriched_response["content"][0], "text": response_text}
                    if isinstance(enriched_response["content"][0], dict)
                    else enriched_response["content"][0]
                ]
            return enriched_response

        return None

    except Exception as exc:
        log.debug("after_tool_handler non-fatal: %s", exc)
        return None  # never block normal execution


# ── on_tool_error_callback ────────────────────────────────────────────────────
# Graceful degradation when an MCP tool call fails (server down, timeout, etc.).
# Instead of crashing the entire turn, return a structured error dict so the LLM
# can inform the user and continue the conversation.

# Maximum length of the error message included in the response — very long
# tracebacks would waste context tokens and confuse the LLM.
_ERROR_MSG_MAX_LEN: int = 500

# Map well-known exception families to user-friendly short labels.
_ERROR_LABELS: dict[type, str] = {
    ConnectionError: "connection_error",
    TimeoutError: "timeout",
    OSError: "network_error",
}


def _classify_error(error: Exception) -> str:
    """Return a short, stable label for the error type.

    Checks isinstance against ``_ERROR_LABELS`` first (catches subclasses like
    ConnectionRefusedError, ConnectionResetError).  Falls back to the class name.
    """
    for exc_type, label in _ERROR_LABELS.items():
        if isinstance(error, exc_type):
            return label
    return type(error).__name__


def on_tool_error_handler(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    error: Exception,
) -> Optional[dict]:
    """ADK on_tool_error_callback — graceful degradation for tool failures.

    When an MCP tool raises (server down, timeout, malformed response, etc.),
    ADK calls this *before* propagating the exception.  By returning a ``dict``
    we short-circuit the exception and give the LLM a structured error response
    so it can inform the user and suggest alternatives.

    Returning ``None`` would re-raise the original exception and crash the turn.

    Edge cases handled:
      - ``tool.name`` is None or empty → falls back to ``"unknown_tool"``.
      - ``args`` is None → normalised to ``{}``.
      - Error message is extremely long → truncated to ``_ERROR_MSG_MAX_LEN``.
      - Error has no message (empty str) → uses class name as message.
      - Unexpected failure *inside this handler* → logs + returns minimal fallback
        dict so the turn still doesn't crash.

    Args:
        tool:         The BaseTool that failed.
        args:         The arguments dict passed to the tool call.
        tool_context: ADK ToolContext for the current invocation.
        error:        The exception raised by the tool.

    Returns:
        A dict that ADK uses as the tool's ``function_response`` so the LLM
        can explain the failure to the user.
    """
    try:
        tool_name = getattr(tool, "name", None) or "unknown_tool"
        safe_args = args if isinstance(args, dict) else {}
        error_type = _classify_error(error)

        # Build a bounded error message — avoid injecting huge tracebacks
        raw_msg = str(error).strip()
        if not raw_msg:
            raw_msg = type(error).__name__
        error_msg = (raw_msg[:_ERROR_MSG_MAX_LEN] + "…") if len(raw_msg) > _ERROR_MSG_MAX_LEN else raw_msg

        log.warning(
            "on_tool_error_handler: tool=%s error_type=%s error=%s args=%s",
            tool_name, error_type, error_msg, safe_args,
        )

        return {
            "status": "error",
            "error_type": error_type,
            "tool_name": tool_name,
            "message": (
                f"The tool '{tool_name}' is temporarily unavailable ({error_type}: {error_msg}). "
                f"Please inform the user that this data source could not be reached right now. "
                f"You may retry the same tool, try an alternative approach, or ask the user to try again later."
            ),
        }

    except Exception as fallback_exc:
        # This handler must NEVER itself crash — that would propagate the
        # original tool error and kill the turn.
        log.error(
            "on_tool_error_handler: internal failure (returning minimal fallback): %s — %s",
            type(fallback_exc).__name__, fallback_exc,
        )
        return {
            "status": "error",
            "error_type": "handler_internal_error",
            "tool_name": "unknown",
            "message": "A tool call failed and the error handler encountered an internal issue. Please try again.",
        }
