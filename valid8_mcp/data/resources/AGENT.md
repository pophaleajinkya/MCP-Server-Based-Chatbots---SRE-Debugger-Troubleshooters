# Valid8 MCP Server — Agent Guide

## Overview

The Valid8 MCP Server provides tools for validating entities and retrieving data
from Walmart's **Valid8** platform. It serves **Canada (CA)** and **Mexico (MX)**
markets.

## Authentication

Valid8 uses **API key + tenant header** authentication:
- **X-API-Key**: Set via the `VALID8_API_KEY` environment variable
- **X-Tenant**: Determined automatically per tool (`ca` or `mx`)

Authentication is handled internally — you do not need to pass credentials.
Simply call any tool and it will authenticate on your behalf.

## Available Tools

### Canada (CA) Tools

| Tool | Description |
|------|-------------|
| `ca_orchestrated_query` | Run OASIS / SKU validation by sku_id |

### Mexico (MX) Tools

| Tool | Description |
|------|-------------|
| `mx_item_visibility_lookup_upc` | Look up item visibility by offerId + banner + store |
| `mx_item_status` | Get item status for a banner and list of items |
| `mx_order_dashboard_search` | Search order dashboard by seller name and time frame |

## Workflow

### For CA SKU Validation
1. Call `ca_orchestrated_query(sku_id="6000199554997")`
2. Review the orchestrated results across catalog, IMS, MCSE, PNO, and search

### For MX Item Lookups
1. Call `mx_item_visibility_lookup_upc(offer_id="...", banner="WM", store_number="2344")` for store-level visibility
2. Or call `mx_item_status(banner="wm-bd", items=["00085240100638"])` for item status by banner

### For MX Order Dashboard
1. Call `mx_order_dashboard_search(seller_name="Bodega Aurrera", time_frame="30min")`

## Response Format

All tools return a dict with:
- `success: true/false` — whether the API call succeeded
- `data: {...}` — the response payload from Valid8
- `took_ms: N` — request duration in milliseconds
- `error: "..."` — error message (only when success=false)

## Error Handling

- **Connection errors**: Valid8 is unreachable → retry after a moment
- **API errors (401)**: Invalid or missing API key → check VALID8_API_KEY config
- **API errors (4xx/5xx)**: Bad request or server error → check the error message for details

## Tips

- Always provide all required parameters for each tool
- For MX item status, the `banner` field accepts codes like "wm-bd" (Bodega), "WM" (Walmart)
- Time frames for order dashboard: "30min", "1h", "24h"
- SKU IDs for CA are numeric strings like "6000199554997"
