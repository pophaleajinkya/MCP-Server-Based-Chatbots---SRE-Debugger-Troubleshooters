"""
ADK hook callbacks for the super-agent orchestrator.

All before_agent_callback / after_agent_callback / after_tool_callback
implementations live here, keeping agent definitions and session storage
layers free of hook logic.

Exports
-------
trim_session_history   — before_agent_callback that enforces LLM_HISTORY_TURNS
after_tool_handler     — after_tool_callback for generic post-processing
table_row_cache_key    — build session-scoped key for TABLE_ROW_CACHE
"""

from app.hooks.session_hooks import (
    after_tool_handler,
    commit_pending_observations,
    inject_pending_observations,
    on_tool_error_handler,
    table_row_cache_key,
    trim_session_history,
)

__all__ = [
    "trim_session_history",
    "inject_pending_observations",
    "commit_pending_observations",
    "after_tool_handler",
    "on_tool_error_handler",
    "table_row_cache_key",
]
