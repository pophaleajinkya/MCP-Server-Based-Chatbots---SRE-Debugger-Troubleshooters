"""Provider modules for the Signal MCP server.

Each module exposes a single `provider` (LocalProvider) instance
that is registered with the FastMCP server in src/server.py.

  resources        — signal:// MCP resources (agent guide, API reference)
  inventory_tools  — App inventory suggestions
  metadata_tools   — App metadata filters
  oe_report_tools  — OE report data (certified & not-certified)
"""
