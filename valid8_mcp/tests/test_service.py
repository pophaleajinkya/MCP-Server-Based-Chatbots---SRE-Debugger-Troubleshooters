"""Tests for the Valid8Service layer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.http_client import Valid8ApiError, Valid8ConnectionError
from src.services.valid8_service import Valid8Service


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def svc(client):
    return Valid8Service(client)


@pytest.mark.asyncio
async def test_ca_orchestrated_query_success(svc, client):
    client.post = AsyncMock(return_value={"validated": True})
    result = await svc.ca_orchestrated_query("6000199554997")
    assert result["success"] is True
    assert result["data"]["validated"] is True
    client.post.assert_called_once_with(
        "/ca/api/orchestrated-query",
        tenant="ca",
        json={"sku_id": "6000199554997"},
    )


@pytest.mark.asyncio
async def test_ca_orchestrated_query_api_error(svc, client):
    client.post = AsyncMock(side_effect=Valid8ApiError(500, "Server error"))
    result = await svc.ca_orchestrated_query("BAD")
    assert result["success"] is False
    assert "500" in result["error"]


@pytest.mark.asyncio
async def test_mx_item_visibility(svc, client):
    client.post = AsyncMock(return_value={"offerId": "ABC", "success": True, "upc": "001"})
    result = await svc.mx_item_visibility_lookup_upc("ABC", "WM", "2344")
    assert result["success"] is True
    client.post.assert_called_once_with(
        "/mx/item-visibility/lookup-upc",
        tenant="mx",
        json={"offerId": "ABC", "banner": "WM", "storeNumber": "2344"},
    )


@pytest.mark.asyncio
async def test_mx_item_status(svc, client):
    client.post = AsyncMock(return_value={"items": []})
    result = await svc.mx_item_status("wm-bd", ["001"], fmt="table")
    assert result["success"] is True
    client.post.assert_called_once_with(
        "/mx/api/item-status",
        tenant="mx",
        json={"banner": "wm-bd", "items": ["001"], "format": "table"},
    )


@pytest.mark.asyncio
async def test_mx_order_dashboard_search(svc, client):
    client.post = AsyncMock(return_value={"orders": []})
    result = await svc.mx_order_dashboard_search("Bodega", "1h")
    assert result["success"] is True
    assert result["seller_name"] == "Bodega"
    client.post.assert_called_once_with(
        "/mx/api/order-dashboard/search",
        tenant="mx",
        json={"seller_name": "Bodega", "time_frame": "1h"},
    )


@pytest.mark.asyncio
async def test_connection_error_handling(svc, client):
    client.post = AsyncMock(
        side_effect=Valid8ConnectionError("Cannot connect"),
    )
    result = await svc.ca_orchestrated_query("6000199554997")
    assert result["success"] is False
    assert "Connection error" in result["error"]


@pytest.mark.asyncio
async def test_api_error_includes_status(svc, client):
    client.post = AsyncMock(side_effect=Valid8ApiError(401, "Unauthorized"))
    result = await svc.mx_item_status("WM", ["001"])
    assert result["success"] is False
    assert result.get("status_code") == 401
