"""
Unit tests for agent.caching_mcp_toolset — CachingMCPToolset.

Tests the caching behavior, lock safety, invalidation, and logging
of the MCPToolset wrapper that avoids redundant HTTP calls.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from agent.caching_mcp_toolset import CachingMCPToolset


def _make_mock_tool(name: str) -> MagicMock:
    """Create a mock BaseTool with a .name attribute."""
    tool = MagicMock()
    tool.name = name
    return tool


@pytest.fixture
def toolset():
    """Return a CachingMCPToolset with mocked parent get_tools()."""
    with patch.object(CachingMCPToolset, "__init__", lambda self, **kw: None):
        ts = CachingMCPToolset()
        ts._cached_tools = None
        ts._cache_lock = asyncio.Lock()
        ts._connection_params = MagicMock(url="http://localhost:8999/mcp/")
    return ts


class TestGetToolsCaching:

    @pytest.mark.asyncio
    async def test_first_call_delegates_to_super(self, toolset):
        tools = [_make_mock_tool("tool_a"), _make_mock_tool("tool_b")]
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", new_callable=AsyncMock, return_value=tools):
            result = await toolset.get_tools()
        assert result == tools
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_second_call_returns_cached(self, toolset):
        tools = [_make_mock_tool("tool_a")]
        mock_super = AsyncMock(return_value=tools)
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", mock_super):
            first = await toolset.get_tools()
            second = await toolset.get_tools()
        assert first is second
        assert mock_super.call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_cache_survives_multiple_calls(self, toolset):
        tools = [_make_mock_tool("x")]
        mock_super = AsyncMock(return_value=tools)
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", mock_super):
            for _ in range(10):
                result = await toolset.get_tools()
            assert result == tools
            assert mock_super.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_list_of_base_tools(self, toolset):
        tools = [_make_mock_tool("a"), _make_mock_tool("b"), _make_mock_tool("c")]
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", new_callable=AsyncMock, return_value=tools):
            result = await toolset.get_tools()
        assert isinstance(result, list)
        assert all(hasattr(t, "name") for t in result)

    @pytest.mark.asyncio
    async def test_passes_readonly_context(self, toolset):
        ctx = MagicMock()
        mock_super = AsyncMock(return_value=[])
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", mock_super):
            await toolset.get_tools(readonly_context=ctx)
        mock_super.assert_called_once_with(ctx)


class TestInvalidateCache:

    @pytest.mark.asyncio
    async def test_invalidate_forces_refetch(self, toolset):
        tools_v1 = [_make_mock_tool("v1")]
        tools_v2 = [_make_mock_tool("v2")]
        call_count = 0

        async def mock_get_tools(ctx=None):
            nonlocal call_count
            call_count += 1
            return tools_v1 if call_count == 1 else tools_v2

        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", side_effect=mock_get_tools):
            first = await toolset.get_tools()
            assert first[0].name == "v1"

            toolset.invalidate_cache()
            assert toolset._cached_tools is None

            second = await toolset.get_tools()
            assert second[0].name == "v2"
        assert call_count == 2

    def test_invalidate_sets_none(self, toolset):
        toolset._cached_tools = [_make_mock_tool("x")]
        toolset.invalidate_cache()
        assert toolset._cached_tools is None

    def test_invalidate_idempotent(self, toolset):
        toolset.invalidate_cache()
        toolset.invalidate_cache()
        assert toolset._cached_tools is None


class TestConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_get_tools_calls_super_once(self, toolset):
        """Multiple concurrent get_tools() should only trigger one HTTP call."""
        call_count = 0

        async def slow_get_tools(ctx=None):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # Simulate network delay
            return [_make_mock_tool("tool")]

        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", side_effect=slow_get_tools):
            results = await asyncio.gather(
                toolset.get_tools(),
                toolset.get_tools(),
                toolset.get_tools(),
            )
        # All results should be the same cached list
        assert all(r == results[0] for r in results)
        assert call_count == 1  # Lock ensures only one actual call


class TestLogging:

    @pytest.mark.asyncio
    async def test_logs_cached_tool_count(self, toolset, caplog):
        tools = [_make_mock_tool("a"), _make_mock_tool("b")]
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", new_callable=AsyncMock, return_value=tools):
            import logging
            with caplog.at_level(logging.INFO):
                await toolset.get_tools()
        assert any("cached 2 tools" in r.message for r in caplog.records)

    def test_logs_invalidation(self, toolset, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            toolset.invalidate_cache()
        assert any("cache invalidated" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_logs_server_url(self, toolset, caplog):
        tools = [_make_mock_tool("x")]
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", new_callable=AsyncMock, return_value=tools):
            import logging
            with caplog.at_level(logging.INFO):
                await toolset.get_tools()
        assert any("localhost:8999" in r.message for r in caplog.records)


class TestConnectionParamsUrl:

    @pytest.mark.asyncio
    async def test_missing_url_uses_fallback(self):
        """When _connection_params has no url attr, log should show '?'."""
        with patch.object(CachingMCPToolset, "__init__", lambda self, **kw: None):
            ts = CachingMCPToolset()
            ts._cached_tools = None
            ts._cache_lock = asyncio.Lock()
            ts._connection_params = MagicMock(spec=[])  # no 'url' attribute

        tools = [_make_mock_tool("t")]
        with patch("agent.caching_mcp_toolset.MCPToolset.get_tools", new_callable=AsyncMock, return_value=tools):
            result = await ts.get_tools()
        assert result == tools
