"""
Signal Service — all API operations against the Signal backend.

Called by MCP tool handlers in the provider modules.
Every public method returns a plain ``dict`` — never raises.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.http_client import SignalApiError, SignalConnectionError, SignalHttpClient

logger = logging.getLogger(__name__)


class SignalService:
    """
    Unified service layer for the Signal API.

    Wraps the HTTP client and provides typed methods for each Signal
    API endpoint. Returns structured dicts for all success/error paths.
    """

    def __init__(self, client: SignalHttpClient) -> None:
        self._client = client

    def _ok(self, **fields: Any) -> dict[str, Any]:
        return {"success": True, **fields}

    def _err(self, error: str, **fields: Any) -> dict[str, Any]:
        logger.error("SignalService error: %s", error)
        return {"success": False, "error": error, **fields}

    def _handle_exc(self, exc: Exception, op: str, **ctx: Any) -> dict[str, Any]:
        if isinstance(exc, SignalApiError):
            msg = f"Signal API error ({exc.status_code}): {exc.message[:300]}"
            return self._err(msg, status_code=exc.status_code, **ctx)
        elif isinstance(exc, SignalConnectionError):
            return self._err(f"Connection error: {exc}", **ctx)
        elif isinstance(exc, ValueError):
            return self._err(str(exc), **ctx)
        return self._err(f"Unexpected error in {op}: {exc}", **ctx)

    # ------------------------------------------------------------------
    # App Inventory
    # ------------------------------------------------------------------

    async def get_app_inventory_suggestions(self) -> dict[str, Any]:
        """Fetch all app inventory suggestions."""
        t0 = time.perf_counter()
        try:
            data = await self._client.get(
                "/api/appInventory/suggestions/all",
            )
            return self._ok(
                data=data,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(exc, "get_app_inventory_suggestions")

    # ------------------------------------------------------------------
    # App Metadata
    # ------------------------------------------------------------------

    async def get_app_metadata_filters(self) -> dict[str, Any]:
        """Fetch app metadata filters."""
        t0 = time.perf_counter()
        try:
            data = await self._client.get(
                "/api/appmetadata/filters",
            )
            return self._ok(
                data=data,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(exc, "get_app_metadata_filters")

    # ------------------------------------------------------------------
    # OE Reports
    # ------------------------------------------------------------------

    async def get_oe_report_certified(
        self,
        tr_product: str = "All",
        apm_id: str = "All",
    ) -> dict[str, Any]:
        """Fetch OE report for WCNP certified data."""
        t0 = time.perf_counter()
        try:
            data = await self._client.post(
                "/api/oeReport/intl-oe-wcnp-data-certified",
                json={"tr_product": tr_product, "apm_id": apm_id},
            )
            return self._ok(
                data=data,
                tr_product=tr_product,
                apm_id=apm_id,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(
                exc, "get_oe_report_certified",
                tr_product=tr_product, apm_id=apm_id,
            )

    async def get_oe_report_not_certified(
        self,
        tr_product: str = "All",
        apm_id: str = "All",
    ) -> dict[str, Any]:
        """Fetch OE report for WCNP not-certified data."""
        t0 = time.perf_counter()
        try:
            data = await self._client.post(
                "/api/oeReport/intl-oe-wcnp-data-not-certified",
                json={"tr_product": tr_product, "apm_id": apm_id},
            )
            return self._ok(
                data=data,
                tr_product=tr_product,
                apm_id=apm_id,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            return self._handle_exc(
                exc, "get_oe_report_not_certified",
                tr_product=tr_product, apm_id=apm_id,
            )
