"""Tests for App Metadata MCP tools."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.providers.metadata_tools import get_app_metadata_filters


@pytest.mark.asyncio
async def test_get_app_metadata_filters_success(patched_service, mock_signal_client):
    mock_signal_client.get = AsyncMock(
        return_value={"filters": ["environment", "team", "criticality"]},
    )
    result = await get_app_metadata_filters()
    assert result["success"] is True
    assert "filters" in result["data"]
    assert "took_ms" in result


@pytest.mark.asyncio
async def test_get_app_metadata_filters_api_error(patched_service, mock_signal_client):
    from src.http_client import SignalApiError

    mock_signal_client.get = AsyncMock(
        side_effect=SignalApiError(503, "Service Unavailable"),
    )
    result = await get_app_metadata_filters()
    assert result["success"] is False
    assert "503" in result["error"]
