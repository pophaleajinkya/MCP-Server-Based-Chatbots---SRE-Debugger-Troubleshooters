"""Unit tests for src/mcp_server/tools/wcnp.py

Each tool is a thin async wrapper over a service call.
Tests verify:
  - correct service function is called with correct args
  - success response has all required fields with correct values
  - error response is returned (not raised) when service throws
  - direction field is always set correctly
"""
import pytest
from unittest.mock import AsyncMock, patch


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_deps(count: int = 2) -> list:
    return [{"app_name": f"svc-{i}", "namespace": "ns", "tier": "T1"} for i in range(count)]


def _make_breakdown(upstream: int = 2, downstream: int = 0) -> dict:
    return {
        "database_only": upstream,
        "topology_only": 0,
        "both": 0,
        "total": upstream + downstream,
        "upstream_count": upstream,
        "downstream_count": downstream,
    }


# ─── list_apps_in_namespace ───────────────────────────────────────────────────

class TestListAppsInNamespace:
    """Tests for the list_apps_in_namespace MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_service_result_unchanged(self):
        """Tool should forward the get_apps_for_namespace result as-is."""
        expected = {"apps": ["app-a", "app-b"], "namespace": "prod"}

        with patch(
            "src.mcp_server.tools.wcnp.get_apps_for_namespace",
            new=AsyncMock(return_value=expected),
        ):
            from src.mcp_server.tools.wcnp import list_apps_in_namespace
            result = await list_apps_in_namespace("prod")

        assert result == expected

    @pytest.mark.asyncio
    async def test_calls_service_with_correct_namespace(self):
        """Tool must pass the namespace argument to the underlying service."""
        mock_fn = AsyncMock(return_value={"apps": []})

        with patch("src.mcp_server.tools.wcnp.get_apps_for_namespace", new=mock_fn):
            from src.mcp_server.tools.wcnp import list_apps_in_namespace
            await list_apps_in_namespace("atlas-inventory-crons")

        mock_fn.assert_awaited_once_with("atlas-inventory-crons")


# ─── fetch_wcnp_upstream_dependencies ────────────────────────────────────────

class TestFetchWcnpUpstreamDependencies:
    """Tests for the fetch_wcnp_upstream_dependencies MCP tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        """On success all required response keys must be present with correct values."""
        upstream = _make_deps(3)
        breakdown = _make_breakdown(upstream=3)

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=(upstream, [], breakdown)),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("iro-prod", "item-assembler-async")

        assert result["status"] == "success"
        assert result["app_name"] == "iro-prod"
        assert result["namespace"] == "item-assembler-async"
        assert result["direction"] == "upstream"
        assert result["dependencies"] == upstream
        assert result["source_breakdown"] == breakdown
        assert result["total_count"] == 3
        assert "Found 3 upstream" in result["message"]

    @pytest.mark.asyncio
    async def test_calls_merge_service_with_upstream_direction(self):
        """Must request direction='upstream' from the merge service."""
        mock_fn = AsyncMock(return_value=([], [], {}))

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=mock_fn,
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            await fetch_wcnp_upstream_dependencies("my-app", "my-ns")

        mock_fn.assert_awaited_once_with("my-app", "my-ns", direction="upstream")

    @pytest.mark.asyncio
    async def test_error_response_on_service_exception(self):
        """When the service throws, the tool must return an error dict (not reraise)."""
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=RuntimeError("SRE-OPS unavailable")),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("iro-prod", "item-assembler-async")

        assert result["status"] == "error"
        assert result["app_name"] == "iro-prod"
        assert result["namespace"] == "item-assembler-async"
        assert result["direction"] == "upstream"
        assert result["dependencies"] == []
        assert result["total_count"] == 0
        assert "SRE-OPS unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_zero_upstream_deps_is_success(self):
        """Zero dependencies is a valid success — not an error."""
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=([], [], {})),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("orphan-app", "prod")

        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert result["dependencies"] == []

    @pytest.mark.asyncio
    async def test_total_count_matches_dependencies_length(self):
        """total_count must always equal len(dependencies)."""
        upstream = _make_deps(5)

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=(upstream, [], {})),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("app", "ns")

        assert result["total_count"] == len(result["dependencies"])


# ─── fetch_wcnp_downstream_dependencies ──────────────────────────────────────

class TestFetchWcnpDownstreamDependencies:
    """Tests for the fetch_wcnp_downstream_dependencies MCP tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        """On success all required response keys must be present with correct values."""
        downstream = _make_deps(2)
        breakdown = _make_breakdown(upstream=0, downstream=2)

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=([], downstream, breakdown)),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("iro-prod", "item-assembler-async")

        assert result["status"] == "success"
        assert result["direction"] == "downstream"
        assert result["dependencies"] == downstream
        assert result["total_count"] == 2
        assert "Found 2 downstream" in result["message"]

    @pytest.mark.asyncio
    async def test_calls_merge_service_with_downstream_direction(self):
        """Must request direction='downstream' from the merge service."""
        mock_fn = AsyncMock(return_value=([], [], {}))

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=mock_fn,
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            await fetch_wcnp_downstream_dependencies("my-app", "my-ns")

        mock_fn.assert_awaited_once_with("my-app", "my-ns", direction="downstream")

    @pytest.mark.asyncio
    async def test_error_response_on_service_exception(self):
        """When the service throws, the tool must return an error dict (not reraise)."""
        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(side_effect=ConnectionError("timeout")),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("app", "ns")

        assert result["status"] == "error"
        assert result["direction"] == "downstream"
        assert result["dependencies"] == []
        assert result["total_count"] == 0
        assert "timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_downstream_uses_second_element_of_tuple(self):
        """Tool must unpack the DOWNSTREAM (index 1) element, not upstream."""
        upstream_only = [{"app_name": "wrong-caller"}]
        downstream_only = [{"app_name": "correct-callee"}]

        with patch(
            "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies",
            new=AsyncMock(return_value=(upstream_only, downstream_only, {})),
        ):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("app", "ns")

        assert result["dependencies"] == downstream_only
        assert result["dependencies"][0]["app_name"] == "correct-callee"
