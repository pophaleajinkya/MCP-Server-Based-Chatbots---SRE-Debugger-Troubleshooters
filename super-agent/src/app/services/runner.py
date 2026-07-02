"""ADK runner helpers — shared by /query and /a2a routers.

Wraps ``Runner.run_async`` and extracts the final text response so
routers stay thin and don't duplicate event-loop logic.

Context-window management is handled by the agent's ``before_agent_callback``
(see ``agent/__init__.py``), which trims in-memory session events before each
LLM call.  Full history is preserved in Redis for the UI sidebar.
"""

import asyncio
import json
import logging
import math
import re
import time as _time
from typing import Any, AsyncGenerator

from google.adk.runners import Runner
from google.genai import types as genai_types

from app.constants import APP_NAME as _APP_NAME, LLM_HTTP_ERROR_CODES, SKILL_TOOLS as _SKILL_TOOLS
from app.exceptions import AgentError, LLMError, MCPConnectionError
from app.request_context import init_llm_event_bridge, teardown_llm_event_bridge
from app.store.keys import key_ui_events as _key_ui_events
from app.hooks.session_hooks import TABLE_ROW_CACHE as _table_row_cache
from app.hooks.session_hooks import table_row_cache_key as _cache_key

log = logging.getLogger(__name__)

def _sanitize_floats(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so the result is valid JSON."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _collect_grafana_urls(obj: Any, seen: set, depth: int = 0) -> None:
    """Recursively walk a response dict and collect all grafana_url string values.

    Health check responses nest grafana_url inside checks.<metric>.grafana_url.
    Depth is capped at 6 to avoid traversing unbounded structures.
    """
    if depth > 6 or not isinstance(obj, (dict, list)):
        return
    if isinstance(obj, dict):
        url = obj.get("grafana_url")
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
        for v in obj.values():
            _collect_grafana_urls(v, seen, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_grafana_urls(item, seen, depth + 1)


def _extract_graph_events(response: dict) -> list[tuple[str, dict]]:
    """Inspect any MCP tool response and return (graph_tool, args) pairs to render.

    Works for ALL providers — no hardcoded tool names.  Any response that
    carries one of the recognised keys triggers a graph event:

    * ``chart_data``       → render_chart        (single line/bar chart)
    * ``multi_chart_data`` → render_multi_chart   (synchronized multi-panel)
    * ``grafana_url``      → render_grafana_panel (live Grafana iframe)
    * ``table_data``       → render_table_data    (paginated data table)

    grafana_url is searched recursively — health check results nest it at
    checks.<metric>.grafana_url, not at the top level.

    See docs/runner-sse-event-registry.md for the full MCP tool developer guide.
    """
    renders: list[tuple[str, dict]] = []
    if isinstance(response.get("chart_data"), dict):
        renders.append(("render_chart", response["chart_data"]))
    if isinstance(response.get("multi_chart_data"), dict):
        renders.append(("render_multi_chart", response["multi_chart_data"]))
    if isinstance(response.get("table_data"), dict):
        renders.append(("render_table_data", response["table_data"]))
    # Collect all grafana_url values anywhere in the response tree
    seen_urls: set = set()
    _collect_grafana_urls(response, seen_urls)
    for url in seen_urls:
        renders.append(("render_grafana_panel", {"url": url}))
    return renders


# ── MCP tool registry ──────────────────────────────────────────────────────────
# Populated at startup from mcp_pool.claude_tools so the exception handlers can
# look up the exact tool (including its full input_schema) by Anthropic's index.
_mcp_tool_registry: list[dict] = []


def register_mcp_tools(tools: list[dict]) -> None:
    """Store the full claude_tools list for use in schema-error diagnostics."""
    global _mcp_tool_registry
    _mcp_tool_registry = list(tools)
    log.info("MCP tool registry updated — %d tools registered", len(_mcp_tool_registry))


# Keywords Anthropic rejects under JSON Schema draft 2020-12
_SUSPICIOUS_KEYS = {
    "default",      # annotation — Anthropic strict validator rejects it
    "definitions",  # replaced by $defs in draft 2020-12
    "$ref",         # can cause issues with Anthropic's validator
    "id",           # replaced by $id in draft 2020-12
    "$schema",      # not allowed inside sub-schemas
    "if", "then", "else",  # conditional keywords — often rejected
}


def find_suspicious_fields(schema: dict, path: str = "input_schema") -> list[str]:
    """Recursively walk a JSON schema and return dot-paths of suspicious fields."""
    hits: list[str] = []
    for key, value in schema.items():
        current = f"{path}.{key}"
        if key in _SUSPICIOUS_KEYS:
            hits.append(f"{current}={value!r}")
        if isinstance(value, dict):
            hits.extend(find_suspicious_fields(value, current))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    hits.extend(find_suspicious_fields(item, f"{current}[{i}]"))
    return hits


# ── MCP server registry ───────────────────────────────────────────────────────
# Populated at startup from server_configs so error handlers can identify which
# MCP server is down by matching URLs found in exception messages / cause chains.
_mcp_server_registry: dict[str, str] = {}   # url → server name


def register_mcp_servers(servers: list[dict]) -> None:
    """Store the URL→name mapping for all configured MCP servers.

    Args:
        servers: List of ``{"name": ..., "url": ...}`` dicts from ``MCPPool.servers``.
    """
    global _mcp_server_registry
    _mcp_server_registry = {s["url"]: s["name"] for s in servers}
    log.info(
        "MCP server registry updated — %d server(s): %s",
        len(_mcp_server_registry),
        [s["name"] for s in servers],
    )


# ── MCP connection error detection ─────────────────────────────────────────────

_MCP_ERROR_SIGNATURES = (
    "Failed to get tools from MCP server",
    "Failed to call tool on MCP server",
    "Failed to connect to MCP server",
    "MCP session",
)


def _is_mcp_connection_error(exc: Exception) -> bool:
    """Return True if the exception originates from an MCP server connectivity failure.

    Checks both the exception type (ConnectionError from ADK's MCPToolset) and
    known error message signatures that indicate MCP server unavailability.
    """
    exc_str = str(exc)
    if isinstance(exc, ConnectionError):
        return any(sig in exc_str for sig in _MCP_ERROR_SIGNATURES)
    # Also catch wrapped exceptions (e.g. TaskGroup sub-exceptions)
    if any(sig in exc_str for sig in _MCP_ERROR_SIGNATURES):
        return True
    return False


def _identify_failed_server(exc: Exception) -> str | None:
    """Try to identify which MCP server failed by matching URLs in the exception chain.

    Walks the exception ``__cause__`` chain and the string representation to
    find a URL that matches a registered MCP server.

    Returns:
        The server name if identified, else ``None``.
    """
    # Collect all text from the exception chain
    texts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        texts.append(str(current))
        # Also check repr — some exceptions embed URLs in repr but not str
        texts.append(repr(current))
        current = current.__cause__
    combined = " ".join(texts)

    for url, name in _mcp_server_registry.items():
        if url in combined:
            return name
    return None


def _build_mcp_error_message(exc: Exception) -> str:
    """Build a user-friendly MCP error message, identifying the failed server if possible.

    Returns:
        A human-readable error string naming the specific server if identified,
        or a generic message listing all configured servers otherwise.
    """
    server_name = _identify_failed_server(exc)

    if server_name:
        return (
            f"The **{server_name}** service is temporarily unavailable. "
            f"Please try again in a few moments. If the issue persists, "
            f"contact the SRE Super Agent team in #sre-super-agent."
        )

    # Fallback: list all configured servers so the user/on-call has context
    if _mcp_server_registry:
        all_names = ", ".join(sorted(_mcp_server_registry.values()))
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


# ── Private helpers ────────────────────────────────────────────────────────────


async def _ensure_session(runner: Runner, user_id: str, session_id: str) -> None:
    """Create an ADK session in the store if it does not already exist.

    No-op when the session was created in a previous turn, so this is safe to
    call unconditionally at the start of every request.

    Args:
        runner:     ADK Runner whose ``session_service`` is used for lookup/create.
        user_id:    Caller user identifier; scopes Redis keys.
        session_id: Session identifier; created on first use.
    """
    existing = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if existing is None:
        await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id,
            # Initialize active_context so ADK's inject_session_state never
            # throws KeyError on the first turn before any tool has been called.
            state={"active_context": ""},
        )


def _build_user_content(query: str) -> genai_types.Content:
    """Wrap a query string in an ADK user ``Content`` object.

    Args:
        query: The user's natural language input.

    Returns:
        A ``genai_types.Content`` with ``role="user"`` and a single text part.
    """
    return genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=query)],
    )


