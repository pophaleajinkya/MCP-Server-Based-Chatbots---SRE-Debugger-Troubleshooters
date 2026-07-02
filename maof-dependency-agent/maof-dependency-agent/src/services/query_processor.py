"""Query processor for the /dependencies (WCNP) endpoint."""
import logging
import time
from typing import List, Tuple, Dict, Any, Optional

from src.models.query import ToolPayload, ToolResult
from src.agent.agent import dependency_agent

logger = logging.getLogger(__name__)


class QueryProcessor:
    """Process WCNP queries using the shared DependencyAgent."""

    @staticmethod
    async def process_query(
        query: str,
        session_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[ToolPayload, List[ToolResult]]:
        logger.info(f"[{session_id}] WCNP: processing query")
        start_time = time.time()

        try:
            result = await dependency_agent.process_query(
                query, session_id, query_type="wcnp", conversation_history=conversation_history
            )
            execution_time = (time.time() - start_time) * 1000

            payload = ToolPayload(
                toolName="get_app_dependencies",
                appName=result.get("app_name"),
                namespace=result.get("namespace"),
                parameters={},
            )

            if result.get("success"):
                tool_result = ToolResult(
                    toolName="get_app_dependencies",
                    success=True,
                    data={
                        "appName": result.get("app_name"),
                        "namespace": result.get("namespace"),
                        "direction": result.get("direction"),
                        "dependencies": result.get("dependencies", []),
                        "upstream_dependencies": result.get("upstream_dependencies"),
                        "downstream_dependencies": result.get("downstream_dependencies"),
                        "total_count": result.get("total_count", len(result.get("dependencies", []))),
                        "sourceBreakdown": result.get("source_breakdown", {}),
                        "available_apps": result.get("available_apps"),
                        "messages": result.get("messages", []),
                    },
                    error=None,
                    executionTimeMs=execution_time,
                )
            else:
                tool_result = ToolResult(
                    toolName="get_app_dependencies",
                    success=False,
                    data=None,
                    error=result.get("error", "Unknown error"),
                    executionTimeMs=execution_time,
                )

            return payload, [tool_result]

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"[{session_id}] WCNP agent error: {e}")
            payload = ToolPayload(toolName="get_app_dependencies", appName=None, namespace=None, parameters={})
            tool_result = ToolResult(
                toolName="get_app_dependencies", success=False, data=None,
                error=str(e), executionTimeMs=execution_time,
            )
            return payload, [tool_result]
