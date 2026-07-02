"""Unit tests for src/services/merge_service.py"""
import pytest
from unittest.mock import AsyncMock, patch

from src.services.merge_service import (
    get_upstream_and_downstream_dependencies,
)


class TestGetUpstreamAndDownstreamDependencies:
    """Tests for get_upstream_and_downstream_dependencies function."""

    @pytest.mark.asyncio
    async def test_fetch_both_directions(self):
        """Test fetching both upstream and downstream dependencies."""
        upstream_data = [
            {"source": "db", "app_name": "upstream-service", "namespace": "prod", "wcnp_id": None, "direction": "upstream"}
        ]
        downstream_data = [
            {"source": "topology", "app_name": "downstream-service", "namespace": "prod", "tier": None, "direction": "downstream"}
        ]

        with patch("src.services.merge_service.fetch_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.services.merge_service.fetch_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = upstream_data
            mock_down.return_value = downstream_data

            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                "my-app", "my-namespace"
            )

            assert len(upstream) == 1
            assert len(downstream) == 1
            assert breakdown["upstream_count"] == 1
            assert breakdown["downstream_count"] == 1
            assert breakdown["total"] == 2
            # direction comes from _extract_deps, already set on mocked data
            assert upstream[0]["direction"] == "upstream"
            assert downstream[0]["direction"] == "downstream"
            # nulls are preserved (no stripping)
            assert upstream[0]["wcnp_id"] is None
            assert downstream[0]["tier"] is None

    @pytest.mark.asyncio
    async def test_fetch_upstream_only(self):
        """Test fetching upstream dependencies only."""
        upstream_data = [
            {"source": "db", "app_name": "upstream1", "namespace": "prod", "direction": "upstream"},
            {"source": "db", "app_name": "upstream2", "namespace": "prod", "direction": "upstream"},
        ]

        with patch("src.services.merge_service.fetch_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.services.merge_service.fetch_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = upstream_data

            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                "my-app", "my-namespace", direction="upstream"
            )

            assert len(upstream) == 2
            assert len(downstream) == 0
            assert breakdown["upstream_count"] == 2
            assert breakdown["downstream_count"] == 0
            mock_up.assert_called_once()
            mock_down.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_downstream_only(self):
        """Test fetching downstream dependencies only."""
        downstream_data = [
            {"source": "db", "app_name": "downstream1", "namespace": "prod", "direction": "downstream"},
        ]

        with patch("src.services.merge_service.fetch_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.services.merge_service.fetch_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_down.return_value = downstream_data

            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                "my-app", "my-namespace", direction="downstream"
            )

            assert len(upstream) == 0
            assert len(downstream) == 1
            assert breakdown["downstream_count"] == 1
            mock_up.assert_not_called()
            mock_down.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_empty_results(self):
        """Test when both upstream and downstream return empty."""
        with patch("src.services.merge_service.fetch_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.services.merge_service.fetch_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = []
            mock_down.return_value = []

            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                "my-app", "my-namespace"
            )

            assert upstream == []
            assert downstream == []
            assert breakdown["total"] == 0

    @pytest.mark.asyncio
    async def test_direction_none_fetches_both(self):
        """Test that direction=None fetches both upstream and downstream."""
        with patch("src.services.merge_service.fetch_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.services.merge_service.fetch_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = [{"source": "db", "app_name": "up", "namespace": "ns", "direction": "upstream"}]
            mock_down.return_value = [{"source": "db", "app_name": "down", "namespace": "ns", "direction": "downstream"}]

            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                "my-app", "my-namespace", direction=None
            )

            mock_up.assert_called_once()
            mock_down.assert_called_once()
            assert breakdown["total"] == 2

    @pytest.mark.asyncio
    async def test_raw_data_passed_through_unchanged(self):
        """Test that the raw SRE-OPS data is returned as-is without any transformation."""
        raw_dep = {
            "source": "db",
            "type": "cassandra",
            "application_id": 595,
            "application_name": "unified-rollups-prod::cass-azv2-2",
            "managed_service_id": 35,
            "wcnp_id": None,
            "namespace": None,
            "app_name": None,
            "assembly": "unified-rollups-prod",
            "platform": "cass-azv2-2",
            "tier": "Unknown",
            "direction": "upstream",
        }

        with patch("src.services.merge_service.fetch_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.services.merge_service.fetch_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = [raw_dep]
            mock_down.return_value = []

            upstream, _, _ = await get_upstream_and_downstream_dependencies(
                "my-app", "my-namespace", direction="upstream"
            )

            dep = upstream[0]
            # Every field from SRE-OPS must be present exactly as received
            assert dep["source"] == "db"
            assert dep["type"] == "cassandra"
            assert dep["application_id"] == 595
            assert dep["managed_service_id"] == 35
            assert dep["wcnp_id"] is None       # null preserved
            assert dep["namespace"] is None     # null preserved
            assert dep["app_name"] is None      # null preserved
            assert dep["assembly"] == "unified-rollups-prod"