def _parts_to_text(parts) -> str:
    """Concatenate text from all ``Content`` parts into a single string.

    Filters out thought parts (Claude extended thinking blocks) so only
    the agent's actual response text is returned.

    Args:
        parts: Iterable of ``genai_types.Part`` objects.

    Returns:
        Newline-joined string of all non-empty, non-thought text parts.
    """
    return "\n".join(
        p.text
        for p in parts
        if hasattr(p, "text") and p.text and getattr(p, "thought", None) is not True
    )


# ── Tool call labels & categories ──────────────────────────────────────────────

# Static labels for skill tools (emoji prefix for visual distinction in the UI).
_SKILL_TOOL_LABELS = {
    "list_skills":          "🧩 Discovering Skills",
    "load_skill":           "🧩 Loading Skill",
    "load_skill_resource":  "🧩 Loading Skill Resource",
    "run_skill_script":     "🧩 Running Skill Script",
}


def _tool_category(name: str) -> str:
    """Classify a tool call as ``"skill"`` or ``"tool"``.

    Skill calls are the 4 ADK SkillToolset tools (list_skills, load_skill,
    load_skill_resource, run_skill_script).
    Everything else (MCP tools, get_mcp_prompt, pingfed_token, A2A tools) is ``"tool"``.
    """
    return "skill" if name in _SKILL_TOOLS else "tool"


