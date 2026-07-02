"""Custom exception hierarchy and FastAPI exception handlers."""

from fastapi import Request
from fastapi.responses import JSONResponse


# ── Domain exceptions ─────────────────────────────────────────────────────────

class AgentBaseError(Exception):
    """Root exception for all agent-related errors."""


class MCPConnectionError(AgentBaseError):
    """MCP server could not be reached, or the session was lost."""


class MCPToolError(AgentBaseError):
    """An MCP tool call failed even after an automatic reconnect."""


class LLMError(AgentBaseError):
    """LLM gateway returned a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        """Initialise with the upstream HTTP status code and error detail.

        Args:
            status_code: The HTTP status code returned by the LLM gateway.
            detail: A short description of the error, typically the first 500
                characters of the gateway's response body.
        """
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AgentError(AgentBaseError):
    """The agentic loop encountered an unrecoverable error."""


# ── FastAPI exception handlers ────────────────────────────────────────────────

async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    """Translate an ``LLMError`` into a 502 Bad Gateway JSON response.

    Surfaces the upstream gateway's status code and message so callers can
    distinguish LLM-side failures from application bugs.

    Args:
        request: The incoming FastAPI request (required by the handler signature).
        exc: The ``LLMError`` instance carrying the upstream status code and detail.

    Returns:
        A ``JSONResponse`` with HTTP 502 and a structured error body.
    """
    return JSONResponse(
        status_code=502,
        content={
            "error": "llm_error",
            "detail": exc.detail,
            "llm_status_code": exc.status_code,
        },
    )


async def agent_error_handler(request: Request, exc: AgentError) -> JSONResponse:
    """Translate an ``AgentError`` into a 500 Internal Server Error JSON response.

    Catches unrecoverable failures in the agentic loop and returns a
    consistent error envelope rather than an unhandled exception trace.

    Args:
        request: The incoming FastAPI request (required by the handler signature).
        exc: The ``AgentError`` instance with the error description.

    Returns:
        A ``JSONResponse`` with HTTP 500 and a structured error body.
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": "agent_error",
            "detail": str(exc),
        },
    )


async def mcp_connection_error_handler(request: Request, exc: MCPConnectionError) -> JSONResponse:
    """Translate an ``MCPConnectionError`` into a 503 Service Unavailable JSON response.

    When one or more MCP servers are down or unreachable, this handler returns
    a user-friendly message instead of exposing raw connection error tracebacks.

    Args:
        request: The incoming FastAPI request (required by the handler signature).
        exc: The ``MCPConnectionError`` with a user-friendly description.

    Returns:
        A ``JSONResponse`` with HTTP 503 and a structured error body.
    """
    return JSONResponse(
        status_code=503,
        content={
            "error": "mcp_connection_error",
            "detail": str(exc),
        },
    )
