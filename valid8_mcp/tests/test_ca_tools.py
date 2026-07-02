"""Tests for Canada (CA) MCP tools."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.providers.ca_tools import ca_orchestrated_query


@pytest.mark.asyncio
async def test_ca_orchestrated_query_success(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(
        return_value={"result": "sku_data", "status": "validated"},
    )
    result = await ca_orchestrated_query(sku_id="6000199554997")
    assert result["success"] is True
    assert result["data"]["result"] == "sku_data"
    assert result["sku_id"] == "6000199554997"
    assert "took_ms" in result


@pytest.mark.asyncio
async def test_ca_orchestrated_query_api_error(patched_service, mock_valid8_client):
    from src.http_client import Valid8ApiError

    mock_valid8_client.post = AsyncMock(
        side_effect=Valid8ApiError(400, "Invalid SKU"),
    )
    result = await ca_orchestrated_query(sku_id="BAD-SKU")
    assert result["success"] is False
    assert "Invalid SKU" in result["error"]


@pytest.mark.asyncio
async def test_ca_orchestrated_query_passes_tenant(patched_service, mock_valid8_client):
    mock_valid8_client.post = AsyncMock(return_value={"result": "ok"})
    await ca_orchestrated_query(sku_id="6000199554997")
    mock_valid8_client.post.assert_called_once_with(
        "/ca/api/orchestrated-query",
        tenant="ca",
        json={"sku_id": "6000199554997"},
    )
