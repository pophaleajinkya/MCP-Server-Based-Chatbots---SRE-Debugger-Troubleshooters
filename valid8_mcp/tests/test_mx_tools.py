"""Tests for Mexico (MX) MCP tools."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.providers.mx_tools import (
    mx_item_status,
    mx_item_visibility_lookup_upc,
    mx_order_dashboard_search,
)


@pytest.mark.asyncio
async def test_mx_item_visibility_lookup_upc(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(
        return_value={"offerId": "2F1A382F30483E47AD888D0AA01DBDDF", "storeNumber": "2344", "success": True, "upc": "00033554661739"},
    )
    result = await mx_item_visibility_lookup_upc(
        offer_id="2F1A382F30483E47AD888D0AA01DBDDF",
        banner="WM",
        store_number="2344",
    )
    assert result["success"] is True
    assert result["offer_id"] == "2F1A382F30483E47AD888D0AA01DBDDF"
    assert result["banner"] == "WM"
    assert result["store_number"] == "2344"


@pytest.mark.asyncio
async def test_mx_item_status(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(
        return_value={"items": [{"id": "00085240100638", "status": "active"}]},
    )
    result = await mx_item_status(
        banner="wm-bd",
        items=["00085240100638"],
        format="table",
    )
    assert result["success"] is True
    assert result["banner"] == "wm-bd"
    assert result["items"] == ["00085240100638"]


@pytest.mark.asyncio
async def test_mx_item_status_multiple_items(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(
        return_value={"items": [
            {"id": "001", "status": "active"},
            {"id": "002", "status": "inactive"},
        ]},
    )
    result = await mx_item_status(
        banner="WM",
        items=["001", "002"],
    )
    assert result["success"] is True
    assert len(result["data"]["items"]) == 2


@pytest.mark.asyncio
async def test_mx_order_dashboard_search(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(
        return_value={"orders": [{"id": "MX-ORD-1", "seller": "Bodega Aurrera"}]},
    )
    result = await mx_order_dashboard_search(
        seller_name="Bodega Aurrera",
        time_frame="30min",
    )
    assert result["success"] is True
    assert result["seller_name"] == "Bodega Aurrera"
    assert result["time_frame"] == "30min"
    assert len(result["data"]["orders"]) == 1


@pytest.mark.asyncio
async def test_mx_order_dashboard_search_no_filters(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(return_value={"orders": []})
    result = await mx_order_dashboard_search()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_mx_item_status_passes_tenant(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(return_value={"items": []})
    await mx_item_status(banner="wm-bd", items=["001"])
    mock_valid8_client.post.assert_called_once_with(
        "/mx/api/item-status",
        tenant="mx",
        json={"banner": "wm-bd", "items": ["001"], "format": "table"},
    )
