"""Tests for the SignalService layer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.http_client import SignalApiError, SignalConnectionError
from src.services.signal_service import SignalService


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def svc(client):
    return SignalService(client)


@pytest.mark.asyncio
async def test_get_app_inventory_suggestions_success(svc, client):
    client.get = AsyncMock(return_value=[{"app": "test-app"}])
    result = await svc.get_app_inventory_suggestions()
    assert result["success"] is True
    assert result["data"] == [{"app": "test-app"}]
    client.get.assert_called_once_with("/api/appInventory/suggestions/all")


@pytest.mark.asyncio
async def test_get_app_metadata_filters_success(svc, client):
    client.get = AsyncMock(return_value={"filters": ["env", "team"]})
    result = await svc.get_app_metadata_filters()
    assert result["success"] is True
    assert result["data"]["filters"] == ["env", "team"]
    client.get.assert_called_once_with("/api/appmetadata/filters")


@pytest.mark.asyncio
async def test_get_oe_report_certified_success(svc, client):
    client.post = AsyncMock(return_value={"report": "certified-data"})
    result = await svc.get_oe_report_certified("All", "All")
    assert result["success"] is True
    assert result["data"]["report"] == "certified-data"
    assert result["tr_product"] == "All"
    assert result["apm_id"] == "All"
    client.post.assert_called_once_with(
        "/api/oeReport/intl-oe-wcnp-data-certified",
        json={"tr_product": "All", "apm_id": "All"},
    )


@pytest.mark.asyncio
async def test_get_oe_report_not_certified_success(svc, client):
    client.post = AsyncMock(return_value={"report": "not-certified-data"})
    result = await svc.get_oe_report_not_certified("ProductX", "APM123")
    assert result["success"] is True
    assert result["data"]["report"] == "not-certified-data"
    assert result["tr_product"] == "ProductX"
    assert result["apm_id"] == "APM123"
    client.post.assert_called_once_with(
        "/api/oeReport/intl-oe-wcnp-data-not-certified",
        json={"tr_product": "ProductX", "apm_id": "APM123"},
    )


@pytest.mark.asyncio
async def test_api_error_handling(svc, client):
    client.get = AsyncMock(side_effect=SignalApiError(500, "Server error"))
    result = await svc.get_app_inventory_suggestions()
    assert result["success"] is False
    assert "500" in result["error"]


@pytest.mark.asyncio
async def test_connection_error_handling(svc, client):
    client.get = AsyncMock(
        side_effect=SignalConnectionError("Cannot connect"),
    )
    result = await svc.get_app_metadata_filters()
    assert result["success"] is False
    assert "Connection error" in result["error"]


@pytest.mark.asyncio
async def test_api_error_includes_status(svc, client):
    client.post = AsyncMock(side_effect=SignalApiError(401, "Unauthorized"))
    result = await svc.get_oe_report_certified()
    assert result["success"] is False
    assert result.get("status_code") == 401
