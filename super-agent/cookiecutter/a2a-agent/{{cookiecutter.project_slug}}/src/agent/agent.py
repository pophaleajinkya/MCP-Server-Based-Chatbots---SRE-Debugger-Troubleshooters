"""ADK Agent for {{cookiecutter.project_name}}.

Add your tools and system instruction here.
"""

import logging
from contextlib import AsyncExitStack

import litellm
litellm.ssl_verify = False

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

from src.config import get_settings

log = logging.getLogger(__name__)

_s = get_settings()

# ── LLM setup ────────────────────────────────────────────────────────────────

_claude_base = _s.claude_gateway_url.removesuffix("/v1/messages").removesuffix("/messages")
_llm = LiteLlm(
    model=f"anthropic/{_s.claude_model}",
    api_key=_s.claude_api_key,
    api_base=_claude_base,
    extra_headers={"anthropic-version": _s.claude_anthropic_version},
)

# ── System instruction ───────────────────────────────────────────────────────
# TODO: Customize this with your agent's domain knowledge.

_INSTRUCTION = """\
You are {{cookiecutter.agent_description}}.

Use the available tools to answer every question accurately.
Call tools immediately — never ask for confirmation before using a tool.
If you cannot answer, say so honestly.
"""

# ── Agent factory ─────────────────────────────────────────────────────────────

async def create_agent() -> tuple[Agent, AsyncExitStack]:
    """Build the ADK Agent with all registered tools.

    Returns:
        (agent, exit_stack) — call ``await exit_stack.aclose()`` on shutdown.
    """
    exit_stack = AsyncExitStack()
    tools = []

    # ── TODO: Add MCP toolsets ────────────────────────────────────────────────
    # from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StreamableHTTPConnectionParams
    # mcp_toolset = MCPToolset(connection_params=StreamableHTTPConnectionParams(url="http://..."))
    # mcp_tools = await exit_stack.enter_async_context(mcp_toolset)
    # tools.extend(mcp_tools)

    # ── TODO: Add custom FunctionTools ───────────────────────────────────────
    # from src.tools.my_tool import my_tool_function
    # tools.append(my_tool_function)

    agent = Agent(
        model=_llm,
        name="{{cookiecutter.agent_name}}",
        description="{{cookiecutter.agent_description}}",
        instruction=_INSTRUCTION,
        tools=tools,
    )

    return agent, exit_stack
