"""Unit tests for src/mcp_server/tools/managed_service.py

Four separate upstream-only tools, one per service type.
Tests verify:
  - each tool calls fetch_managed_service_upstream_dependencies with correct params
  - serviceType field in params matches the tool
  - success response has correct structure including direction='upstream'
  - error response is returned (not raised) on exception
  - the shared _fetch helper constructs params correctly for each service type
"""
import pytest
from unittest.mock import AsyncMock, patch


# ─── helpers ──────────────────────────────────────────────────────────────────

_SVC_PATH = "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies"


def _make_deps(count: int = 2) -> list:
    return [{"app_name": f"caller-{i}", "tier": "T1"} for i in range(count)]


# ─── fetch_cassandra_upstream_dependencies ────────────────────────────────────

class TestFetchCassandraUpstreamDependencies:
    """Tests for the Cassandra upstream tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        deps = _make_deps(2)
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            from src.mcp_server.tools.managed_service import fetch_cassandra_upstream_dependencies
            result = await fetch_cassandra_upstream_dependencies(
                assembly="mx-rms", platform="rmsag2"
            )

        assert result["status"] == "success"
        assert result["service_type"] == "cassandra"
        assert result["direction"] == "upstream"
        assert result["dependencies"] == deps
        assert result["total_count"] == 2
        assert "cassandra" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self):
        """Cassandra tool must send assembly, platform, and serviceType='cassandra'."""
        mock_svc = AsyncMock(return_value=[])
        with patch(_SVC_PATH, new=mock_svc):
            from src.mcp_server.tools.managed_service import fetch_cassandra_upstream_dependencies
            await fetch_cassandra_upstream_dependencies(assembly="mx-rms", platform="rmsag2")

        called_params = mock_svc.call_args[0][0]
        assert called_params["assembly"] == "mx-rms"
        assert called_params["platform"] == "rmsag2"
        assert called_params["serviceType"] == "cassandra"

    @pytest.mark.asyncio
    async def test_error_response_on_exception(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("cassandra down"))):
            from src.mcp_server.tools.managed_service import fetch_cassandra_upstream_dependencies
            result = await fetch_cassandra_upstream_dependencies(
                assembly="mx-rms", platform="rmsag2"
            )

        assert result["status"] == "error"
        assert result["service_type"] == "cassandra"
        assert result["direction"] == "upstream"
        assert result["dependencies"] == []
        assert result["total_count"] == 0
        assert "cassandra down" in result["error"]


# ─── fetch_meghacache_upstream_dependencies ───────────────────────────────────

class TestFetchMeghacacheUpstreamDependencies:
    """Tests for the MeghaCache upstream tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        deps = _make_deps(1)
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            from src.mcp_server.tools.managed_service import fetch_meghacache_upstream_dependencies
            result = await fetch_meghacache_upstream_dependencies(
                assembly="payments-prod", platform="pay-platform"
            )

        assert result["status"] == "success"
        assert result["service_type"] == "meghacache"
        assert result["direction"] == "upstream"
        assert result["total_count"] == 1

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self):
        """MeghaCache tool must send assembly, platform, and serviceType='meghacache'."""
        mock_svc = AsyncMock(return_value=[])
        with patch(_SVC_PATH, new=mock_svc):
            from src.mcp_server.tools.managed_service import fetch_meghacache_upstream_dependencies
            await fetch_meghacache_upstream_dependencies(
                assembly="payments-prod", platform="pay-platform"
            )

        called_params = mock_svc.call_args[0][0]
        assert called_params["assembly"] == "payments-prod"
        assert called_params["platform"] == "pay-platform"
        assert called_params["serviceType"] == "meghacache"

    @pytest.mark.asyncio
    async def test_error_response_on_exception(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=ConnectionError("network error"))):
            from src.mcp_server.tools.managed_service import fetch_meghacache_upstream_dependencies
            result = await fetch_meghacache_upstream_dependencies("asm", "plat")

        assert result["status"] == "error"
        assert result["service_type"] == "meghacache"
        assert "network error" in result["error"]


# ─── fetch_cosmos_upstream_dependencies ──────────────────────────────────────

