"""Mexico (MX) tools — item visibility, item status, order dashboard.

Tools:
  mx_item_visibility_lookup_upc  Look up MX item visibility by UPC
  mx_item_status                 Get MX item status for banner + items
  mx_order_dashboard_search      Search MX order dashboard
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import get_valid8_service

provider = LocalProvider()


@provider.tool("mx_item_visibility_lookup_upc")
async def mx_item_visibility_lookup_upc(
    offer_id: str,
    banner: str,
    store_number: str,
) -> dict[str, Any]:
    """
    Look up Mexico item visibility by offerId, banner, and store number.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - MX item visibility
      - Item lookup by UPC / offer ID in Mexico
      - Store-level visibility for a Mexican item
    Examples:
      "check item visibility for offer 2F1A382F30483E47AD888D0AA01DBDDF at WM store 2344"
      "is this item visible in Mexico?"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Valid8 POST /mx/item-visibility/lookup-upc with offerId, banner,
    and storeNumber. Authenticated via X-API-Key + X-Tenant: mx headers.

    Parameters:
        offer_id:     Offer ID for the item.
                      Example: "2F1A382F30483E47AD888D0AA01DBDDF"
        banner:       Banner code (e.g. "WM" for Walmart Mexico).
                      Example: "WM"
        store_number: Store number.
                      Example: "2344"

    Returns:
        {"success": true, "data": {...}, "offer_id": "...", "banner": "...", "store_number": "..."}
        {"success": false, "error": "..."}
    """
    svc = get_valid8_service()
    return await svc.mx_item_visibility_lookup_upc(
        offer_id=offer_id, banner=banner, store_number=store_number,
    )


@provider.tool("mx_item_status")
async def mx_item_status(
    banner: str,
    items: list[str],
    format: str = "table",
) -> dict[str, Any]:
    """
    Get Mexico item status for a list of items and banner.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - MX item status
      - Status of items in Mexico by banner
      - Item availability in a Mexican banner
    Examples:
      "get item status for 00085240100638 in wm-bd"
      "check these items in Bodega: 00085240100638, 00085240100639"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Valid8 POST /mx/api/item-status with banner, items list, and
    optional format. Authenticated via X-API-Key + X-Tenant: mx headers.
    Returns status details for each item.

    Parameters:
        banner: Banner code (e.g. "wm-bd" for Bodega Aurrera).
                Example: "wm-bd"
        items:  List of item IDs to check status.
                Example: ["00085240100638"]
        format: Output format (default: "table").

    Returns:
        {"success": true, "data": {...}, "banner": "...", "items": [...]}
        {"success": false, "error": "..."}
    """
    svc = get_valid8_service()
    return await svc.mx_item_status(banner=banner, items=items, fmt=format)


@provider.tool("mx_order_dashboard_search")
async def mx_order_dashboard_search(
    seller_name: str = "",
    time_frame: str = "",
) -> dict[str, Any]:
    """
    Search the Mexico order dashboard by seller name and time frame.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - MX order dashboard
      - Recent orders in Mexico
      - Order search by seller or time
    Examples:
      "show recent orders for Bodega Aurrera in the last 30 minutes"
      "search MX order dashboard for the last hour"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Valid8 POST /mx/api/order-dashboard/search with optional
    seller_name and time_frame filters. Authenticated via X-API-Key +
    X-Tenant: mx headers. Returns matching orders.

    Parameters:
        seller_name: Seller name to filter by (optional).
                     Example: "Bodega Aurrera"
        time_frame:  Time frame filter (e.g. "30min", "1h", "24h"). Optional.
                     Example: "30min"

    Returns:
        {"success": true, "data": {...}, "seller_name": "...", "time_frame": "..."}
        {"success": false, "error": "..."}
    """
    svc = get_valid8_service()
    return await svc.mx_order_dashboard_search(
        seller_name=seller_name, time_frame=time_frame,
    )
