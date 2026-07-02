"""MCP server definition for {{cookiecutter.project_name}}.

Uses the MCP Python SDK to expose tools, resources, and prompts over
Streamable HTTP — the transport super-agent expects by default.

Structure:
  Tools     → @mcp.tool()       — callable functions the LLM invokes
  Resources → @mcp.resource()   — data/documents the LLM can read
  Prompts   → @mcp.prompt()     — reusable workflow templates

The server is mounted at /mcp/ by the FastAPI app in main.py.
"""

import json
import logging
from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

# ── MCP server instance ───────────────────────────────────────────────────────

mcp = FastMCP(
    name="{{cookiecutter.server_name}}",
    version="{{cookiecutter.server_version}}",
)


# ── Tools ─────────────────────────────────────────────────────────────────────
# Add @mcp.tool() decorated async functions here.
#
# CRITICAL rules for tool compatibility with super-agent (Anthropic/Claude):
#   - inputSchema top-level type MUST be "object"
#   - Do NOT use "default" in parameter schemas
#   - Do NOT use "$ref", "definitions", "if"/"then"/"else"
#   - Tool names must be unique across ALL MCP servers connected to super-agent
#   - Descriptions must be specific: "Use when user asks about X"
#
# Return a JSON-serialisable dict or string.
# For rich UI: include chart_data, table_data, or grafana_url keys.

@mcp.tool()
async def example_tool(query: str) -> str:
    """Perform an example operation for {{cookiecutter.project_name}}.

    Use this tool when the user asks about <describe your domain here>.
    Returns a structured JSON response with the results.

    Args:
        query: The natural language query or identifier to process.
               Example: 'iro-prod' for a namespace, 'item-assembler' for an app.
    """
    # TODO: Replace with your real implementation
    log.info("[example_tool] query=%r", query)
    result = {
        "status": "ok",
        "query": query,
        "data": "Replace this with real domain data",
    }
    return json.dumps(result)


# ── Resources ─────────────────────────────────────────────────────────────────
# The agent guide is the most important resource — super-agent auto-discovers
# any resource whose URI ends with "://agent-guide" and injects it into the
# orchestrator LLM's system prompt.

@mcp.resource("{{cookiecutter.server_name}}://agent-guide")
async def agent_guide() -> str:
    """Domain knowledge guide for {{cookiecutter.project_name}}.

    super-agent injects this into the orchestrator LLM's system prompt at startup.
    Use it to:
      - Tell the LLM which tool to call for which scenario
      - List available prompt templates and when to use them
      - Document domain constraints (e.g. exact metric names for PromQL)
    """
    return """\
## {{cookiecutter.project_name}} — Tool Routing Guide

### Tools available

#### example_tool
- **When to use**: User asks about <your domain here>
- **Required args**: `query` — extract from the user's message
- **Returns**: JSON with `status`, `query`, and `data` fields

### Prompt templates

| Template | When to use |
|---|---|
| {{cookiecutter.server_name}}-workflow | TODO: describe this prompt |

### Domain constraints

- TODO: Add any domain-specific rules the LLM must follow
- Example: "NEVER guess Prometheus metric names — use exact names from the guide"
"""


# ── Prompts ───────────────────────────────────────────────────────────────────
# Prompts let you package reusable workflow instructions the agent loads on demand.
# The agent calls get_mcp_prompt("{{cookiecutter.server_name}}-workflow", {"arg": "value"}).

@mcp.prompt()
async def workflow_prompt(context: str = "") -> str:
    """Reusable workflow for {{cookiecutter.project_name}}.

    Args:
        context: Optional context to include in the workflow (e.g. namespace, app name).
    """
    return f"""\
## {{cookiecutter.project_name}} Workflow

{'Context: ' + context if context else ''}

### Steps

1. Call `example_tool` with the relevant query
2. Parse the `data` field from the response
3. Summarise the findings for the user

### Output format

Return a concise summary with:
- **Status**: ok / warning / error
- **Findings**: key data points
- **Recommendations**: what the user should do next
"""