_VENDOR_PREFIXES = ("wcnp_", "mcp_", "k8s_", "sre_", "health_")


def _tool_label(name: str, args: dict | None = None) -> str:
    """Derive a human-readable label from a tool or skill name.

    For SkillToolset tools, returns an emoji-prefixed label with context
    extracted from ``args`` (e.g. the skill name being loaded or script path).

    For MCP tools, strips common vendor prefixes (e.g. ``wcnp_``, ``mcp_``)
    then converts the remaining snake_case to Title Case.

    Args:
        name: The raw tool/function name from the ADK event.
        args: Optional args dict from the function_call.  Used to enrich
              skill labels with context (e.g. which skill is being loaded).

    Examples:
        ``list_skills``                                        → ``🧩 Discovering Skills``
        ``load_skill`` + args {skill_name: "health-triage"}    → ``🧩 Loading Skill: health-triage``
        ``run_skill_script`` + args {skill_name: "x", ...}     → ``🧩 Running Script: x/summarize_health.py``
        ``wcnp_check_namespace_health``                        → ``Check Namespace Health``
        ``prometheus_query_range``                              → ``Query Range``
    """
    if not name:
        return "Unknown Tool"

    # ── Skill tools: rich labels with context from args ──
    if name in _SKILL_TOOLS:
        base = _SKILL_TOOL_LABELS.get(name, name.replace("_", " ").title())
        if args and isinstance(args, dict):
            if name == "load_skill":
                skill_name = args.get("skill_name") or ""
                if skill_name:
                    return f"{base}: {skill_name}"
            elif name == "run_skill_script":
                skill_name = args.get("skill_name") or ""
                script_path = args.get("script_path") or ""
                if skill_name and script_path:
                    return f"{base}: {skill_name}/{script_path.split('/')[-1]}"
                elif skill_name:
                    return f"{base}: {skill_name}"
            elif name == "load_skill_resource":
                skill_name = args.get("skill_name") or ""
                resource = args.get("resource_path") or args.get("resource_id") or ""
                if skill_name and resource:
                    return f"{base}: {skill_name}/{resource.split('/')[-1]}"
                elif skill_name:
                    return f"{base}: {skill_name}"
        return base

    # ── MCP / regular tools: strip vendor prefix, Title Case ──
    clean = name
    for prefix in _VENDOR_PREFIXES:
        if name.startswith(prefix):
            clean = name[len(prefix):]
            break
    return clean.replace("_", " ").title()