class TestFetchCosmosUpstreamDependencies:
    """Tests for the Cosmos DB upstream tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        deps = _make_deps(3)
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            from src.mcp_server.tools.managed_service import fetch_cosmos_upstream_dependencies
            result = await fetch_cosmos_upstream_dependencies(
                resource_group="my-rg",
                subscription_id="sub-123",
                database_name="orders-db",
            )

        assert result["status"] == "success"
        assert result["service_type"] == "cosmos"
        assert result["direction"] == "upstream"
        assert result["total_count"] == 3

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self):
        """Cosmos tool must map snake_case args to camelCase params + serviceType='cosmos'."""
        mock_svc = AsyncMock(return_value=[])
        with patch(_SVC_PATH, new=mock_svc):
            from src.mcp_server.tools.managed_service import fetch_cosmos_upstream_dependencies
            await fetch_cosmos_upstream_dependencies(
                resource_group="my-rg",
                subscription_id="sub-123",
                database_name="orders-db",
            )

        called_params = mock_svc.call_args[0][0]
        assert called_params["resourceGroup"] == "my-rg"
        assert called_params["subscriptionId"] == "sub-123"
        assert called_params["databaseName"] == "orders-db"
        assert called_params["serviceType"] == "cosmos"

    @pytest.mark.asyncio
    async def test_error_response_on_exception(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=ValueError("bad request"))):
            from src.mcp_server.tools.managed_service import fetch_cosmos_upstream_dependencies
            result = await fetch_cosmos_upstream_dependencies("rg", "sub", "db")

        assert result["status"] == "error"
        assert result["service_type"] == "cosmos"
        assert result["direction"] == "upstream"
        assert "bad request" in result["error"]


# ─── fetch_sqlserver_upstream_dependencies ────────────────────────────────────

class TestFetchSqlserverUpstreamDependencies:
    """Tests for the SQL Server upstream tool."""

    @pytest.mark.asyncio
    async def test_success_response_shape(self):
        deps = _make_deps(4)
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            from src.mcp_server.tools.managed_service import fetch_sqlserver_upstream_dependencies
            result = await fetch_sqlserver_upstream_dependencies(
                resource_group="prod-rg",
                subscription_id="abc-456",
                database_name="inventory-db",
            )

        assert result["status"] == "success"
        assert result["service_type"] == "sqlserver"
        assert result["direction"] == "upstream"
        assert result["total_count"] == 4

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self):
        """SQL Server tool must map snake_case args to camelCase params + serviceType='sqlserver'."""
        mock_svc = AsyncMock(return_value=[])
        with patch(_SVC_PATH, new=mock_svc):
            from src.mcp_server.tools.managed_service import fetch_sqlserver_upstream_dependencies
            await fetch_sqlserver_upstream_dependencies(
                resource_group="prod-rg",
                subscription_id="abc-456",
                database_name="inventory-db",
            )

        called_params = mock_svc.call_args[0][0]
        assert called_params["resourceGroup"] == "prod-rg"
        assert called_params["subscriptionId"] == "abc-456"
        assert called_params["databaseName"] == "inventory-db"
        assert called_params["serviceType"] == "sqlserver"

    @pytest.mark.asyncio
    async def test_error_response_on_exception(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=TimeoutError("timed out"))):
            from src.mcp_server.tools.managed_service import fetch_sqlserver_upstream_dependencies
            result = await fetch_sqlserver_upstream_dependencies("rg", "sub", "db")

        assert result["status"] == "error"
        assert result["service_type"] == "sqlserver"
        assert "timed out" in result["error"]


# ─── All managed service tools: direction field ───────────────────────────────

class TestManagedServiceDirectionField:
    """All managed service tools must always return direction='upstream'."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,kwargs", [
        ("fetch_cassandra_upstream_dependencies", {"assembly": "a", "platform": "p"}),
        ("fetch_meghacache_upstream_dependencies", {"assembly": "a", "platform": "p"}),
        ("fetch_cosmos_upstream_dependencies", {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
        ("fetch_sqlserver_upstream_dependencies", {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
    ])
    async def test_direction_is_always_upstream(self, tool_name, kwargs):
        import importlib
        module = importlib.import_module("src.mcp_server.tools.managed_service")
        tool_fn = getattr(module, tool_name)

        with patch(_SVC_PATH, new=AsyncMock(return_value=[])):
            result = await tool_fn(**kwargs)

        assert result["direction"] == "upstream", (
            f"{tool_name} must always return direction='upstream'"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,kwargs", [
        ("fetch_cassandra_upstream_dependencies", {"assembly": "a", "platform": "p"}),
        ("fetch_meghacache_upstream_dependencies", {"assembly": "a", "platform": "p"}),
        ("fetch_cosmos_upstream_dependencies", {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
        ("fetch_sqlserver_upstream_dependencies", {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
    ])
    async def test_error_direction_is_always_upstream(self, tool_name, kwargs):
        """Even in error path, direction must be 'upstream'."""
        import importlib
        module = importlib.import_module("src.mcp_server.tools.managed_service")
        tool_fn = getattr(module, tool_name)

        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("fail"))):
            result = await tool_fn(**kwargs)

        assert result["direction"] == "upstream"
        assert result["status"] == "error"
