"""OE Report tools — fetch certified and not-certified WCNP data from Signal API.

Tools:
  get_oe_report_certified       Fetch OE report for WCNP certified data
  get_oe_report_not_certified   Fetch OE report for WCNP not-certified data
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import get_signal_service

provider = LocalProvider()


@provider.tool("get_oe_report_certified")
async def get_oe_report_certified(
    tr_product: str = "All",
    apm_id: str = "All",
) -> dict[str, Any]:
    """
    Fetch OE report for WCNP certified data from Signal.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - OE report for certified data
      - WCNP certified report
      - Certified OE data
      - Certified operational excellence report
    Examples:
      "show me the certified OE report"
      "get WCNP certified data"
      "OE report for certified apps"
      "show certified OE report for product X"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Signal POST /api/oeReport/intl-oe-wcnp-data-certified
    with optional tr_product and apm_id filters.

    Parameters:
        tr_product: Product filter. Use "All" for all products, or specify
                    a specific product name. Default: "All"
        apm_id:     APM ID filter. Use "All" for all APM IDs, or specify
                    a specific APM ID. Default: "All"

    Returns:
        {"success": true, "data": {...}, "tr_product": "...", "apm_id": "...", "took_ms": N}
        {"success": false, "error": "..."}
    """
    svc = get_signal_service()
    return await svc.get_oe_report_certified(
        tr_product=tr_product, apm_id=apm_id,
    )


@provider.tool("get_oe_report_not_certified")
async def get_oe_report_not_certified(
    tr_product: str = "All",
    apm_id: str = "All",
) -> dict[str, Any]:
    """
    Fetch OE report for WCNP not-certified data from Signal.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - OE report for not-certified data
      - WCNP not-certified report
      - Not-certified OE data
      - Non-certified operational excellence report
    Examples:
      "show me the not-certified OE report"
      "get WCNP not-certified data"
      "OE report for non-certified apps"
      "show not-certified OE report for APM ID abc123"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Signal POST /api/oeReport/intl-oe-wcnp-data-not-certified
    with optional tr_product and apm_id filters.

    Parameters:
        tr_product: Product filter. Use "All" for all products, or specify
                    a specific product name. Default: "All"
        apm_id:     APM ID filter. Use "All" for all APM IDs, or specify
                    a specific APM ID. Default: "All"

    Returns:
        {"success": true, "data": {...}, "tr_product": "...", "apm_id": "...", "took_ms": N}
        {"success": false, "error": "..."}
    """
    svc = get_signal_service()
    return await svc.get_oe_report_not_certified(
        tr_product=tr_product, apm_id=apm_id,
    )
