"""Response contract tests — all 9 MCP tools must return the required keys.

Strategy:
  - For each tool, assert EVERY expected key is present in both success and error paths
  - Assert types of key values
  - Assert consistent invariants across all tools:
      * status is always "success" or "error"
      * direction is always a string
      * dependencies is always a list
      * total_count is always a non-negative int

These tests guard against accidental removal of fields that client LLMs rely on.
"""
import pytest
from unittest.mock import AsyncMock, patch

_SVC_MANAGED = "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies"
_SVC_WCNP_MERGE = "src.mcp_server.tools.wcnp.get_upstream_and_downstream_dependencies"
_SVC_WCNP_LIST = "src.mcp_server.tools.wcnp.get_apps_for_namespace"
_SVC_ONEOPS_UP = "src.mcp_server.tools.oneops._svc_upstream"
_SVC_ONEOPS_DOWN = "src.mcp_server.tools.oneops._svc_downstream"

_SAMPLE_DEP = {"app_name": "caller-svc", "tier": "T1"}
_SAMPLE_BREAKDOWN = {"upstream_count": 1, "downstream_count": 0, "total": 1}


# ─── WCNP tools ───────────────────────────────────────────────────────────────

class TestWcnpUpstreamResponseContract:
    """fetch_wcnp_upstream_dependencies response must have all required keys."""

    @pytest.mark.asyncio
    async def test_success_has_all_required_keys(self):
        required = {"status", "app_name", "namespace", "direction", "dependencies",
                    "source_breakdown", "total_count", "message"}
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([_SAMPLE_DEP], [], _SAMPLE_BREAKDOWN))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("my-app", "my-ns")
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    @pytest.mark.asyncio
    async def test_error_has_all_required_keys(self):
        required = {"status", "app_name", "namespace", "direction", "dependencies",
                    "total_count", "error"}
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(side_effect=RuntimeError("fail"))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("my-app", "my-ns")
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    @pytest.mark.asyncio
    async def test_success_field_types(self):
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([_SAMPLE_DEP], [], _SAMPLE_BREAKDOWN))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("my-app", "my-ns")
        assert isinstance(result["status"], str)
        assert isinstance(result["app_name"], str)
        assert isinstance(result["namespace"], str)
        assert isinstance(result["direction"], str)
        assert isinstance(result["dependencies"], list)
        assert isinstance(result["total_count"], int)
        assert isinstance(result["message"], str)
        assert result["total_count"] >= 0

    @pytest.mark.asyncio
    async def test_direction_value_is_upstream(self):
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([], [], {}))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("app", "ns")
        assert result["direction"] == "upstream"


class TestWcnpDownstreamResponseContract:
    """fetch_wcnp_downstream_dependencies response must have all required keys."""

    @pytest.mark.asyncio
    async def test_success_has_all_required_keys(self):
        required = {"status", "app_name", "namespace", "direction", "dependencies",
                    "source_breakdown", "total_count", "message"}
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([], [_SAMPLE_DEP], _SAMPLE_BREAKDOWN))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("my-app", "my-ns")
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    @pytest.mark.asyncio
    async def test_direction_value_is_downstream(self):
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([], [], {}))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("app", "ns")
        assert result["direction"] == "downstream"

    @pytest.mark.asyncio
    async def test_error_has_required_keys(self):
        required = {"status", "app_name", "namespace", "direction", "dependencies",
                    "total_count", "error"}
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(side_effect=RuntimeError("fail"))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("my-app", "my-ns")
        assert required.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_total_count_always_equals_len_dependencies(self):
        deps = [{"app": f"svc-{i}"} for i in range(4)]
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([], deps, {}))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_downstream_dependencies
            result = await fetch_wcnp_downstream_dependencies("app", "ns")
        assert result["total_count"] == len(result["dependencies"]) == 4


# ─── OneOps tools ─────────────────────────────────────────────────────────────