# ── Public API ─────────────────────────────────────────────────────────────────


async def run_agent(runner: Runner, user_id: str, session_id: str, query: str) -> str:
    """Run ``root_agent`` for a single user turn and return the final text.

    Creates a ``Content`` message, streams events from the ADK runner, and
    returns the concatenated text from the first final-response event.

    Args:
        runner:     The ADK ``Runner`` instance stored on ``app.state.runner``.
        user_id:    Caller-supplied user identifier; scopes Redis session keys.
        session_id: Unique session identifier; created in Redis if absent.
        query:      The user's natural language input.

    Returns:
        The agent's final text response.

    Raises:
        LLMError:   When the upstream LLM gateway returns a non-2xx response.
        AgentError: When the agentic loop encounters any other unrecoverable error.
    """
    content = _build_user_content(query)
    log.info("[%s/%s] Query: %s", user_id, session_id, query)

    try:
        await _ensure_session(runner, user_id, session_id)

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            # ── Log tool / skill calls and responses ─────────────────────────
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        fc_name = fc.name or "<unknown>"
                        args_preview = str(fc.args)[:200] if fc.args else "{}"
                        category = _tool_category(fc_name)
                        call_kind = "Skill call" if category == "skill" else "MCP tool call"
                        log.info(
                            "[%s/%s] %s  → %s  args=%s",
                            user_id, session_id, call_kind, fc_name, args_preview,
                        )
                    elif hasattr(part, "function_response") and part.function_response:
                        fr = part.function_response
                        fr_name = fr.name or "<unknown>"
                        resp_preview = str(fr.response)[:300] if fr.response else "{}"
                        category = _tool_category(fr_name)
                        resp_kind = "Skill response" if category == "skill" else "MCP tool response"
                        log.info(
                            "[%s/%s] %s ← %s  result=%s",
                            user_id, session_id, resp_kind, fr_name, resp_preview,
                        )

            if event.is_final_response() and event.content and event.content.parts:
                answer = _parts_to_text(event.content.parts)
                log.info(
                    "[%s/%s] Final response: %d chars — %.200s%s",
                    user_id, session_id, len(answer), answer,
                    "…" if len(answer) > 200 else "",
                )
                return answer

    except LLMError:
        raise
    except MCPConnectionError:
        raise
    except Exception as exc:
        # ── MCP server connectivity failures → friendly user message ──────
        if _is_mcp_connection_error(exc):
            log.error(
                "MCP connection failure for %s/%s: %s", user_id, session_id, exc,
            )
            raise MCPConnectionError(_build_mcp_error_message(exc)) from exc

        exc_str = str(exc)
        _schema_match = re.search(r"tools\.(\d+)\.", exc_str)
        if _schema_match and "input_schema" in exc_str:
            _idx = int(_schema_match.group(1))
            if _idx < len(_mcp_tool_registry):
                _bad_tool    = _mcp_tool_registry[_idx]
                _bad_fields  = find_suspicious_fields(_bad_tool.get("input_schema", {}))
                log.warning(
                    "MCP tool schema error — tool[%d] name=%r | suspicious fields: %s",
                    _idx, _bad_tool.get("name"),
                    _bad_fields or ["<none detected — check full schema>"],
                )
                log.debug("MCP tool schema error — tool[%d] full JSON:\n%s",
                    _idx, json.dumps(_bad_tool, indent=2),
                )
            else:
                log.error(
                    "MCP tool schema error — tool index %d out of range (registry has %d tools)",
                    _idx, len(_mcp_tool_registry),
                )
        log.exception("ADK runner error for %s/%s: %s", user_id, session_id, exc)
        for code in LLM_HTTP_ERROR_CODES:
            if str(code) in exc_str:
                raise LLMError(status_code=code, detail=exc_str[:500]) from exc
        raise AgentError(exc_str) from exc

    log.warning("ADK runner produced no final response for %s/%s", user_id, session_id)
    return ""


