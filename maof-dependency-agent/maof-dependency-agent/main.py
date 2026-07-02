"""Main FastAPI application with MAOF and LangGraph integration."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from maof_agent_kit import maof, agent_version, create_openapi_metadata_router, register_agent
from src.mcp_server.server import mcp

# Eagerly initialise the streamable-HTTP sub-app so mcp.session_manager is
# available before the FastAPI lifespan starts.
_mcp_sub_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the MCP StreamableHTTP session manager alongside the main app."""
    async with mcp.session_manager.run():
        yield

from src.models.query import QueryRequest
from src.models.agent_response import AgentResponse
from src.services.query_processor import QueryProcessor
from src.services.oneops_service import OneOpsQueryProcessor
from src.services.managed_service_processor import ManagedServiceQueryProcessor
from src.services.response_builder import create_error_response, build_data_payload
from src.services.conversation_history import get_conversation_history

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Dependency Agent API",
    description="Agent to fetch dependencies from different sources and return unique dependencies.",
    version="0.1.0",
    lifespan=lifespan,
)

register_agent(
    agent_name="dependency_agent",
    description="""Parses the query using LLM to extract app_name and namespace
                    Routes based on extracted parameters:
                       - Both app_name and namespace → fetch dependencies
                       - Only namespace → suggest dependencies (return list of apps)
                       - Neither → return error
                    Executes the appropriate action
                    Returns structured results in AgentResponse format""",
    version="1.0.0"
)(app)

# Mount MCP server at /mcp — streamable_http_path="/" means endpoint is POST /mcp/ (Istio-friendly)
app.mount("/mcp", _mcp_sub_app)

@maof
@app.post("/dependencies",
          response_model=AgentResponse,
          summary="""Parses the query using LLM to extract app_name and namespace
                    Routes based on extracted parameters:
                       - Both app_name and namespace → fetch dependencies
                       - Only namespace → suggest dependencies (return list of apps)
                       - Neither → return error
                    Executes the appropriate action
                    Returns structured results in AgentResponse format""",
          )
@agent_version("1.0.0")
async def process_query_endpoint(request: QueryRequest):
    """
    Process a query with session ID using MAOF + LangGraph.

    This endpoint uses a LangGraph workflow that:
    1. Parses the query using LLM to extract app_name and namespace
    2. Routes based on extracted parameters:
       - Both app_name and namespace → fetch dependencies
       - Only namespace → suggest dependencies (return list of apps)
       - Neither → return error
    3. Executes the appropriate action
    4. Returns structured results in AgentResponse format

    Use Cases:
    - Given namespace only: Returns list of available apps to select from
    - Given namespace and app_name: Fetches and returns dependencies

    Expected query formats:
    - Natural language: "Get dependencies for payment-service in production"
    - Direct parameters: "appName=user-api namespace=staging"
    - Context string: Agent response format with parameters
    """
    try:
        logger.info(f"[{request.session_id}] Received query request")

        # Retrieve conversation history from HTTP API using session_id
        logger.info(f"[{request.session_id}] Retrieving conversation history from API...")
        conversation_history = await get_conversation_history(
            session_id=request.session_id,
            limit=5
        )

        # Process query using LangGraph agent workflow with conversation history
        _, tool_results = await QueryProcessor.process_query(
            request.query,
            request.session_id,
            conversation_history
        )

        success = all(result.success for result in tool_results)

        # Build data payload with actual API responses
        data_payload = build_data_payload(success, tool_results)

        # Get error if any
        error = tool_results[0].error if tool_results and not success else None

        # Create AgentResponse with API response data (no response field - summarization handled in Redis)
        agent_response = AgentResponse(
            status="success" if success else "error",
            query=request.query,
            data=data_payload,  # Include actual API responses
            error=error
        )

        logger.info(f"[{request.session_id}] Query processed successfully: {success}")
        return agent_response

    except Exception as e:
        logger.error(f"[{request.session_id}] Error processing query: {e}", exc_info=True)
        return create_error_response(request, str(e))