class TestOneopsUpstreamResponseContract:
    """fetch_oneops_upstream_dependencies response must have all required keys."""

    @pytest.mark.asyncio
    async def test_success_has_all_required_keys(self):
        required = {"status", "org", "platform", "assembly", "direction",
                    "dependencies", "total_count", "message"}
        with patch(_SVC_ONEOPS_UP, new=AsyncMock(return_value=[_SAMPLE_DEP])):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("org", "plat", "asm")
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    @pytest.mark.asyncio
    async def test_error_has_all_required_keys(self):
        required = {"status", "org", "platform", "assembly", "direction",
                    "dependencies", "total_count", "error"}
        with patch(_SVC_ONEOPS_UP, new=AsyncMock(side_effect=RuntimeError("fail"))):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("org", "plat", "asm")
        assert required.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_direction_is_upstream(self):
        with patch(_SVC_ONEOPS_UP, new=AsyncMock(return_value=[])):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("o", "p", "a")
        assert result["direction"] == "upstream"

    @pytest.mark.asyncio
    async def test_success_field_types(self):
        with patch(_SVC_ONEOPS_UP, new=AsyncMock(return_value=[_SAMPLE_DEP])):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("org", "plat", "asm")
        assert isinstance(result["status"], str)
        assert isinstance(result["org"], str)
        assert isinstance(result["platform"], str)
        assert isinstance(result["assembly"], str)
        assert isinstance(result["direction"], str)
        assert isinstance(result["dependencies"], list)
        assert isinstance(result["total_count"], int)
        assert isinstance(result["message"], str)


class TestOneopsDownstreamResponseContract:
    """fetch_oneops_downstream_dependencies response must have all required keys."""

    @pytest.mark.asyncio
    async def test_success_has_all_required_keys(self):
        required = {"status", "org", "platform", "assembly", "direction",
                    "dependencies", "total_count", "message"}
        with patch(_SVC_ONEOPS_DOWN, new=AsyncMock(return_value=[_SAMPLE_DEP])):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            result = await fetch_oneops_downstream_dependencies("org", "plat", "asm")
        assert required.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_direction_is_downstream(self):
        with patch(_SVC_ONEOPS_DOWN, new=AsyncMock(return_value=[])):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            result = await fetch_oneops_downstream_dependencies("o", "p", "a")
        assert result["direction"] == "downstream"

    @pytest.mark.asyncio
    async def test_message_includes_count_and_direction(self):
        deps = [_SAMPLE_DEP, _SAMPLE_DEP]
        with patch(_SVC_ONEOPS_DOWN, new=AsyncMock(return_value=deps)):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            result = await fetch_oneops_downstream_dependencies("org", "plat", "asm")
        assert "2" in result["message"]
        assert "downstream" in result["message"].lower()


# ─── Managed service tools ────────────────────────────────────────────────────

