"""Unit tests for src/services/sre_ops_service.py"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from src.services.sre_ops_service import (
    _extract_deps,
    _get,
    fetch_downstream_dependencies,
    fetch_upstream_dependencies,
    fetch_oneops_downstream_dependencies,
    fetch_oneops_upstream_dependencies,
    fetch_managed_service_upstream_dependencies,
)


class TestExtractDeps:
    """Tests for _extract_deps helper function."""

    def test_extract_deps_from_list_preserves_all_fields(self):
        """Test that raw SRE-OPS fields are preserved as-is."""
        data = [
            {
                "source": "db",
                "type": "wcnp",
                "application_id": 7078,
                "application_name": "item-assembler-async::iro-prod",
                "namespace": "item-assembler-async",
                "app_name": "iro-prod",
                "wcnp_id": 8637,
                "managed_service_id": None,
                "tier": "T0",
                "dns": None,
            },
        ]
        result = _extract_deps(data, "upstream")

        assert len(result) == 1
        dep = result[0]
        # All original fields must survive unchanged
        assert dep["source"] == "db"
        assert dep["type"] == "wcnp"
        assert dep["application_id"] == 7078
        assert dep["application_name"] == "item-assembler-async::iro-prod"
        assert dep["namespace"] == "item-assembler-async"
        assert dep["app_name"] == "iro-prod"
        assert dep["wcnp_id"] == 8637
        assert dep["managed_service_id"] is None   # nulls kept
        assert dep["tier"] == "T0"
        assert dep["dns"] is None                  # nulls kept
        # Only addition is direction
        assert dep["direction"] == "upstream"

    def test_extract_deps_direction_downstream(self):
        """Test direction field is set to downstream."""
        data = [{"source": "db", "type": "wcnp", "app_name": "svc"}]
        result = _extract_deps(data, "downstream")
        assert result[0]["direction"] == "downstream"

    def test_extract_deps_does_not_mutate_original(self):
        """Test that the original dicts are not mutated."""
        original = {"source": "db", "app_name": "svc"}
        data = [original]
        _extract_deps(data, "upstream")
        assert "direction" not in original

    def test_extract_deps_from_list(self):
        """Test extracting dependencies from a list."""
        data = [
            {"source": "db", "namespace": "ns1", "app_name": "app1"},
            {"source": "topology", "namespace": "ns2", "app_name": "app2"},
        ]
        result = _extract_deps(data, "upstream")

        assert len(result) == 2
        assert result[0]["app_name"] == "app1"
        assert result[1]["app_name"] == "app2"
        assert all(dep["direction"] == "upstream" for dep in result)

    def test_extract_deps_from_dict_with_dependencies_key(self):
        """Test extracting from dict with 'dependencies' key."""
        data = {
            "dependencies": [
                {"source": "db", "namespace": "ns1", "app_name": "app1"},
            ]
        }
        result = _extract_deps(data, "downstream")

        assert len(result) == 1
        assert result[0]["direction"] == "downstream"

    def test_extract_deps_empty_list(self):
        """Test extracting from empty list."""
        result = _extract_deps([], "upstream")
        assert result == []

    def test_extract_deps_empty_dict(self):
        """Test extracting from empty dict."""
        result = _extract_deps({}, "upstream")
        assert result == []

    def test_extract_deps_non_dict_items_filtered(self):
        """Test that non-dict items are filtered out."""
        data = [
            {"source": "db", "app_name": "valid"},
            "invalid-string",
            123,
            None,
            {"source": "topology", "app_name": "valid2"},
        ]
        result = _extract_deps(data, "upstream")

        assert len(result) == 2

    def test_extract_deps_invalid_data_type(self):
        """Test extracting from invalid data type returns empty list."""
        result = _extract_deps("invalid string", "upstream")
        assert result == []

        result = _extract_deps(123, "upstream")
        assert result == []

        result = _extract_deps(None, "upstream")
        assert result == []


class TestGetHelper:
    """Tests for _get async helper function."""

    @pytest.mark.asyncio
    async def test_get_success(self):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{"name": "test"}]
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get("http://test.com/api", {"param": "value"}, "test-label")
            
            assert result == [{"name": "test"}]
            mock_instance.get.assert_called_once_with("http://test.com/api", params={"param": "value"})

    @pytest.mark.asyncio
    async def test_get_connect_error(self):
        """Test GET request with connection error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("Connection failed")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get("http://test.com/api", {}, "test-label")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_http_status_error(self):
        """Test GET request with HTTP status error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.HTTPStatusError(
                "Server error", 
                request=MagicMock(), 
                response=mock_response
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get("http://test.com/api", {}, "test-label")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_generic_exception(self):
        """Test GET request with generic exception."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Unexpected error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get("http://test.com/api", {}, "test-label")
            
            assert result == []


