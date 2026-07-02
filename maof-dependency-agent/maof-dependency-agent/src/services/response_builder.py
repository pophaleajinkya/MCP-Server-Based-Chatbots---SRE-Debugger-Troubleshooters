"""Helper functions for building agent responses."""
from typing import Dict, Any, Optional
from src.models.query import QueryRequest
from src.models.agent_response import AgentResponse


def create_error_response(request: QueryRequest, error: str) -> AgentResponse:
    """Create an error AgentResponse."""
    return AgentResponse(
        status="error",
        query=request.query,
        data=None,
        error=error
    )


def build_data_payload(success: bool, tool_results) -> Optional[Dict[str, Any]]:
    """Return the raw data from the tool result as-is — no fields are renamed or removed."""
    if not success or not tool_results:
        return None

    tool_result = tool_results[0]
    data = tool_result.data or {}
    if not data:
        return None

    result_data: Dict[str, Any] = {}

    # App / namespace identity
    if data.get("appName"):
        result_data["appName"] = data["appName"]
    if data.get("namespace"):
        result_data["namespace"] = data["namespace"]

    # Raw SRE-OPS dependency lists — use exactly the keys set by query_processor
    if "dependencies" in data:
        result_data["dependencies"] = data["dependencies"] or []
        result_data["totalCount"] = data.get("total_count", len(result_data["dependencies"]))
        result_data["sourceBreakdown"] = data.get("sourceBreakdown") or {}

    if "upstream_dependencies" in data and data["upstream_dependencies"] is not None:
        result_data["upstreamDependencies"] = data["upstream_dependencies"]

    if "downstream_dependencies" in data and data["downstream_dependencies"] is not None:
        result_data["downstreamDependencies"] = data["downstream_dependencies"]

    # Only include direction when there is actual dependency data
    if result_data:
        result_data["direction"] = data.get("direction") or "both"

    # Available apps (namespace-only queries)
    if data.get("available_apps"):
        result_data["availableApps"] = data["available_apps"]
        result_data["totalApps"] = len(result_data["availableApps"])


    return result_data if result_data else None