async def run_agent_with_events(
    runner: Runner,
    user_id: str,
    session_id: str,
    query: str,
) -> AsyncGenerator[str, None]:
    """Run ``root_agent`` and yield SSE-formatted progress events + final response.

    Yields ``data: <json>\\n\\n`` lines in text/event-stream format:

    * ``{"type":"thinking","text":"<thought>"}``
      Claude's extended thinking blocks (chain-of-thought reasoning).
      Only emitted when ``LLM_EXTENDED_THINKING_ENABLED=true``.
    * ``{"type":"reasoning","text":"<text>"}``
      Intermediate text the LLM produces between tool calls
      (e.g. "Let me check the namespace health...").  Always available.
    * ``{"type":"progress","tool":"<name>","label":"<label>","status":"running"}``
      emitted when an MCP function_call is seen.
    * ``{"type":"progress","tool":"<name>","label":"<label>","status":"done"}``
      emitted when the corresponding function_response arrives.
    * ``{"type":"complete","text":"<answer>"}`` on the final agent response.
    * ``{"type":"error","message":"<detail>"}`` on any exception.

    **Frontend rendering contract for thinking/reasoning events:**

    The UI should render these in a ``ReasoningStream`` panel that:
      • Shows the last ~5 lines of reasoning/thinking text while processing
      • Scrolls up to reveal full history on user interaction
      • Auto-collapses to a compact summary line when the ``complete`` event arrives
      • Distinguishes thinking (deeper, analytical) from reasoning (conversational)

    Context trimming is handled by the agent's ``before_agent_callback`` —
    the LLM always starts with a clean (or windowed) context regardless of
    how large the Redis session history has grown.

    Args:
        runner:     ADK Runner stored on ``app.state.runner``.
        user_id:    Caller user identifier.
        session_id: Redis session key.
        query:      The user's natural language input.
    """
    content = _build_user_content(query)

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    # ── UI event persistence helpers ───────────────────────────────────────────
    _redis    = runner.session_service._redis
    _ttl      = runner.session_service._ttl
    _ui_key   = _key_ui_events(_APP_NAME, user_id, session_id)

    async def _persist(event_data: dict) -> None:
        """Fire-and-forget: append event to the UI events log in Redis."""
        try:
            await asyncio.gather(
                _redis.rpush(_ui_key, json.dumps({**event_data, "ts": _time.time()})),
                _redis.expire(_ui_key, _ttl),
            )
        except Exception as _pe:
            log.warning("ui_events persist failed (non-fatal): %s", _pe)

    # ── LLM event bridge ────────────────────────────────────────────────────────
    # Allows agent.py (LiteLLM client layer) to push progress events that we
    # drain and yield as SSE between ADK event iterations.
    _llm_events = init_llm_event_bridge()

    _context_shrink_attempted = False  # set True if any context_shrink event was drained

    async def _drain_llm_events():
        """Yield + persist any events pushed by the LLM client layer (e.g. context shrink)."""
        nonlocal _context_shrink_attempted
        while _llm_events:
            llm_ev = _llm_events.pop(0)
            if llm_ev.get("call_id") == "context_shrink":
                _context_shrink_attempted = True
            yield _sse(llm_ev)
            await _persist(llm_ev)

    try:
        await _ensure_session(runner, user_id, session_id)

        # Record the user message as the first event in this turn
        await _persist({"type": "user", "text": query})

        # Cache call_id → label so "done" events reuse the richer args-enriched
        # label from the corresponding "running" event (function_response has no args).
        _call_label_cache: dict[str, str] = {}

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            # Drain any events pushed by the LLM client layer (e.g. context shrink)
            async for sse_line in _drain_llm_events():
                yield sse_line

            if event.content and event.content.parts:
                _is_final = event.is_final_response()
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        name    = part.function_call.name or ""
                        _cid    = getattr(part.function_call, "id", None)
                        call_id = _cid if isinstance(_cid, str) and _cid else name
                        # Extract args dict for label enrichment + event payload
                        _fc_args: dict | None = None
                        if part.function_call.args:
                            try:
                                _fc_args = dict(part.function_call.args)
                                json.dumps(_fc_args)  # validate serializable
                            except (TypeError, ValueError) as _e:
                                log.warning("tool args not JSON-serializable (%s) — omitting args", _e)
                                _fc_args = None
                        category = _tool_category(name)
                        label = _tool_label(name, args=_fc_args)
                        _call_label_cache[call_id] = label
                        event_data: dict = {
                            "type": "progress",
                            "tool": name,
                            "call_id": call_id,
                            "label": label,
                            "category": category,
                            "status": "running",
                        }
                        if _fc_args is not None:
                            event_data["args"] = _fc_args
                        yield _sse(event_data)
                        await _persist(event_data)

                        # ── Frontend-rendered chart tools (render_chart, render_multi_chart) ──
                        # These tools are intercepted client-side from the function_call args.
                        # In the SSE streaming path, we emit a type:"graph" event here so the
                        # UI renders the chart — the MCP tool response only returns {"rendered":True}
                        # which contains no chart_data, so _extract_graph_events() won't fire.
                        _RENDER_CHART_TOOLS = {"render_chart", "render_multi_chart"}
                        if name in _RENDER_CHART_TOOLS and part.function_call.args:
                            try:
                                _render_args = _sanitize_floats(dict(part.function_call.args))
                                _valid = (
                                    # render_chart: needs labels + datasets
                                    (_render_args.get("labels") and _render_args.get("datasets"))
                                    # render_multi_chart: needs charts array
                                    or bool(_render_args.get("charts"))
                                )
                                if _valid:
                                    _graph_event: dict = {
                                        "type": "graph",
                                        "graph_tool": name,
                                        "call_id": f"graph_{call_id}",
                                        "args": _render_args,
                                    }
                                    json.dumps(_graph_event)  # validate before yielding
                                    yield _sse(_graph_event)
                                    await _persist(_graph_event)
                            except Exception as _re:
                                log.warning("render_chart graph event skipped for %s: %s", name, _re)

                    elif hasattr(part, "function_response") and part.function_response:
                        name    = part.function_response.name or ""
                        _cid    = getattr(part.function_response, "id", None)
                        call_id = _cid if isinstance(_cid, str) and _cid else name
                        # Reuse the richer label from the "running" event if available
                        done_label = _call_label_cache.pop(call_id, None) or _tool_label(name)
                        done_event: dict = {
                            "type": "progress",
                            "tool": name,
                            "call_id": call_id,
                            "label": done_label,
                            "category": _tool_category(name),
                            "status": "done",
                        }
                        yield _sse(done_event)
                        await _persist(done_event)

                        # ── Emit type:"graph" events from any response with chart/grafana data ──
                        # ADK wraps MCP TextContent as:
                        #   {"content": [{"type": "text", "text": "<json>"}], "isError": false}
                        # We parse the first text content item to recover the actual tool response.
                        if part.function_response.response:
                            try:
                                _raw = dict(part.function_response.response)
                                # Unwrap MCP TextContent envelope
                                _content = _raw.get("content") or []
                                _resp: dict | None = None
                                for _item in _content:
                                    if isinstance(_item, dict) and _item.get("type") == "text":
                                        try:
                                            _parsed = json.loads(_item["text"])
                                            if isinstance(_parsed, dict):
                                                _resp = _parsed
                                                break
                                        except (json.JSONDecodeError, KeyError):
                                            pass
                                if _resp is None:
                                    _resp = _raw  # fallback: search top-level keys
                                # Restore full table rows from cache if they were
                                # stripped by after_tool_callback to save LLM tokens.
                                if (
                                    isinstance(_resp.get("table_data"), dict)
                                    and _resp["table_data"].get("_rows_stripped")
                                ):
                                    _ck = _cache_key(session_id, call_id)
                                    _cached = _table_row_cache.pop(_ck, None)
                                    if _cached is not None:
                                        _resp = {**_resp, "table_data": _cached["table_data"]}
                                        log.debug("runner: restored %d cached rows for cache_key=%s", len(_cached["table_data"].get("rows", [])), _ck)
                                for _graph_tool, _graph_args in _extract_graph_events(_resp):
                                    _graph_args_clean = _sanitize_floats(_graph_args)
                                    _graph_event: dict = {
                                        "type": "graph",
                                        "graph_tool": _graph_tool,
                                        "call_id": f"graph_{call_id}",
                                        "args": _graph_args_clean,
                                    }
                                    json.dumps(_graph_event)  # validate before sending
                                    yield _sse(_graph_event)
                                    await _persist(_graph_event)
                            except Exception as _ge:
                                log.warning("Graph event skipped for %s: %s", name, _ge)

                    # ── Reasoning & Thinking: stream LLM thought process to the UI ──
                    # Two event types for the frontend ReasoningStream panel:
                    #
                    # 1. "thinking" — Claude's extended thinking blocks (part.thought=True).
                    #    Deep chain-of-thought reasoning; requires LLM_EXTENDED_THINKING_ENABLED.
                    #
                    # 2. "reasoning" — Intermediate text the LLM produces between tool calls
                    #    (e.g. "Let me check the namespace health...").  Free — no extra tokens.
                    #    Only emitted for non-final events to avoid duplicating the answer text.
                    #
                    # Frontend contract:
                    #   • Show in a collapsible ReasoningStream panel
                    #   • Display last 5 lines with scroll-up for history
                    #   • Auto-collapse to summary when "complete" event arrives
                    elif hasattr(part, "text") and part.text:
                        _is_thought = getattr(part, "thought", None) is True
                        _text = part.text.strip()
                        if not _text:
                            continue

                        if _is_thought:
                            # Extended thinking block from Claude
                            _thinking_event: dict = {
                                "type": "thinking",
                                "text": _text,
                            }
                            yield _sse(_thinking_event)
                            await _persist(_thinking_event)
                        elif not _is_final:
                            # Intermediate reasoning text between tool calls
                            # (skip on final response — that text goes into "complete")
                            _reasoning_event: dict = {
                                "type": "reasoning",
                                "text": _text,
                            }
                            yield _sse(_reasoning_event)
                            await _persist(_reasoning_event)

            if event.is_final_response() and event.content and event.content.parts:
                # Drain any remaining LLM-layer events before the final response
                async for sse_line in _drain_llm_events():
                    yield sse_line
                # Extract only non-thought text for the final answer
                answer = "\n".join(
                    p.text for p in event.content.parts
                    if hasattr(p, "text") and p.text and getattr(p, "thought", None) is not True
                )
                complete_event: dict = {"type": "complete", "text": answer}
                yield _sse(complete_event)
                await _persist(complete_event)
                return

    except LLMError as exc:
        # Drain LLM events — context shrink may have fired before the LLM error
        async for sse_line in _drain_llm_events():
            yield sse_line
        _llm_err_event: dict = {
            "type": "progress",
            "tool": "llm_error",
            "call_id": "llm_error",
            "label": f"❌ LLM Error ({exc.status_code})",
            "category": "system",
            "status": "error",
        }
        yield _sse(_llm_err_event)
        await _persist(_llm_err_event)
        yield _sse({"type": "error", "message": f"LLM error {exc.status_code}: {exc.detail}"})
    except Exception as exc:
        # Drain LLM events — context shrink may have fired before the exception
        async for sse_line in _drain_llm_events():
            yield sse_line

        # ── MCP server connectivity failures → friendly user message ──────
        if _is_mcp_connection_error(exc):
            log.error("MCP connection failure for %s/%s: %s", user_id, session_id, exc)
            _mcp_err_event: dict = {
                "type": "progress",
                "tool": "mcp_connection",
                "call_id": "mcp_error",
                "label": f"❌ Backend Service Unavailable — {_identify_failed_server(exc) or 'unknown'}",
                "category": "system",
                "status": "error",
            }
            yield _sse(_mcp_err_event)
            await _persist(_mcp_err_event)
            error_event: dict = {"type": "error", "message": _build_mcp_error_message(exc)}
            yield _sse(error_event)
            await _persist(error_event)
            return

        exc_str = str(exc)

        # ── Context overflow that survived shrink+retry → friendly message ──
        _CONTEXT_KEYWORDS = (
            "contextwindowexceedederror", "prompt is too long", "prompt: length",
            "context length", "maximum context", "too many tokens",
            "request too large", "payload size exceeds",
        )
        _exc_lower = exc_str.lower()
        _type_name = type(exc).__name__.lower()
        if (
            "contextwindow" in _type_name
            or any(kw in _exc_lower for kw in _CONTEXT_KEYWORDS)
            # Anthropic generic 400 after shrink attempt — the flag confirms it
            or (_type_name == "badrequesterror" and _context_shrink_attempted)
        ):
            log.warning("Context overflow (post-retry) for %s/%s: %s", user_id, session_id, exc)
            yield _sse({
                "type": "error",
                "message": (
                    "The conversation has grown too long for the model's context window. "
                    "I've tried to optimize, but there's still too much content. "
                    "Please start a new session to continue."
                ),
            })
            return

        _schema_match = re.search(r"tools\.(\d+)\.", exc_str)
        if _schema_match and "input_schema" in exc_str:
            _idx = int(_schema_match.group(1))
            _bad_tool_name = "<unknown>"
            if _idx < len(_mcp_tool_registry):
                _bad_tool   = _mcp_tool_registry[_idx]
                _bad_tool_name = _bad_tool.get("name", "<unknown>")
                _bad_fields = find_suspicious_fields(_bad_tool.get("input_schema", {}))
                log.warning(
                    "MCP tool schema error — tool[%d] name=%r | suspicious fields: %s",
                    _idx, _bad_tool_name,
                    _bad_fields or ["<none detected — check full schema>"],
                )
                log.debug("MCP tool schema error — tool[%d] full JSON:\n%s",
                    _idx, json.dumps(_bad_tool, indent=2),
                )
            else:
                log.error(
                    "MCP tool schema error — tool index %d out of range (registry has %d tools)",
                    _idx, len(_mcp_tool_registry),
                )
            # Emit a specific schema-error event so the UI shows what tool broke
            _schema_err_event: dict = {
                "type": "progress",
                "tool": "schema_validation",
                "call_id": "schema_error",
                "label": f"❌ Tool Schema Error — {_bad_tool_name}",
                "category": "system",
                "status": "error",
            }
            yield _sse(_schema_err_event)
            await _persist(_schema_err_event)
        log.exception("run_agent_with_events error for %s/%s: %s", user_id, session_id, exc)
        yield _sse({"type": "error", "message": exc_str})
    finally:
        teardown_llm_event_bridge()