class TestFetchDownstreamDependencies:
    """Tests for fetch_downstream_dependencies function."""

    @pytest.mark.asyncio
    async def test_fetch_downstream_success(self):
        """Test successful downstream dependencies fetch."""
        mock_data = [
            {"name": "service1", "namespace": "ns1", "app_name": "app1"},
            {"name": "service2", "namespace": "ns2", "app_name": "app2"},
        ]
        
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetch_downstream_dependencies("my-app", "my-namespace")
            
            assert len(result) == 2
            assert all(dep["direction"] == "downstream" for dep in result)
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_downstream_empty_result(self):
        """Test downstream fetch with empty result."""
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            
            result = await fetch_downstream_dependencies("my-app", "my-namespace")
            
            assert result == []


class TestFetchUpstreamDependencies:
    """Tests for fetch_upstream_dependencies function."""

    @pytest.mark.asyncio
    async def test_fetch_upstream_success(self):
        """Test successful upstream dependencies fetch."""
        mock_data = [
            {"name": "upstream1", "namespace": "ns1", "app_name": "up-app1"},
        ]
        
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetch_upstream_dependencies("my-app", "my-namespace")
            
            assert len(result) == 1
            assert result[0]["direction"] == "upstream"

    @pytest.mark.asyncio
    async def test_fetch_upstream_empty_result(self):
        """Test upstream fetch with empty result."""
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            
            result = await fetch_upstream_dependencies("my-app", "my-namespace")
            
            assert result == []


class TestFetchOneOpsDownstreamDependencies:
    """Tests for fetch_oneops_downstream_dependencies function."""

    @pytest.mark.asyncio
    async def test_fetch_oneops_downstream_success(self):
        """Test successful OneOps downstream fetch."""
        mock_data = [
            {"name": "oneops-service", "namespace": "oneops-ns", "app_name": "oneops-app"},
        ]
        
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetch_oneops_downstream_dependencies("mexicoecomm", "rmsag2", "mx-rms")
            
            assert len(result) == 1
            assert result[0]["direction"] == "downstream"
            # Verify correct params were passed
            call_args = mock_get.call_args
            assert call_args[0][1] == {"org": "mexicoecomm", "platform": "rmsag2", "assembly": "mx-rms"}


class TestFetchOneOpsUpstreamDependencies:
    """Tests for fetch_oneops_upstream_dependencies function."""

    @pytest.mark.asyncio
    async def test_fetch_oneops_upstream_success(self):
        """Test successful OneOps upstream fetch."""
        mock_data = [
            {"name": "oneops-upstream", "namespace": "oneops-ns", "app_name": "up-oneops"},
        ]
        
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetch_oneops_upstream_dependencies("walmart-ecomm", "pay-platform", "payments-prod")
            
            assert len(result) == 1
            assert result[0]["direction"] == "upstream"


class TestFetchManagedServiceUpstreamDependencies:
    """Tests for fetch_managed_service_upstream_dependencies function."""

    @pytest.mark.asyncio
    async def test_fetch_cassandra_dependencies(self):
        """Test fetching Cassandra managed service dependencies."""
        mock_data = [
            {"name": "cassandra-dep", "namespace": "data-ns", "app_name": "cassandra-service"},
        ]
        params = {
            "assembly": "mx-rms",
            "platform": "rmsag2",
            "serviceType": "cassandra"
        }
        
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetch_managed_service_upstream_dependencies(params)
            
            assert len(result) == 1
            assert result[0]["direction"] == "upstream"

    @pytest.mark.asyncio
    async def test_fetch_cosmos_dependencies(self):
        """Test fetching Cosmos managed service dependencies."""
        mock_data = [
            {"name": "cosmos-dep", "namespace": "azure-ns", "app_name": "cosmos-service"},
        ]
        params = {
            "resourceGroup": "my-rg",
            "subscriptionId": "sub-123",
            "databaseName": "orders-db",
            "serviceType": "cosmos"
        }
        
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            
            result = await fetch_managed_service_upstream_dependencies(params)
            
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_managed_service_empty_result(self):
        """Test managed service fetch with empty result."""
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            
            result = await fetch_managed_service_upstream_dependencies({"serviceType": "cassandra"})
            
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_managed_service_unknown_type(self):
        """Test managed service fetch with unknown service type."""
        with patch("src.services.sre_ops_service._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            
            result = await fetch_managed_service_upstream_dependencies({"serviceType": "unknown"})
            
            assert result == []
