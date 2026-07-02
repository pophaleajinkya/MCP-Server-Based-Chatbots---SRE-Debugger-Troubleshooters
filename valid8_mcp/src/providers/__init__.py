"""Provider modules for the Valid8 MCP server.

Each module exposes a single `provider` (LocalProvider) instance
that is registered with the FastMCP server in src/server.py.

  resources     — valid8:// MCP resources (agent guide, API reference)
  ca_tools      — Canada tools: orchestrated query, OASIS config/progress
  mx_tools      — Mexico tools: item visibility, item status, order dashboard
  validate      — Entity validation: validate, validate_batch
"""
