"""MCPToolset wrapper that caches get_tools() results.

MCP tool definitions don't change at runtime — they're static declarations
registered when the server starts.  Yet ADK's _process_agent_tools calls
get_tools() → session.list_tools() (HTTP) for EVERY MCPToolset on EVERY
LLM iteration.  With 7 MCP servers, each round-trip ~200-500ms, that's
~1.5-3.5s of pure overhead **per LLM call** — and a typical turn has 2-3
LLM calls.

This wrapper calls the real MCPToolset.get_tools() once (on first access)
and returns the cached result on subsequent calls.  The cache can be
explicitly invalidated if a server's tools ever need refreshing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

log = logging.getLogger(__name__)


class CachingMCPToolset(MCPToolset):
    """MCPToolset subclass that caches the result of get_tools().

    First call to get_tools() delegates to the real MCPToolset (HTTP call).
    All subsequent calls return the cached list — zero network overhead.

    Thread-safety: uses an asyncio.Lock to ensure only one coroutine
    populates the cache (relevant if ADK ever parallelizes tool listing).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cached_tools: Optional[List[BaseTool]] = None
        self._cache_lock = asyncio.Lock()

    async def get_tools(
        self,
        readonly_context: Optional[ReadonlyContext] = None,
    ) -> List[BaseTool]:
        if self._cached_tools is not None:
            return self._cached_tools

        async with self._cache_lock:
            # Double-check after acquiring lock
            if self._cached_tools is not None:
                return self._cached_tools

            tools = await super().get_tools(readonly_context)
            self._cached_tools = tools
            tool_names = [t.name for t in tools]
            log.info(
                "CachingMCPToolset: cached %d tools from %s → %s",
                len(tools),
                getattr(self._connection_params, "url", "?"),
                tool_names,
            )
            return tools

    def invalidate_cache(self) -> None:
        """Force the next get_tools() call to re-fetch from the MCP server."""
        self._cached_tools = None
        log.info(
            "CachingMCPToolset: cache invalidated for %s",
            getattr(self._connection_params, "url", "?"),
        )
