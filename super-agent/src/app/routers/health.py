"""Health and readiness endpoints."""

from fastapi import APIRouter, Request

from app.config import get_settings
from app.models.schemas import HealthResponse, MCPServerInfo
router = APIRouter(tags=["observability"])

_APP_VERSION = "2.0.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness + capability summary",
)
async def health(request: Request) -> HealthResponse:
    """Return the agent's current status, active LLM, and connected MCP tools.

    MCP server and tool metadata is populated at startup by probing the
    configured MCP server; the ADK Runner and ``root_agent`` handle all
    live tool calls at request time.
    """
    settings    = get_settings()
    mcp_servers = request.app.state.mcp_servers
    mcp_tools   = request.app.state.mcp_tools

    return HealthResponse(
        status="ok",
        version=_APP_VERSION,
        active_llm=settings.active_llm,
        llm_endpoint=settings.active_llm_endpoint,
        mcp_servers=[MCPServerInfo(name=s["name"], url=s["url"]) for s in mcp_servers],
        mcp_tools=mcp_tools,
    )


@router.get(
    "/ready",
    summary="Kubernetes readiness probe",
    status_code=200,
)
async def ready() -> dict[str, str]:
    """Lightweight readiness check — returns 200 when the server is up."""
    return {"status": "ready"}

@router.get(
    "/liveness",
    summary="Kubernetes liveness probe",
    status_code=200,
)
async def ready() -> dict[str, str]:
    """Lightweight liveness check — returns 200 when the server is up."""
    return {"status": "ok"}
