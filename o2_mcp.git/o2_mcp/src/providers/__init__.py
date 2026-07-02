"""Provider modules for the OpenObserve MCP server.

Each module exposes a single `provider` (LocalProvider) instance
that is registered with the FastMCP server in src/server.py.

  resources   — o2:// MCP resources (static docs + retry prompt template)
  query       — execute_sql, search_around, get_field_values, get_stream_schema, list_streams
  validation  — validate_sql_policy, validate_sql, validate_vrl
  sql_tools   — validate_sql_functions, check_sql_function,
                get_sql_correction_hint, get_o2_rules, search_docs
  utils       — get_time
"""
