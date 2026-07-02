"""MCP Resources — static documentation served as valid8:// URIs.

Resources:
  valid8://agent-guide       Full agent guide: workflow, tool selection
  valid8://api-reference     Valid8 API reference with request/response examples
"""
from __future__ import annotations

from fastmcp.server.providers import LocalProvider

from src.providers._shared import AGENT_GUIDE, API_REFERENCE, read_doc

provider = LocalProvider()


@provider.resource("valid8://agent-guide")
def agent_guide() -> str:
    """
    Valid8 agent guide: full workflow, tool selection, and response format
    documentation.

    Read this resource at session start to understand how to use Valid8
    tools for Canada (CA) and Mexico (MX) validation and data retrieval.
    """
    return read_doc(
        AGENT_GUIDE,
        "Agent guide not found. See data/resources/AGENT.md.",
    )


@provider.resource("valid8://api-reference")
def api_reference() -> str:
    """
    Valid8 API reference — all endpoints with request/response examples.

    Read this when you need to understand:
    - Exact request payload formats for each Valid8 API
    - Expected response structures
    - Available banner codes, SKU formats, and time frame options
    """
    return read_doc(
        API_REFERENCE,
        "API reference not found. See data/resources/api_reference.md.",
    )


@provider.prompt("valid8_usage")
def valid8_usage_prompt() -> str:
    """
    Quick reference for selecting the right Valid8 tool based on user intent.

    Use this prompt when you need guidance on which tool to call for a
    given user question about CA/MX validation or data retrieval.
    """
    from src.providers._shared import _PROMPTS_DIR

    prompt_path = _PROMPTS_DIR / "valid8_guide.md"
    return read_doc(
        prompt_path,
        "Valid8 usage guide not found. See data/prompts/valid8_guide.md.",
    )
