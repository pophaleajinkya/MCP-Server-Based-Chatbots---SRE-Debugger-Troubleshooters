"""Unit tests for src/mcp_server/tools/oneops.py

Each tool is a thin async wrapper over the SRE-OPS service.
Tests verify:
  - correct aliased service function is called with correct args
  - success response has all required fields with correct values
  - error response is returned (not raised) when service throws
  - direction field is always set correctly for each tool
"""
import pytest
from unittest.mock import AsyncMock, patch


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_oneops_deps(count: int = 2, direction: str = "upstream") -> list:
    return [
        {
            "app_name": f"svc-{i}",
            "namespace": "assembly-prod",
            "tier": "T1",
            "direction": direction,
        }
        for i in range(count)
    ]


# ─── fetch_oneops_upstream_dependencies ──────────────────────────────────────

class TestFetchOneopsUpstreamDependencies:
    """Tests for the fetch_oneops_upstream_dependencies MCP tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        """On success all required response keys must be present with correct values."""
        upstream = _make_oneops_deps(3, "upstream")

        with patch(
            "src.mcp_server.tools.oneops._svc_upstream",
            new=AsyncMock(return_value=upstream),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies(
                org="mexicoecomm", platform="rmsag2", assembly="mx-rms"
            )

        assert result["status"] == "success"
        assert result["org"] == "mexicoecomm"
        assert result["platform"] == "rmsag2"
        assert result["assembly"] == "mx-rms"
        assert result["direction"] == "upstream"
        assert result["dependencies"] == upstream
        assert result["total_count"] == 3
        assert "3 upstream" in result["message"]

    @pytest.mark.asyncio
    async def test_calls_svc_upstream_with_correct_args(self):
        """Must call _svc_upstream (not _svc_downstream) with the right params."""
        mock_upstream = AsyncMock(return_value=[])

        with patch("src.mcp_server.tools.oneops._svc_upstream", new=mock_upstream):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            await fetch_oneops_upstream_dependencies(
                org="walmart-ecomm", platform="pay-platform", assembly="payments-prod"
            )

        mock_upstream.assert_awaited_once_with("walmart-ecomm", "pay-platform", "payments-prod")

    @pytest.mark.asyncio
    async def test_error_response_on_service_exception(self):
        """When service throws, tool must return an error dict (not reraise)."""
        with patch(
            "src.mcp_server.tools.oneops._svc_upstream",
            new=AsyncMock(side_effect=RuntimeError("SRE-OPS 503")),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies(
                org="org", platform="plat", assembly="asm"
            )

        assert result["status"] == "error"
        assert result["org"] == "org"
        assert result["platform"] == "plat"
        assert result["assembly"] == "asm"
        assert result["direction"] == "upstream"
        assert result["dependencies"] == []
        assert result["total_count"] == 0
        assert "SRE-OPS 503" in result["error"]

    @pytest.mark.asyncio
    async def test_zero_upstream_deps_is_success(self):
        """Empty upstream is a valid success — not an error."""
        with patch(
            "src.mcp_server.tools.oneops._svc_upstream",
            new=AsyncMock(return_value=[]),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("o", "p", "a")

        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert result["dependencies"] == []

    @pytest.mark.asyncio
    async def test_total_count_matches_dependencies_length(self):
        """total_count must equal len(dependencies)."""
        deps = _make_oneops_deps(4, "upstream")

        with patch(
            "src.mcp_server.tools.oneops._svc_upstream",
            new=AsyncMock(return_value=deps),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("o", "p", "a")

        assert result["total_count"] == len(result["dependencies"])


# ─── fetch_oneops_downstream_dependencies ────────────────────────────────────

class TestFetchOneopsDownstreamDependencies:
    """Tests for the fetch_oneops_downstream_dependencies MCP tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        """On success all required response keys must be present with correct values."""
        downstream = _make_oneops_deps(2, "downstream")

        with patch(
            "src.mcp_server.tools.oneops._svc_downstream",
            new=AsyncMock(return_value=downstream),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            result = await fetch_oneops_downstream_dependencies(
                org="mexicoecomm", platform="rmsag2", assembly="mx-rms"
            )

        assert result["status"] == "success"
        assert result["direction"] == "downstream"
        assert result["dependencies"] == downstream
        assert result["total_count"] == 2
        assert "2 downstream" in result["message"]

    @pytest.mark.asyncio
    async def test_calls_svc_downstream_with_correct_args(self):
        """Must call _svc_downstream (not _svc_upstream) with the right params."""
        mock_downstream = AsyncMock(return_value=[])

        with patch("src.mcp_server.tools.oneops._svc_downstream", new=mock_downstream):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            await fetch_oneops_downstream_dependencies(
                org="walmart-ecomm", platform="pay-platform", assembly="payments-prod"
            )

        mock_downstream.assert_awaited_once_with("walmart-ecomm", "pay-platform", "payments-prod")

    @pytest.mark.asyncio
    async def test_does_not_call_upstream_service(self):
        """Downstream tool must NOT call _svc_upstream."""
        mock_upstream = AsyncMock(return_value=[])
        mock_downstream = AsyncMock(return_value=[])

        with (
            patch("src.mcp_server.tools.oneops._svc_upstream", new=mock_upstream),
            patch("src.mcp_server.tools.oneops._svc_downstream", new=mock_downstream),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            await fetch_oneops_downstream_dependencies("o", "p", "a")

        mock_upstream.assert_not_awaited()
        mock_downstream.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_response_on_service_exception(self):
        """When service throws, tool must return an error dict (not reraise)."""
        with patch(
            "src.mcp_server.tools.oneops._svc_downstream",
            new=AsyncMock(side_effect=ConnectionError("timeout")),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            result = await fetch_oneops_downstream_dependencies("o", "p", "a")

        assert result["status"] == "error"
        assert result["direction"] == "downstream"
        assert result["dependencies"] == []
        assert "timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_upstream_tool_does_not_call_downstream_service(self):
        """Upstream tool must NOT call _svc_downstream."""
        mock_upstream = AsyncMock(return_value=[])
        mock_downstream = AsyncMock(return_value=[])

        with (
            patch("src.mcp_server.tools.oneops._svc_upstream", new=mock_upstream),
            patch("src.mcp_server.tools.oneops._svc_downstream", new=mock_downstream),
        ):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            await fetch_oneops_upstream_dependencies("o", "p", "a")

        mock_downstream.assert_not_awaited()
        mock_upstream.assert_awaited_once()
