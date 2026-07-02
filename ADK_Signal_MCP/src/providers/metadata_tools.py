"""App Metadata tools — fetch metadata filters from Signal API.

Tools:
  get_app_metadata_filters  Fetch app metadata filter options
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import get_signal_service

provider = LocalProvider()


@provider.tool("get_app_metadata_filters")
async def get_app_metadata_filters() -> dict[str, Any]:
    """
    Fetch app metadata filters from Signal.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use when the user asks for:
      - App metadata filters
      - Available filter options for apps
      - Metadata filter criteria
      - Signal filter metadata
    Examples:
      "show me the app metadata filters"
      "what filters are available for applications?"
      "get filter options from Signal"

    ── HOW IT WORKS ───────────────────────────────────────────────────────────
    Calls Signal GET /api/appmetadata/filters
    Returns the available metadata filter options for applications.

    Returns:
        {"success": true, "data": {...}, "took_ms": N}
        {"success": false, "error": "..."}
    """
    svc = get_signal_service()
    return await svc.get_app_metadata_filters()
