"""Per-request LLM Gateway header propagation via async contextvars.

Middleware in factory.py calls set_llm_headers() at request start;
llm.py and agent.py call get_llm_headers() when making outbound LLM calls.

Mandatory headers (lowercase per gateway spec):
  wm_llm_gw.user_type  — ASSOCIATE | RETAIL_CUSTOMER | VENDOR | TECH_DEVELOPMENT | NO_END_USER
  wm_llm_gw.user_name  — user identifier (loginId / email)
  wm_llm_gw.user_agent — browser user-agent string
  wm_llm_gw.user_ip    — client IP address

User time context (set by _before_agent in factory.py from x-user-timezone /
x-current-epoch-ms HTTP headers sent by the UI):
  _cv_timezone   — IANA timezone string, e.g. "America/Los_Angeles"
  _cv_epoch_ms   — browser epoch ms at request time, e.g. "1743494400000"
"""

import logging
from contextvars import ContextVar

from starlette.requests import Request

log = logging.getLogger(__name__)

# ── Context variable ──────────────────────────────────────────────────────────
# Stores the wm_llm_gw.* headers extracted from the incoming HTTP request.
# Each async task gets its own copy (contextvars are per-asyncio-Task safe).

_llm_headers: ContextVar[dict[str, str]] = ContextVar("_llm_headers", default={})

# ── User time context ─────────────────────────────────────────────────────────
# Captured from x-user-timezone / x-current-epoch-ms HTTP headers by
# _LLMHeaderContextBuilder + _before_agent in factory.py.
# Read by _inject_time_context before_model_callback in agent/__init__.py to
# prepend a time-context block to the LLM system instruction per request.
_cv_timezone: ContextVar[str] = ContextVar("user_timezone",    default="")
_cv_epoch_ms: ContextVar[str] = ContextVar("current_epoch_ms", default="")

# Per-request user PingFed bearer token — used by the MCP header_provider
# for required_token=true servers (Jira, Confluence, etc.) so tool calls
# are authenticated as the real human user, not the service account.
_cv_user_token: ContextVar[str] = ContextVar("user_auth_token", default="")

# Fallback store keyed by session ID — used when ContextVar doesn't propagate
# across async task boundaries (ADK may spawn agents in separate tasks).
_user_token_store: dict[str, str] = {}

# Header keys we extract from the incoming request and forward to the LLM Gateway.
# Lowercase per LLM Gateway spec requirement.
LLM_HEADER_KEYS = (
    "wm_llm_gw.user_type",
    "wm_llm_gw.user_name",
    "wm_llm_gw.user_agent",
    "wm_llm_gw.user_ip",
)

# Valid values for wm_llm_gw.user_type per LLM Gateway spec.
_VALID_USER_TYPES = frozenset({
    "ASSOCIATE",
    "RETAIL_CUSTOMER",
    "VENDOR",
    "TECH_DEVELOPMENT",
    "NO_END_USER",
})

# Legacy values from old frontend code (employeeType S/H, old sre-ai-ui default)
_LEGACY_ASSOCIATE = frozenset({"S", "H", "SALARIED", "HOURLY", "STANDARD"})

# Default user_type when the frontend sends an invalid/missing value.
# This is an internal SRE tool — all users are Walmart associates.
_DEFAULT_USER_TYPE = "ASSOCIATE"


def _normalize_user_type(value: str) -> str:
    """Normalize wm_llm_gw.user_type to a valid LLM Gateway value."""
    upper = value.strip().upper()
    if upper in _VALID_USER_TYPES:
        return upper
    if upper in _LEGACY_ASSOCIATE:
        log.debug("Mapped legacy user_type %r → ASSOCIATE", value)
        return "ASSOCIATE"
    log.warning("Unknown wm_llm_gw.user_type %r — defaulting to %s", value, _DEFAULT_USER_TYPE)
    return _DEFAULT_USER_TYPE