@maof
@app.post(
    "/dependencies/oneops",
    response_model=AgentResponse,
    summary="Fetch OneOps application dependencies via LangGraph (no DX Console)",
)
@agent_version("1.0.0")
async def oneops_dependency_endpoint(request: QueryRequest):
    """
    Process a OneOps dependency query through the LangGraph agent workflow.

    The agent uses LLM to extract org / platform / assembly / direction from
    the natural-language query, then fetches dependencies from:
      - SRE-OPS  : app_name = platform, namespace = assembly
      - Topology : tenant = org, deployment = platform, namespace = assembly

    DX Console is NOT called for this endpoint.

    Example query:
      "upstream dependencies for org=walmart-ecomm platform=pay-platform assembly=payments-prod"
    """
    try:
        logger.info(f"[{request.session_id}] OneOps: received query request")

        conversation_history = await get_conversation_history(
            session_id=request.session_id,
            limit=5,
        )

        _, tool_results = await OneOpsQueryProcessor.process_query(
            request.query,
            request.session_id,
            conversation_history,
        )

        success = all(r.success for r in tool_results)
        data = tool_results[0].data if tool_results and success else None
        error = tool_results[0].error if tool_results and not success else None

        logger.info(f"[{request.session_id}] OneOps: processed successfully: {success}")
        return AgentResponse(
            status="success" if success else "error",
            query=request.query,
            data=data,
            error=error,
        )

    except Exception as e:
        logger.error(f"[{request.session_id}] OneOps error: {e}", exc_info=True)
        return AgentResponse(
            status="error",
            query=request.query,
            data=None,
            error=str(e),
        )


@maof
@app.post(
    "/dependencies/managed-service",
    response_model=AgentResponse,
    summary="Fetch upstream dependencies for a managed service (Cassandra/MeghaCache/Cosmos/SQL)",
)
@agent_version("1.0.0")
async def managed_service_dependency_endpoint(request: QueryRequest):
    """
    Fetch upstream dependencies for a managed service via LangGraph.

    The agent extracts serviceType and its required params from the natural-language query:

    **Cassandra / MeghaCache** — include in query:
      - serviceType: "cassandra" or "meghacache"
      - assembly
      - platform

    **Cosmos / SQL** — include in query:
      - serviceType: "cosmos" or "sqlserver"
      - resourceGroup
      - subscriptionId
      - databaseName

    Only SRE-OPS upstream is called. No Topology or DX Console.

    Example queries:
      "upstream dependencies for cassandra assembly=mx-rms platform=rmsag2"
      "cosmos dependencies resourceGroup=my-rg subscriptionId=sub-123 databaseName=orders-db"
    """
    try:
        logger.info(f"[{request.session_id}] ManagedService: received query request")

        conversation_history = await get_conversation_history(
            session_id=request.session_id,
            limit=5,
        )

        _, tool_results = await ManagedServiceQueryProcessor.process_query(
            request.query,
            request.session_id,
            conversation_history,
        )

        success = all(r.success for r in tool_results)
        data = tool_results[0].data if tool_results and success else None
        error = tool_results[0].error if tool_results and not success else None

        logger.info(f"[{request.session_id}] ManagedService: processed successfully: {success}")
        return AgentResponse(
            status="success" if success else "error",
            query=request.query,
            data=data,
            error=error,
        )

    except Exception as e:
        logger.error(f"[{request.session_id}] ManagedService error: {e}", exc_info=True)
        return AgentResponse(
            status="error",
            query=request.query,
            data=None,
            error=str(e),
        )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Dependency Agent API",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/health/liveness")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

@app.get("/health/readiness")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

app.include_router(create_openapi_metadata_router(app))


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run maof-dependency-agent server")
    parser.add_argument(
        "--port", type=int, default=8013, help="Port to run the agent server on"
    )
    args = parser.parse_args()

    uvicorn.run("main:app", host="0.0.0.0", port=args.port, reload=False)