class TestManagedServiceResponseContract:
    """All 4 managed service tools must return the required keys."""

    _REQUIRED_SUCCESS = {"status", "service_type", "direction", "dependencies",
                         "total_count", "message"}
    _REQUIRED_ERROR = {"status", "service_type", "direction", "dependencies",
                       "total_count", "error"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,kwargs,expected_stype", [
        ("fetch_cassandra_upstream_dependencies",
         {"assembly": "mx-rms", "platform": "rmsag2"}, "cassandra"),
        ("fetch_meghacache_upstream_dependencies",
         {"assembly": "pay-prod", "platform": "pay-plat"}, "meghacache"),
        ("fetch_cosmos_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}, "cosmos"),
        ("fetch_sqlserver_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}, "sqlserver"),
    ])
    async def test_success_has_all_required_keys(self, tool_name, kwargs, expected_stype):
        import importlib
        module = importlib.import_module("src.mcp_server.tools.managed_service")
        tool_fn = getattr(module, tool_name)

        with patch(_SVC_MANAGED, new=AsyncMock(return_value=[_SAMPLE_DEP])):
            result = await tool_fn(**kwargs)

        missing = self._REQUIRED_SUCCESS - result.keys()
        assert not missing, f"{tool_name} missing keys: {missing}"
        assert result["service_type"] == expected_stype
        assert result["direction"] == "upstream"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,kwargs", [
        ("fetch_cassandra_upstream_dependencies",
         {"assembly": "mx-rms", "platform": "rmsag2"}),
        ("fetch_meghacache_upstream_dependencies",
         {"assembly": "pay-prod", "platform": "pay-plat"}),
        ("fetch_cosmos_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
        ("fetch_sqlserver_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
    ])
    async def test_error_has_all_required_keys(self, tool_name, kwargs):
        import importlib
        module = importlib.import_module("src.mcp_server.tools.managed_service")
        tool_fn = getattr(module, tool_name)

        with patch(_SVC_MANAGED, new=AsyncMock(side_effect=RuntimeError("svc down"))):
            result = await tool_fn(**kwargs)

        missing = self._REQUIRED_ERROR - result.keys()
        assert not missing, f"{tool_name} error missing keys: {missing}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,kwargs", [
        ("fetch_cassandra_upstream_dependencies",
         {"assembly": "mx-rms", "platform": "rmsag2"}),
        ("fetch_meghacache_upstream_dependencies",
         {"assembly": "pay-prod", "platform": "pay-plat"}),
        ("fetch_cosmos_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
        ("fetch_sqlserver_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
    ])
    async def test_total_count_matches_dependencies_length(self, tool_name, kwargs):
        deps = [{"app": "x"}, {"app": "y"}, {"app": "z"}]
        import importlib
        module = importlib.import_module("src.mcp_server.tools.managed_service")
        tool_fn = getattr(module, tool_name)

        with patch(_SVC_MANAGED, new=AsyncMock(return_value=deps)):
            result = await tool_fn(**kwargs)

        assert result["total_count"] == len(result["dependencies"]) == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,kwargs", [
        ("fetch_cassandra_upstream_dependencies",
         {"assembly": "mx-rms", "platform": "rmsag2"}),
        ("fetch_meghacache_upstream_dependencies",
         {"assembly": "pay-prod", "platform": "pay-plat"}),
        ("fetch_cosmos_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
        ("fetch_sqlserver_upstream_dependencies",
         {"resource_group": "rg", "subscription_id": "sub", "database_name": "db"}),
    ])
    async def test_success_field_types(self, tool_name, kwargs):
        import importlib
        module = importlib.import_module("src.mcp_server.tools.managed_service")
        tool_fn = getattr(module, tool_name)

        with patch(_SVC_MANAGED, new=AsyncMock(return_value=[_SAMPLE_DEP])):
            result = await tool_fn(**kwargs)

        assert isinstance(result["status"], str)
        assert isinstance(result["service_type"], str)
        assert isinstance(result["direction"], str)
        assert isinstance(result["dependencies"], list)
        assert isinstance(result["total_count"], int)
        assert isinstance(result["message"], str)
        assert result["total_count"] >= 0


# ─── Cross-tool invariants ────────────────────────────────────────────────────

class TestCrossToolInvariants:
    """Universal invariants that hold for every MCP tool response."""

    @pytest.mark.asyncio
    async def test_status_is_always_success_or_error_wcnp_up(self):
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(return_value=([], [], {}))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("app", "ns")
        assert result["status"] in ("success", "error")

    @pytest.mark.asyncio
    async def test_status_is_always_success_or_error_oneops_down(self):
        with patch(_SVC_ONEOPS_DOWN, new=AsyncMock(return_value=[])):
            from src.mcp_server.tools.oneops import fetch_oneops_downstream_dependencies
            result = await fetch_oneops_downstream_dependencies("o", "p", "a")
        assert result["status"] in ("success", "error")

    @pytest.mark.asyncio
    async def test_status_is_always_success_or_error_managed(self):
        with patch(_SVC_MANAGED, new=AsyncMock(return_value=[])):
            from src.mcp_server.tools.managed_service import fetch_cassandra_upstream_dependencies
            result = await fetch_cassandra_upstream_dependencies("asm", "plat")
        assert result["status"] in ("success", "error")

    @pytest.mark.asyncio
    async def test_wcnp_app_name_echoed_in_error(self):
        """app_name must be echoed even in error response (so LLM knows which call failed)."""
        with patch(_SVC_WCNP_MERGE, new=AsyncMock(side_effect=RuntimeError("fail"))):
            from src.mcp_server.tools.wcnp import fetch_wcnp_upstream_dependencies
            result = await fetch_wcnp_upstream_dependencies("target-app", "prod-ns")
        assert result["app_name"] == "target-app"
        assert result["namespace"] == "prod-ns"

    @pytest.mark.asyncio
    async def test_oneops_params_echoed_in_error(self):
        """org/platform/assembly must be echoed in error response."""
        with patch(_SVC_ONEOPS_UP, new=AsyncMock(side_effect=RuntimeError("fail"))):
            from src.mcp_server.tools.oneops import fetch_oneops_upstream_dependencies
            result = await fetch_oneops_upstream_dependencies("my-org", "my-plat", "my-asm")
        assert result["org"] == "my-org"
        assert result["platform"] == "my-plat"
        assert result["assembly"] == "my-asm"