def extract_llm_headers(request: Request) -> dict[str, str]:
    """Extract and normalize wm_llm_gw.* headers from the request.

    Defaults user_type to ASSOCIATE if missing; falls back to loginId for user_name.
    """
    headers: dict[str, str] = {}
    for key in LLM_HEADER_KEYS:
        if value := request.headers.get(key):
            headers[key] = _normalize_user_type(value) if key == "wm_llm_gw.user_type" else value

    if "wm_llm_gw.user_type" not in headers:
        headers["wm_llm_gw.user_type"] = _DEFAULT_USER_TYPE

    if "wm_llm_gw.user_name" not in headers:
        if login_id := (request.headers.get("loginid") or request.headers.get("loginId")):
            headers["wm_llm_gw.user_name"] = login_id

    return headers


def set_llm_headers(headers: dict[str, str]) -> None:
    """Store LLM Gateway headers in the current async context (called by middleware)."""
    _llm_headers.set(headers)


def get_llm_headers() -> dict[str, str]:
    """Retrieve LLM Gateway headers from the current async context (called by llm.py / agent.py)."""
    return _llm_headers.get()


def clear_llm_headers() -> None:
    """Clear LLM Gateway headers after request processing."""
    _llm_headers.set({})


# ── LLM-layer event bridge ────────────────────────────────────────────────────
# Allows the LiteLLM client layer (agent.py) to emit progress events that the
# SSE event stream in runner.py can surface to the UI.  Events are appended to
# a per-request list; runner.py drains it between ADK event iterations.
#
# Each event is a plain dict ready to be JSON-serialised as an SSE payload,
# e.g. {"type": "progress", "tool": "context_management", "label": "...", ...}

_cv_llm_events: ContextVar[list[dict] | None] = ContextVar("llm_events", default=None)


def init_llm_event_bridge() -> list[dict]:
    """Create and install a fresh event list for the current request.

    Call at the start of ``run_agent_with_events()`` so that ``agent.py`` can
    push progress events during LLM calls.

    Returns:
        The mutable list that will accumulate events (also stored in the contextvar).
    """
    events: list[dict] = []
    _cv_llm_events.set(events)
    return events


def push_llm_event(event: dict) -> None:
    """Append a progress event from the LLM client layer.

    No-op if the bridge hasn't been initialised (e.g. non-streaming path or tests).
    """
    buf = _cv_llm_events.get(None)
    if buf is not None:
        buf.append(event)


def teardown_llm_event_bridge() -> None:
    """Detach the event bridge at the end of the request."""
    _cv_llm_events.set(None)


def set_user_time_context(timezone: str, epoch_ms: str) -> None:
    """Store the user's browser timezone and current epoch ms in the async context.

    Called by _before_agent in factory.py after reading x-user-timezone and
    x-current-epoch-ms from the incoming A2A request headers.

    Args:
        timezone: IANA timezone string, e.g. "America/Los_Angeles" or "Asia/Kolkata".
        epoch_ms: Browser epoch milliseconds as a string, e.g. "1743494400000".
    """
    _cv_timezone.set(timezone)
    _cv_epoch_ms.set(epoch_ms)


def get_user_time_context() -> tuple[str, str]:
    """Retrieve the user's timezone and epoch ms from the current async context.

    Returns:
        (timezone, epoch_ms) — both are empty strings when not set.
    """
    return _cv_timezone.get(), _cv_epoch_ms.get()


def set_user_token(token: str, session_id: str = "") -> None:
    """Store the user's PingFed bearer token for MCP auth.

    Sets the token in the current async contextvar (primary) and also in a
    module-level dict keyed by session_id (fallback when contextvar doesn't
    propagate across ADK async task boundaries).

    Called by _before_agent in factory.py after reading the Authorization
    header from the incoming A2A request.
    """
    _cv_user_token.set(token)
    if session_id:
        _user_token_store[session_id] = token
        # Cap size — evict oldest half when over limit
        if len(_user_token_store) > 2000:
            evict = list(_user_token_store.keys())[: len(_user_token_store) // 2]
            for k in evict:
                _user_token_store.pop(k, None)


def get_user_token(session_id: str = "") -> str:
    """Retrieve the user's PingFed bearer token for MCP auth.

    Tries the async contextvar first (primary, per-task safe).  Falls back
    to the module-level dict keyed by session_id when the contextvar is
    empty (e.g. ADK spawned a new asyncio.Task without context propagation).

    Returns:
        The raw bearer token string, or empty string when not available.
    """
    token = _cv_user_token.get()
    if not token and session_id:
        token = _user_token_store.get(session_id, "")
    return token
