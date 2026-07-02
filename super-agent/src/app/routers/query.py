"""Query endpoint — ADK-native agent interaction."""

import logging

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import QueryRequest, QueryResponse
from app.services.runner import run_agent

log = logging.getLogger(__name__)


def _resolve_user_id(req: QueryRequest, request: Request) -> str:
    """Return the effective user identity for this request.

    Resolution order:
      1. ``user_id`` field in the JSON body.
      2. ``loginId`` request header (set by the UI and MAOF proxy).
      3. ``wm_llm_gw.user_name`` request header (Walmart LLM Gateway).

    Raises HTTP 422 when none of the above is present so that sessions are
    never silently stored under a shared "admin" bucket.
    """
    uid = (
        req.user_id
        or request.headers.get("loginId")
        or request.headers.get("wm_llm_gw.user_name")
    )
    if not uid:
        raise HTTPException(
            status_code=422,
            detail=(
                "user_id is required. Supply it in the JSON body as 'user_id', "
                "or via the 'loginId' / 'wm_llm_gw.user_name' request header."
            ),
        )
    return uid

router = APIRouter(tags=["agent"])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Submit a natural language query to the WCNP health agent",
)
async def query(req: QueryRequest, request: Request) -> QueryResponse:
    """Run the ADK agentic loop for the given query and return the answer.

    The ADK framework handles the multi-round tool-use loop, MCP tool calls,
    and conversation history automatically via ``root_agent``.

    Args:
        req:     Incoming query payload with ``query`` text and optional ``session_id``.
        request: FastAPI request; provides access to ``app.state.runner``.

    Returns:
        ``QueryResponse`` with the agent's answer and the session ID.
    """
    session_id = req.session_id
    user_id    = _resolve_user_id(req, request)
    log.info("Query [%s/%s]: %s", user_id, session_id, req.query[:120])

    answer = await run_agent(request.app.state.runner, user_id, session_id, req.query)

    log.info("Response [%s/%s]: %d chars", user_id, session_id, len(answer))
    return QueryResponse(response=answer, session_id=session_id)


@router.post(
    "/query_api",
    response_model=QueryResponse,
    summary=(
        "WCNP Health Agent — provides detailed health reports for any Kubernetes namespace "
        "or namespace + app combination on WCNP clusters. Runs 17 parallel health checks "
        "across compute, mesh, pods, secrets, and configuration using live Prometheus data."
    ),
)
async def query_api(req: QueryRequest, request: Request) -> QueryResponse:
    """Alternate entry point for the WCNP health agent.

    Functionally identical to ``POST /query``.

    Args:
        req:     Incoming query payload with ``query`` text and optional ``session_id``.
        request: FastAPI request; provides access to ``app.state.runner``.

    Returns:
        ``QueryResponse`` with the agent's answer and the session ID.
    """
    session_id = req.session_id
    user_id    = _resolve_user_id(req, request)
    log.info("Query [%s/%s]: %s", user_id, session_id, req.query[:120])

    answer = await run_agent(request.app.state.runner, user_id, session_id, req.query)

    log.info("Response [%s/%s]: %d chars", user_id, session_id, len(answer))
    return QueryResponse(response=answer, session_id=session_id)
