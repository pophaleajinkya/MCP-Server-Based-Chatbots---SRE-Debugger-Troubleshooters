"""
Signal MCP Server.

Exposes Signal app inventory, metadata, and OE report capabilities as MCP
tools for use by any MCP-compatible agent (Google ADK, Claude, Cursor, etc.).
No LLM is bundled here — the intelligence lives in the consuming agent.

Design philosophy — same as o2_mcp / valid8_mcp (70% prompt / 30% tool):
  Tools call Signal APIs and return structured data.
  Tool descriptions and the AGENT.md resource teach the agent how to
  select the right tool and interpret results.

Authentication:
  Signal APIs require no API key — requests use accept: application/json.

Agent workflow:
  1. Read signal://agent-guide to understand available tools
  2. Call the appropriate tool (e.g. get_app_inventory_suggestions,
     get_oe_report_certified)

Project layout:
  src/providers/resources.py        — signal:// MCP resources (agent guide, API ref)
  src/providers/inventory_tools.py  — get_app_inventory_suggestions
  src/providers/metadata_tools.py   — get_app_metadata_filters
  src/providers/oe_report_tools.py  — get_oe_report_certified,
                                      get_oe_report_not_certified
  src/providers/_shared.py          — shared helpers: singleton client/service, doc cache

  data/resources/                   — static .md docs served as signal:// resources
  data/prompts/                     — prompt templates

Run:
    python -m src.server          # stdio (default for MCP)
    fastmcp run src/server.py     # same, via fastmcp CLI
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from src.config import get_settings
from src.providers import inventory_tools, metadata_tools, oe_report_tools, resources
from src.utils.logging import get_logger, setup_logging

load_dotenv()
setup_logging(os.environ.get("SIGNAL_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

mcp = FastMCP("signal")

mcp.add_provider(resources.provider)
mcp.add_provider(inventory_tools.provider)
mcp.add_provider(metadata_tools.provider)
mcp.add_provider(oe_report_tools.provider)


def main() -> None:
    """Run the MCP server via stdio transport (standard for MCP)."""
    cfg = get_settings()
    logger.info(
        "Starting Signal MCP Server | base_url=%s",
        cfg.signal_base_url,
    )
    mcp.run()


if __name__ == "__main__":
    main()
