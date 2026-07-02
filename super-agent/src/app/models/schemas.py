"""Pydantic request / response schemas for all API endpoints."""

import uuid

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Incoming payload for the ``POST /query`` endpoint.

    ``session_id`` is optional — a UUID is auto-generated when omitted, enabling
    stateless single-turn calls.  Supply the same value across turns to maintain
    conversation history.  ``user_id`` is optional in the body — the router
    also accepts the caller's identity via the ``loginId`` or
    ``wm_llm_gw.user_name`` request headers.  A 422 is returned when none of
    those sources supplies a value, ensuring sessions are never silently stored
    under a shared "admin" bucket.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Natural language question for the WCNP health agent.",
    )
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        min_length=1,
        max_length=256,
        description="Session identifier. Auto-generated UUID if omitted; supply the same value across turns to maintain conversation history.",
    )
    user_id: str | None = Field(
        default=None,
        max_length=512,
        description="Caller identity (e.g. loginId). Also accepted via loginId or wm_llm_gw.user_name request headers. Omitting all three returns HTTP 422.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "Check health of namespace intl-sre",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "jane.doe@walmart.com",
            }
        }
    }


class QueryResponse(BaseModel):
    """Response envelope returned by the ``POST /query`` endpoint.

    Packages the agent's natural language answer together with the session ID
    so callers can correlate requests and responses in distributed tracing.
    """

    response: str = Field(..., description="Agent's natural language answer.")
    session_id: str = Field(..., description="Session identifier for this request.")


class MCPServerInfo(BaseModel):
    """Lightweight summary of a single connected MCP server.

    Used inside ``HealthResponse`` to let operators verify which tool servers
    the agent has successfully connected to at runtime.
    """

    name: str
    url: str


class HealthResponse(BaseModel):
    """Full capability snapshot returned by the ``GET /health`` endpoint.

    Aggregates service health, version, active LLM details, and the list of
    MCP servers and tools so that monitoring systems and operators have a
    single endpoint to inspect the agent's current state.
    """

    status: str
    version: str
    active_llm: str
    llm_endpoint: str
    mcp_servers: list[MCPServerInfo]
    mcp_tools: list[str]
