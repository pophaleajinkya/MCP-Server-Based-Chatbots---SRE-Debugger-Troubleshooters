"""
Valid8 MCP Server.

Exposes Valid8 validation and data retrieval capabilities as MCP tools
for use by any MCP-compatible agent (Google ADK, Claude, Cursor, etc.).
No LLM is bundled here — the intelligence lives in the consuming agent.

Design philosophy — same as o2_mcp (70% prompt / 30% tool):
  Tools call Valid8 APIs and return structured data.
  Tool descriptions and the AGENT.md resource teach the agent how to
  select the right tool and interpret results.

Authentication:
  Valid8 APIs are authenticated via X-API-Key and X-Tenant headers.
  The API key is configured via VALID8_API_KEY env var. The tenant
  (ca / mx) is determined per-request based on the market.

Agent workflow:
  1. Read valid8://agent-guide to understand available tools
  2. Call the appropriate tool (e.g. ca_orchestrated_query, mx_item_status)

Project layout:
  src/providers/resources.py   — valid8:// MCP resources (agent guide, API ref)
  src/providers/ca_tools.py    — ca_orchestrated_query
  src/providers/mx_tools.py    — mx_item_visibility_lookup_upc, mx_item_status,
                                  mx_order_dashboard_search
  src/providers/_shared.py     — shared helpers: singleton client/service, doc cache

  data/resources/              — static .md docs served as valid8:// resources
  data/prompts/                — prompt templates

Run:
    python -m src.server          # stdio (default for MCP)
    fastmcp run src/server.py     # same, via fastmcp CLI
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from src.config import get_settings
from src.providers import ca_tools, mx_tools, resources
from src.utils.logging import get_logger, setup_logging

load_dotenv()
setup_logging(os.environ.get("VALID8_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

mcp = FastMCP("valid8")

mcp.add_provider(resources.provider)
mcp.add_provider(ca_tools.provider)
mcp.add_provider(mx_tools.provider)


def main() -> None:
    """Run the MCP server via stdio transport (standard for MCP)."""
    cfg = get_settings()
    logger.info(
        "Starting Valid8 MCP Server | base_url=%s api_key=%s",
        cfg.valid8_base_url,
        "***" if cfg.valid8_api_key else "<not set>",
    )
    mcp.run()


if __name__ == "__main__":
    main()
