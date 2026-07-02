"""Canada (CA) tools — orchestrated query for SKU validation.

Tools:
  ca_orchestrated_query  Run CA orchestrated query by SKU ID
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import get_valid8_service

provider = LocalProvider()


@provider.tool("ca_orchestrated_query")
async def ca_orchestrated_query(sku_id: str) -> dict[str, Any]:
    """
    Run Canada orchestrated query (OASIS / SKU validation) by sku_id.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - CA orchestrated query
      - OASIS SKU validation
      - Canada SKU lookup
    Examples:
      "run orchestrated query for SKU 6000199554997"
      "validate Canadian SKU 6000199554997"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Valid8 POST /ca/api/orchestrated-query with the given sku_id.
    Authenticated via X-API-Key + X-Tenant: ca headers.
    The Valid8 backend performs an OASIS lookup and returns SKU validation
    results including catalog, IMS, MCSE, PNO, and search data.

    Parameters:
        sku_id: SKU identifier for Canada orchestrated query.
                Example: "6000199554997"

    Returns:
        {"success": true, "data": {...}, "sku_id": "...", "took_ms": N}
        {"success": false, "error": "..."}
    """
    svc = get_valid8_service()
    return await svc.ca_orchestrated_query(sku_id=sku_id)
