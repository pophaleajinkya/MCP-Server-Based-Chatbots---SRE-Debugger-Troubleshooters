# Signal MCP Server — Agent Guide

## Overview

The Signal MCP Server provides tools for querying Walmart's **Signal** platform.
It exposes app inventory suggestions, metadata filters, and OE (Operational
Excellence) reports for WCNP certified and not-certified data.

## Authentication

Signal API currently requires **no API key or token**. Requests are authenticated
implicitly via network access. All tools work immediately — no manual auth
steps needed.

## Available Tools

### App Inventory

| Tool | Description |
|------|-------------|
| `get_app_inventory_suggestions` | Fetch all app inventory suggestions |

### App Metadata

| Tool | Description |
|------|-------------|
| `get_app_metadata_filters` | Fetch available metadata filter options |

### OE Reports

| Tool | Description |
|------|-------------|
| `get_oe_report_certified` | Fetch OE report for WCNP certified data |
| `get_oe_report_not_certified` | Fetch OE report for WCNP not-certified data |

## Workflow

### For App Inventory
1. Call `get_app_inventory_suggestions()` to get all available suggestions

### For App Metadata
1. Call `get_app_metadata_filters()` to see available filter options

### For OE Reports (Certified)
1. Call `get_oe_report_certified()` for all certified data
2. Or filter: `get_oe_report_certified(tr_product="MyProduct", apm_id="APM123")`

### For OE Reports (Not Certified)
1. Call `get_oe_report_not_certified()` for all not-certified data
2. Or filter: `get_oe_report_not_certified(tr_product="MyProduct", apm_id="APM123")`

## Response Format

All tools return a dict with:
- `success: true/false` — whether the API call succeeded
- `data: {...}` — the response payload from Signal
- `took_ms: N` — request duration in milliseconds
- `error: "..."` — error message (only when success=false)

## Error Handling

- **Connection errors**: Signal API is unreachable → retry after a moment
- **API errors (4xx/5xx)**: Bad request or server error → check the error message for details

## Tips

- OE report tools accept `tr_product` and `apm_id` filters; use "All" for no filtering
- App inventory and metadata tools take no parameters — they return all available data
- All tools are read-only; they do not modify any data
