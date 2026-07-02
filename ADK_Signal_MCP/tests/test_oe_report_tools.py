"""Tests for OE Report MCP tools."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.providers.oe_report_tools import (
    get_oe_report_certified,
    get_oe_report_not_certified,
)


@pytest.mark.asyncio
async def test_get_oe_report_certified_success(patched_service, mock_signal_client):
    mock_signal_client.post = AsyncMock(
        return_value={"rows": [{"app": "app-1", "status": "certified"}]},
    )
    result = await get_oe_report_certified(tr_product="All", apm_id="All")
    assert result["success"] is True
    assert result["data"]["rows"][0]["status"] == "certified"
    assert result["tr_product"] == "All"
    assert result["apm_id"] == "All"
    assert "took_ms" in result


@pytest.mark.asyncio
async def test_get_oe_report_certified_with_filters(patched_service, mock_signal_client):
    mock_signal_client.post = AsyncMock(return_value={"rows": []})
    result = await get_oe_report_certified(tr_product="ProductX", apm_id="APM123")
    assert result["success"] is True
    assert result["tr_product"] == "ProductX"
    assert result["apm_id"] == "APM123"
    mock_signal_client.post.assert_called_once_with(
        "/api/oeReport/intl-oe-wcnp-data-certified",
        json={"tr_product": "ProductX", "apm_id": "APM123"},
    )


@pytest.mark.asyncio
async def test_get_oe_report_not_certified_success(patched_service, mock_signal_client):
    mock_signal_client.post = AsyncMock(
        return_value={"rows": [{"app": "app-2", "status": "not-certified"}]},
    )
    result = await get_oe_report_not_certified(tr_product="All", apm_id="All")
    assert result["success"] is True
    assert result["data"]["rows"][0]["status"] == "not-certified"
    assert "took_ms" in result


@pytest.mark.asyncio
async def test_get_oe_report_not_certified_api_error(patched_service, mock_signal_client):
    from src.http_client import SignalApiError

    mock_signal_client.post = AsyncMock(
        side_effect=SignalApiError(400, "Bad Request"),
    )
    result = await get_oe_report_not_certified()
    assert result["success"] is False
    assert "Bad Request" in result["error"]


@pytest.mark.asyncio
async def test_get_oe_report_certified_passes_body(patched_service, mock_signal_client):
    mock_signal_client.post = AsyncMock(return_value={"rows": []})
    await get_oe_report_certified(tr_product="All", apm_id="All")
    mock_signal_client.post.assert_called_once_with(
        "/api/oeReport/intl-oe-wcnp-data-certified",
        json={"tr_product": "All", "apm_id": "All"},
    )
