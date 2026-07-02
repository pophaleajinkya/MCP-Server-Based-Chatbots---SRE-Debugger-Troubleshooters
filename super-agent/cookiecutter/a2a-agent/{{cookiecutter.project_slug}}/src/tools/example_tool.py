"""Example FunctionTool for {{cookiecutter.project_name}}.

Replace this with your real domain tools.
Each async function the ADK agent can call — ADK auto-wraps plain async
functions as FunctionTool.  The docstring IS the tool description shown to
the LLM — make it specific and actionable.
"""

import logging

log = logging.getLogger(__name__)


async def example_tool(query: str) -> str:
    """Perform an example operation for the given query.

    Use this tool when the user asks about <describe your domain here>.

    Args:
        query: The natural language query or identifier to process.

    Returns:
        A string containing the result of the operation.
    """
    # TODO: Replace with your actual implementation
    log.info("example_tool called: query=%r", query)
    return f"[example_tool] Result for: {query}"
