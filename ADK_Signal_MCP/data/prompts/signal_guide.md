# Signal Usage Guide

You are interacting with the Signal MCP server, which provides tools for
Walmart International Signal platform data retrieval.

No authentication is required — all tools work immediately.

## Tool Selection

When the user asks about **app inventory / application suggestions / inventory list**:
→ Use `get_app_inventory_suggestions`

When the user asks about **app metadata / filters / filter options**:
→ Use `get_app_metadata_filters`

When the user asks about **OE report / certified / WCNP certified data**:
→ Use `get_oe_report_certified`

When the user asks about **OE report / not certified / WCNP not-certified data**:
→ Use `get_oe_report_not_certified`

## Important Notes

1. OE report tools accept `tr_product` and `apm_id` as optional filters
2. Use "All" (the default) to retrieve unfiltered data
3. App inventory and metadata tools take no parameters
