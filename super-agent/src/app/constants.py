"""Application-wide constants shared across modules.

Centralises every magic string and numeric code so that each value lives in
exactly one place — import from here rather than defining locally.
"""

import os

# ── Agent identity ─────────────────────────────────────────────────────────────

APP_NAME: str = os.getenv("APP_NAME", "health_agent")
"""Application name used as the ADK ``app_name`` and Redis key prefix.

Override via the ``APP_NAME`` environment variable (e.g. in ``.env``).
Defaults to ``"health_agent"`` when not set.
"""

DEFAULT_USER_ID: str = "admin"
"""Default caller identity used by the query and A2A routers."""

# ── LLM error handling ─────────────────────────────────────────────────────────

LLM_HTTP_ERROR_CODES: tuple[int, ...] = (400, 401, 403, 404, 429, 500, 502, 503)
"""HTTP status codes that indicate a failure originating from the LLM gateway.

When the ADK runner raises an exception whose string representation contains
one of these codes the runner re-raises it as ``LLMError`` so FastAPI can
return a structured 502 response rather than a generic 500.
"""

# ── ADK SkillToolset ─────────────────────────────────────────────────────────

SKILL_TOOLS: frozenset[str] = frozenset({
    "list_skills",
    "load_skill",
    "load_skill_resource",
    "run_skill_script",
})
"""The 4 tool names exposed by ADK's SkillToolset.

Used by runner.py, debug.py, and sessions.py to classify SSE events as
``category: "skill"`` vs ``"tool"`` so the UI can render them differently.
"""


# ── JSON-RPC 2.0 error codes ──────────────────────────────────────────────────

class JSONRPCCode:
    """JSON-RPC 2.0 standard and application-specific numeric error codes.

    Standard codes are defined by the JSON-RPC 2.0 specification.
    Application-specific codes start at -32000 (per spec recommendation).
    """

    # Standard JSON-RPC 2.0 codes
    PARSE_ERROR: int       = -32700
    INVALID_REQUEST: int   = -32600
    METHOD_NOT_FOUND: int  = -32601
    INVALID_PARAMS: int    = -32602
    INTERNAL_ERROR: int    = -32603

    # Application-specific codes
    TASK_NOT_FOUND: int    = -32001
