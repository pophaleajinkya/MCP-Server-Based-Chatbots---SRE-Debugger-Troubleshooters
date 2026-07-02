"""Unit tests for the shared _fetch helper in src/mcp_server/tools/managed_service.py

The _fetch helper is the single implementation used by all 4 managed service tools.
Tests verify:
  - success path: correct dict shape, direction always 'upstream', total_count = len(deps)
  - error path: returns error dict (never raises), preserves service_type and direction
  - message field format for various counts (0, 1, many)
  - total_count consistency with dependencies list length
  - service_type is stored verbatim from caller
"""
import pytest
from unittest.mock import AsyncMock, patch

_SVC_PATH = "src.mcp_server.tools.managed_service.fetch_managed_service_upstream_dependencies"


async def _call_fetch(service_type: str, params: dict) -> dict:
    """Import and call _fetch directly."""
    from src.mcp_server.tools.managed_service import _fetch
    return await _fetch(service_type=service_type, params=params)


# ─── success path ─────────────────────────────────────────────────────────────

class TestFetchHelperSuccessPath:
    """Success path: valid service response."""

    @pytest.mark.asyncio
    async def test_returns_status_success(self):
        with patch(_SVC_PATH, new=AsyncMock(return_value=[{"app": "x"}])):
            result = await _call_fetch("cassandra", {"assembly": "a", "platform": "p", "serviceType": "cassandra"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_direction_is_always_upstream(self):
        with patch(_SVC_PATH, new=AsyncMock(return_value=[])):
            result = await _call_fetch("cosmos", {"resourceGroup": "rg", "subscriptionId": "sub", "databaseName": "db", "serviceType": "cosmos"})
        assert result["direction"] == "upstream"

    @pytest.mark.asyncio
    async def test_service_type_stored_verbatim(self):
        """service_type in response must match what was passed to _fetch."""
        for stype in ("cassandra", "meghacache", "cosmos", "sqlserver"):
            with patch(_SVC_PATH, new=AsyncMock(return_value=[])):
                result = await _call_fetch(stype, {"serviceType": stype})
            assert result["service_type"] == stype, f"service_type mismatch for {stype}"

    @pytest.mark.asyncio
    async def test_dependencies_list_is_passthrough(self):
        """dependencies in response must be exactly what the service returned."""
        deps = [{"app_name": "svc-a", "tier": "T1"}, {"app_name": "svc-b", "tier": "T2"}]
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            result = await _call_fetch("cassandra", {})
        assert result["dependencies"] == deps

    @pytest.mark.asyncio
    async def test_total_count_equals_len_dependencies(self):
        """total_count must always equal len(dependencies)."""
        deps = [{"app": f"svc-{i}"} for i in range(7)]
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            result = await _call_fetch("cassandra", {})
        assert result["total_count"] == 7
        assert result["total_count"] == len(result["dependencies"])

    @pytest.mark.asyncio
    async def test_zero_deps_is_valid_success(self):
        """Empty list is a valid success — not an error."""
        with patch(_SVC_PATH, new=AsyncMock(return_value=[])):
            result = await _call_fetch("meghacache", {})
        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert result["dependencies"] == []

    @pytest.mark.asyncio
    async def test_message_contains_service_type(self):
        """Success message must mention the service type."""
        with patch(_SVC_PATH, new=AsyncMock(return_value=[{"app": "x"}])):
            result = await _call_fetch("cosmos", {})
        assert "cosmos" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_message_contains_count(self):
        """Success message must include the dependency count."""
        deps = [{"app": "x"}, {"app": "y"}, {"app": "z"}]
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            result = await _call_fetch("sqlserver", {})
        assert "3" in result["message"]

    @pytest.mark.asyncio
    async def test_message_contains_upstream(self):
        """Success message must mention upstream."""
        with patch(_SVC_PATH, new=AsyncMock(return_value=[])):
            result = await _call_fetch("cassandra", {})
        assert "upstream" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_params_forwarded_to_service(self):
        """_fetch must pass params dict unchanged to the service function."""
        mock_svc = AsyncMock(return_value=[])
        params = {"assembly": "mx-rms", "platform": "rmsag2", "serviceType": "cassandra"}
        with patch(_SVC_PATH, new=mock_svc):
            await _call_fetch("cassandra", params)
        mock_svc.assert_awaited_once_with(params)

    @pytest.mark.asyncio
    async def test_large_dependency_list(self):
        """total_count must match for large lists."""
        deps = [{"app": f"svc-{i}"} for i in range(100)]
        with patch(_SVC_PATH, new=AsyncMock(return_value=deps)):
            result = await _call_fetch("cassandra", {})
        assert result["total_count"] == 100
        assert result["status"] == "success"


# ─── error path ───────────────────────────────────────────────────────────────

class TestFetchHelperErrorPath:
    """Error path: service raises an exception."""

    @pytest.mark.asyncio
    async def test_returns_status_error_on_exception(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("SRE-OPS 503"))):
            result = await _call_fetch("cassandra", {})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_error_direction_is_upstream(self):
        """Even in error path, direction must be 'upstream'."""
        with patch(_SVC_PATH, new=AsyncMock(side_effect=ConnectionError("timeout"))):
            result = await _call_fetch("cosmos", {})
        assert result["direction"] == "upstream"

    @pytest.mark.asyncio
    async def test_error_preserves_service_type(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=ValueError("bad params"))):
            result = await _call_fetch("sqlserver", {})
        assert result["service_type"] == "sqlserver"

    @pytest.mark.asyncio
    async def test_error_dependencies_is_empty_list(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("fail"))):
            result = await _call_fetch("meghacache", {})
        assert result["dependencies"] == []

    @pytest.mark.asyncio
    async def test_error_total_count_is_zero(self):
        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("fail"))):
            result = await _call_fetch("cassandra", {})
        assert result["total_count"] == 0

    @pytest.mark.asyncio
    async def test_error_message_is_stringified_exception(self):
        """Error field must be a string representation of the exception."""
        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("detailed error msg"))):
            result = await _call_fetch("cosmos", {})
        assert "detailed error msg" in result["error"]
        assert isinstance(result["error"], str)

    @pytest.mark.asyncio
    async def test_does_not_reraise_exception(self):
        """_fetch must never propagate exceptions — always returns a dict."""
        with patch(_SVC_PATH, new=AsyncMock(side_effect=Exception("critical failure"))):
            try:
                result = await _call_fetch("cassandra", {})
            except Exception as exc:
                pytest.fail(f"_fetch raised an exception instead of returning error dict: {exc}")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc_type,msg", [
        (RuntimeError, "runtime"),
        (ConnectionError, "connection"),
        (TimeoutError, "timed out"),
        (ValueError, "invalid value"),
        (KeyError, "missing key"),
        (Exception, "generic"),
    ])
    async def test_handles_various_exception_types(self, exc_type, msg):
        """_fetch must convert any exception type to an error dict."""
        with patch(_SVC_PATH, new=AsyncMock(side_effect=exc_type(msg))):
            result = await _call_fetch("cassandra", {})
        assert result["status"] == "error"
        assert msg in result["error"]

    @pytest.mark.asyncio
    async def test_error_response_has_no_message_key(self):
        """Error response should not have a 'message' key (only 'error')."""
        with patch(_SVC_PATH, new=AsyncMock(side_effect=RuntimeError("fail"))):
            result = await _call_fetch("cassandra", {})
        # error path uses 'error' key, not 'message'
        assert "error" in result
        assert "message" not in result

    @pytest.mark.asyncio
    async def test_success_response_has_no_error_key(self):
        """Success response should not have an 'error' key."""
        with patch(_SVC_PATH, new=AsyncMock(return_value=[])):
            result = await _call_fetch("cassandra", {})
        assert "error" not in result
        assert "message" in result
