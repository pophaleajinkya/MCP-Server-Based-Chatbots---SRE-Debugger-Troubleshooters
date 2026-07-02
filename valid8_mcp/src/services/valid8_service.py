"""
Valid8 Service — API operations against the Valid8 backend.

Called by MCP tool handlers in the provider modules.
Every public method returns a plain ``dict`` — never raises.

Provides four live endpoints:
  - ca_orchestrated_query          (tenant=ca)
  - mx_item_visibility_lookup_upc  (tenant=mx)
  - mx_item_status                 (tenant=mx)
  - mx_order_dashboard_search      (tenant=mx)

Authentication: X-API-Key + X-Tenant headers, handled by the HTTP client.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.http_client import Valid8ApiError, Valid8ConnectionError, Valid8HttpClient

logger = logging.getLogger(__name__)


class Valid8Service:
    """
    Unified service layer for the Valid8 API.

    Wraps the HTTP client and provides typed methods for each Valid8
    API endpoint. Returns structured dicts for all success/error paths.
    """

    def __init__(self, client: Valid8HttpClient) -> None:
        self._client = client

    def _ok(self, **fields: Any) -> dict[str, Any]:
        return {"success": True, **fields}

    def _err(self, error: str, **fields: Any) -> dict[str, Any]:
        logger.error("Valid8Service error: %s", error)
        return {"success": False, "error": error, **fields}

    def _handle_exc(self, exc: Exception, op: str, **ctx: Any) -> dict[str, Any]:
        if isinstance(exc, Valid8ApiError):
            msg = f"Valid8 API error ({exc.status_code}): {exc.message[:300]}"
            return self._err(msg, status_code=exc.status_code, **ctx)
        elif isinstance(exc, Valid8ConnectionError):
            return self._err(f"Connection error: {exc}", **ctx)
        elif isinstance(exc, ValueError):
            return self._err(str(exc), **ctx)
        return self._err(f"Unexpected error in {op}: {exc}", **ctx)

    # ------------------------------------------------------------------
    # Canada (CA) APIs — tenant="ca"
    # ------------------------------------------------------------------

    async def ca_orchestrated_query(self, sku_id: str) -> dict[str, Any]:
        """Run Canada orchestrated query (OASIS / SKU validation) by sku_id."""
        t0 = time.perf_counter()
        try:
            data = await self._client.post(
                "/ca/api/orchestrated-query",
                tenant="ca",
                json={"sku_id": sku_id},
            )
            return self._ok(
                data=data,
                sku_id=sku_id,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(exc, "ca_orchestrated_query", sku_id=sku_id)

    # ------------------------------------------------------------------
    # Mexico (MX) APIs — tenant="mx"
    # ------------------------------------------------------------------

    async def mx_item_visibility_lookup_upc(
        self,
        offer_id: str,
        banner: str,
        store_number: str,
    ) -> dict[str, Any]:
        """Look up MX item visibility by offerId, banner, and store number."""
        t0 = time.perf_counter()
        try:
            data = await self._client.post(
                "/mx/item-visibility/lookup-upc",
                tenant="mx",
                json={
                    "offerId": offer_id,
                    "banner": banner,
                    "storeNumber": store_number,
                },
            )
            return self._ok(
                data=data,
                offer_id=offer_id,
                banner=banner,
                store_number=store_number,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(
                exc, "mx_item_visibility_lookup_upc",
                offer_id=offer_id, banner=banner, store_number=store_number,
            )

    async def mx_item_status(
        self,
        banner: str,
        items: list[str],
        fmt: str = "table",
    ) -> dict[str, Any]:
        """Get MX item status for a list of items and banner."""
        t0 = time.perf_counter()
        try:
            body: dict[str, Any] = {"banner": banner, "items": items}
            if fmt:
                body["format"] = fmt
            data = await self._client.post(
                "/mx/api/item-status", tenant="mx", json=body,
            )
            return self._ok(
                data=data,
                banner=banner,
                items=items,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(
                exc, "mx_item_status", banner=banner, items=items,
            )

    async def mx_order_dashboard_search(
        self,
        seller_name: str = "",
        time_frame: str = "",
    ) -> dict[str, Any]:
        """Search MX order dashboard by seller name and time frame."""
        t0 = time.perf_counter()
        try:
            body: dict[str, Any] = {}
            if seller_name:
                body["seller_name"] = seller_name
            if time_frame:
                body["time_frame"] = time_frame
            data = await self._client.post(
                "/mx/api/order-dashboard/search", tenant="mx", json=body,
            )
            return self._ok(
                data=data,
                seller_name=seller_name,
                time_frame=time_frame,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(
                exc, "mx_order_dashboard_search",
                seller_name=seller_name, time_frame=time_frame,
            )
