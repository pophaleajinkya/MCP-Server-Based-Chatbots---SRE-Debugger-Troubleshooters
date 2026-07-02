"""Query processor for the /dependencies/oneops endpoint."""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from src.models.query import ToolPayload, ToolResult
from src.agent.agent import dependency_agent

logger = logging.getLogger(__name__)


class OneOpsQueryProcessor:
    """Process OneOps queries using the shared DependencyAgent."""

    @staticmethod
    async def process_query(
        query: str,
        session_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[ToolPayload, List[ToolResult]]:
        logger.info(f"[{session_id}] OneOps: processing query")
        start_time = time.time()

        try:
            result = await dependency_agent.process_query(
                query, session_id, query_type="oneops", conversation_history=conversation_history
            )
            execution_time = (time.time() - start_time) * 1000

            payload = ToolPayload(
                toolName="get_oneops_dependencies",
                appName=result.get("platform"),
                namespace=result.get("assembly"),
                parameters={
                    "org": result.get("org"),
                    "platform": result.get("platform"),
                    "assembly": result.get("assembly"),
                    "direction": result.get("direction"),
                },
            )

            if result.get("success"):
                tool_result = ToolResult(
                    toolName="get_oneops_dependencies",
                    success=True,
                    data={
                        "org": result.get("org"),
                        "platform": result.get("platform"),
                        "assembly": result.get("assembly"),
                        "direction": result.get("direction"),
                        "dependencies": result.get("dependencies", []),
                        "upstreamDependencies": result.get("upstream_dependencies"),
                        "downstreamDependencies": result.get("downstream_dependencies"),
                        "totalCount": result.get("total_count", 0),
                        "sourceBreakdown": result.get("source_breakdown", {}),
                        "messages": result.get("messages", []),
                    },
                    error=None,
                    executionTimeMs=execution_time,
                )
            else:
                tool_result = ToolResult(
                    toolName="get_oneops_dependencies",
                    success=False,
                    data=None,
                    error=result.get("error", "Unknown error"),
                    executionTimeMs=execution_time,
                )

            return payload, [tool_result]

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"[{session_id}] OneOps agent error: {e}")
            payload = ToolPayload(toolName="get_oneops_dependencies", appName=None, namespace=None, parameters={})
            tool_result = ToolResult(
                toolName="get_oneops_dependencies", success=False, data=None,
                error=str(e), executionTimeMs=execution_time,
            )
            return payload, [tool_result]
