"""
OpenObserve MCP Server.

Exposes OpenObserve capabilities as MCP tools for use by any MCP-compatible
agent (Google ADK, Claude, Cursor, etc.).  No LLM is bundled here — the
intelligence lives in the consuming agent.

Design philosophy — 70% prompt / 30% tool:
  Tools collect data and run checks.
  Tool *descriptions* and the AGENT.md resource teach the agent how to
  translate user questions into SQL, interpret results, and decide what
  to do next.  A rich description IS the prompt.

Stateless design:
  Every tool that talks to OpenObserve accepts endpoint, bearer_token,
  organization, and stream directly as parameters.  No session state is
  stored server-side.  The super-agent owns all session management.

Agent workflow for log/error questions:
  1. health_mcp  → wcnp_get_o2_config(namespace, app)
                    returns endpoint, stream, organization, cluster_lb, default_filter
  2. super-agent → pingfed_playwright_token(cluster_lb)
                    returns bearer_token
  3. o2_mcp      → get_stream_schema(endpoint, stream, bearer_token, ...)
  4. o2_mcp      → validate_sql_policy(sql)   [no network — always first]
  5. o2_mcp      → execute_sql(sql_query, endpoint, stream, bearer_token, ...)
  6. If auth_expired → pingfed_playwright_token again → retry with new token

Project layout:
  src/providers/resources.py   — o2:// MCP resources (static docs + retry prompt)
  src/providers/query.py       — execute_sql, search_around, get_field_values,
                                  get_stream_schema, list_streams
  src/providers/validation.py  — validate_sql_policy, validate_sql, validate_vrl
  src/providers/sql_tools.py   — validate_sql_functions, check_sql_function,
                                  get_sql_correction_hint, get_o2_rules, search_docs
  src/providers/utils.py       — get_time
  src/providers/_shared.py     — shared helpers: build_service, read_doc, path constants

  data/resources/              — static .md docs served as o2:// resources
  data/prompts/                — prompt templates (retry_guide.md)
  data/rules.json              — O2 SQL/VRL rules loaded by get_o2_rules
  data/sql_functions.json      — function registry loaded by validate_sql_functions

Run:
    python -m src.server          # stdio (default for MCP)
    fastmcp run src/server.py     # same, via fastmcp CLI
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from src.config import get_settings
from src.providers import query, resources, sql_tools, utils, validation
from src.utils.logging import get_logger, setup_logging

load_dotenv()
setup_logging(os.environ.get("O2_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

# stateless_http=True is passed at runtime via FASTMCP_STATELESS_HTTP=1 env var
# or by calling mcp.http_app(stateless_http=True) in the ASGI app entrypoint.
mcp = FastMCP("openobserve")

mcp.add_provider(resources.provider)
mcp.add_provider(query.provider)
mcp.add_provider(validation.provider)
mcp.add_provider(sql_tools.provider)
mcp.add_provider(utils.provider)


def main() -> None:
    """Run the MCP server via stdio transport (standard for MCP)."""
    cfg = get_settings()
    logger.info(
        "Starting OpenObserve MCP Server | endpoint=%s org=%s",
        cfg.endpoint or "not configured",
        cfg.org_id,
    )
    mcp.run()


if __name__ == "__main__":
    main()
