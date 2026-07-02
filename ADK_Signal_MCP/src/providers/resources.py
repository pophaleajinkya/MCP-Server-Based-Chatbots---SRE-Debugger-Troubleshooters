"""MCP Resources — static documentation served as signal:// URIs.

Resources:
  signal://agent-guide       Full agent guide: workflow, tool selection
  signal://api-reference     Signal API reference with request/response examples
"""
from __future__ import annotations

from fastmcp.server.providers import LocalProvider

from src.providers._shared import AGENT_GUIDE, API_REFERENCE, read_doc

provider = LocalProvider()


@provider.resource("signal://agent-guide")
def agent_guide() -> str:
    """
    Signal agent guide: full workflow, tool selection, and response format
    documentation.

    Read this resource at session start to understand how to use Signal
    tools for app inventory, metadata, and OE reports.
    """
    return read_doc(
        AGENT_GUIDE,
        "Agent guide not found. See data/resources/AGENT.md.",
    )


@provider.resource("signal://api-reference")
def api_reference() -> str:
    """
    Signal API reference — all endpoints with request/response examples.

    Read this when you need to understand:
    - Exact request payload formats for each Signal API
    - Expected response structures
    - Available filter options for OE reports
    """
    return read_doc(
        API_REFERENCE,
        "API reference not found. See data/resources/api_reference.md.",
    )


@provider.prompt("signal_usage")
def signal_usage_prompt() -> str:
    """
    Quick reference for selecting the right Signal tool based on user intent.

    Use this prompt when you need guidance on which tool to call for a
    given user question about app inventory, metadata, or OE reports.
    """
    from src.providers._shared import _PROMPTS_DIR

    prompt_path = _PROMPTS_DIR / "signal_guide.md"
    return read_doc(
        prompt_path,
        "Signal usage guide not found. See data/prompts/signal_guide.md.",
    )
