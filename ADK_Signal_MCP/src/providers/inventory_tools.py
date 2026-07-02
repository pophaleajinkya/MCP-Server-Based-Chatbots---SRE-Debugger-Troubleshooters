"""App Inventory tools — fetch inventory suggestions from Signal API.

Tools:
  get_app_inventory_suggestions  Fetch all app inventory suggestions
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import get_signal_service

provider = LocalProvider()


@provider.tool("get_app_inventory_suggestions")
async def get_app_inventory_suggestions() -> dict[str, Any]:
    """
    Fetch all app inventory suggestions from Signal.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - App inventory suggestions
      - Application inventory list
      - All available app suggestions
      - Signal app inventory data
    Examples:
      "show me all app inventory suggestions"
      "list application inventory"
      "what apps are in the inventory?"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Signal GET /api/appInventory/suggestions/all
    Returns the complete list of app inventory suggestions.

    Returns:
        {"success": true, "data": [...], "took_ms": N}
        {"success": false, "error": "..."}
    """
    svc = get_signal_service()
    return await svc.get_app_inventory_suggestions()
