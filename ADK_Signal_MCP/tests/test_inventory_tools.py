"""Tests for App Inventory MCP tools."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.providers.inventory_tools import get_app_inventory_suggestions


@pytest.mark.asyncio
async def test_get_app_inventory_suggestions_success(patched_service, mock_signal_client):
    mock_signal_client.get = AsyncMock(
        return_value=[{"app_id": "app-1", "name": "Test App"}],
    )
    result = await get_app_inventory_suggestions()
    assert result["success"] is True
    assert result["data"] == [{"app_id": "app-1", "name": "Test App"}]
    assert "took_ms" in result


@pytest.mark.asyncio
async def test_get_app_inventory_suggestions_api_error(patched_service, mock_signal_client):
    from src.http_client import SignalApiError

    mock_signal_client.get = AsyncMock(
        side_effect=SignalApiError(500, "Internal Server Error"),
    )
    result = await get_app_inventory_suggestions()
    assert result["success"] is False
    assert "500" in result["error"]
