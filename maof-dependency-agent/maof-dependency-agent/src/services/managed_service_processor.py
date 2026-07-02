"""Query processor for the /dependencies/managed-service endpoint."""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from src.models.query import ToolPayload, ToolResult
from src.agent.agent import dependency_agent

logger = logging.getLogger(__name__)


class ManagedServiceQueryProcessor:
    """Process Managed Service queries using the shared DependencyAgent."""

    @staticmethod
    async def process_query(
        query: str,
        session_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[ToolPayload, List[ToolResult]]:
        logger.info(f"[{session_id}] ManagedService: processing query")
        start_time = time.time()

        try:
            result = await dependency_agent.process_query(
                query, session_id, query_type="managed_service", conversation_history=conversation_history
            )
            execution_time = (time.time() - start_time) * 1000

            payload = ToolPayload(
                toolName="get_managed_service_dependencies",
                appName=result.get("service_type"),
                namespace=result.get("assembly") or result.get("resource_group"),
                parameters={
                    "serviceType": result.get("service_type"),
                    "assembly": result.get("assembly"),
                    "platform": result.get("platform"),
                    "resourceGroup": result.get("resource_group"),
                    "subscriptionId": result.get("subscription_id"),
                    "databaseName": result.get("database_name"),
                },
            )

            if result.get("success"):
                tool_result = ToolResult(
                    toolName="get_managed_service_dependencies",
                    success=True,
                    data={
                        "serviceType": result.get("service_type"),
                        "assembly": result.get("assembly"),
                        "platform": result.get("platform"),
                        "resourceGroup": result.get("resource_group"),
                        "subscriptionId": result.get("subscription_id"),
                        "databaseName": result.get("database_name"),
                        "dependencies": result.get("dependencies", []),
                        "totalCount": result.get("total_count", 0),
                        "sourceBreakdown": result.get("source_breakdown", {}),
                        "messages": result.get("messages", []),
                    },
                    error=None,
                    executionTimeMs=execution_time,
                )
            else:
                tool_result = ToolResult(
                    toolName="get_managed_service_dependencies",
                    success=False,
                    data=None,
                    error=result.get("error", "Unknown error"),
                    executionTimeMs=execution_time,
                )

            return payload, [tool_result]

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"[{session_id}] ManagedService agent error: {e}")
            payload = ToolPayload(
                toolName="get_managed_service_dependencies", appName=None, namespace=None, parameters={}
            )
            tool_result = ToolResult(
                toolName="get_managed_service_dependencies", success=False, data=None,
                error=str(e), executionTimeMs=execution_time,
            )
            return payload, [tool_result]
