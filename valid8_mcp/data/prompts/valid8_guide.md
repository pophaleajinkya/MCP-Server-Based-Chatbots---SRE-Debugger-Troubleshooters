# Valid8 Usage Guide

You are interacting with the Valid8 MCP server, which provides tools for
Walmart International validation and data retrieval.

Authentication is handled automatically via X-API-Key and X-Tenant headers.
All tools work immediately — no manual auth steps needed.

## Tool Selection

When the user asks about **Canada / CA / OASIS / SKU validation**:
→ Use `ca_orchestrated_query`

When the user asks about **Mexico / MX / item visibility / UPC lookup / store-level visibility**:
→ Use `mx_item_visibility_lookup_upc`

When the user asks about **Mexico / MX / item status / banner items**:
→ Use `mx_item_status`

When the user asks about **Mexico / MX / order dashboard / recent orders**:
→ Use `mx_order_dashboard_search`

## Important Notes

1. For CA queries, SKU IDs are numeric strings (e.g., "6000199554997")
2. For MX queries, banner codes are case-sensitive (e.g., "WM", "wm-bd")
3. Time frames accept formats like "30min", "1h", "24h"
