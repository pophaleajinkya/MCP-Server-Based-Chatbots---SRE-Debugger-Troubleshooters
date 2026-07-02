"""MCP tools for WCNP (Kubernetes) — thin, structured, no internal LLM.

Tools take explicit parameters extracted by the client LLM (ADK/Claude/etc).
Intelligence stays on the client — these tools are pure service calls.
"""
import logging

from src.mcp_server.server import mcp
from src.services.wcnp_service import get_apps_for_namespace
from src.services.merge_service import get_upstream_and_downstream_dependencies

logger = logging.getLogger(__name__)


@mcp.tool(
    name="list_apps_in_namespace",
    description=(
        "List all applications available in a WCNP (Kubernetes) namespace from DX Console.\n"
        "Use this FIRST when the user provides only a namespace (no app name).\n"
        "Returns the list of apps so the user can pick one before fetching dependencies.\n"
        "Parameter:\n"
        "  namespace — Kubernetes namespace (e.g. 'iro-async', 'atlas-inventory-crons', 'prod')"
    ),
)
async def list_apps_in_namespace(namespace: str) -> dict:
    """Return all app names in a WCNP namespace — thin DX Console call, no LLM."""
    logger.info(f"MCP tool: list_apps_in_namespace namespace={namespace}")
    return await get_apps_for_namespace(namespace)


@mcp.tool(
    name="fetch_wcnp_upstream_dependencies",
    description=(
        "Fetch UPSTREAM dependencies for a WCNP (Kubernetes) application.\n"
        "Upstream = services that call INTO this app (its callers / consumers).\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Use when you already know both app_name AND namespace.\n"
        "If you only have a namespace, use list_apps_in_namespace first.\n"
        "Parameters:\n"
        "  app_name  — application/deployment name (e.g. 'payment-service', 'item-read-service-prod2-tg2')\n"
        "  namespace — Kubernetes namespace (e.g. 'iro-async', 'prod', 'atlas-inventory-crons')"
    ),
)
async def fetch_wcnp_upstream_dependencies(app_name: str, namespace: str) -> dict:
    """Fetch upstream (callers) for a WCNP app — SRE-OPS call, no internal LLM."""
    logger.info(f"MCP tool: fetch_wcnp_upstream_dependencies app={app_name} ns={namespace}")
    try:
        upstream, _, breakdown = await get_upstream_and_downstream_dependencies(
            app_name, namespace, direction="upstream"
        )
        return {
            "status": "success",
            "app_name": app_name,
            "namespace": namespace,
            "direction": "upstream",
            "dependencies": upstream,
            "source_breakdown": breakdown,
            "total_count": len(upstream),
            "message": f"Found {len(upstream)} upstream dependencies for '{app_name}' in '{namespace}'",
        }
    except Exception as e:
        logger.error(f"fetch_wcnp_upstream_dependencies error: {e}")
        return {
            "status": "error",
            "app_name": app_name,
            "namespace": namespace,
            "direction": "upstream",
            "dependencies": [],
            "total_count": 0,
            "error": str(e),
        }


@mcp.tool(
    name="fetch_wcnp_downstream_dependencies",
    description=(
        "Fetch DOWNSTREAM dependencies for a WCNP (Kubernetes) application.\n"
        "Downstream = services this app calls OUT TO (its dependencies / providers).\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Use when you already know both app_name AND namespace.\n"
        "If you only have a namespace, use list_apps_in_namespace first.\n"
        "Parameters:\n"
        "  app_name  — application/deployment name (e.g. 'payment-service', 'item-read-service-prod2-tg2')\n"
        "  namespace — Kubernetes namespace (e.g. 'iro-async', 'prod', 'atlas-inventory-crons')"
    ),
)
async def fetch_wcnp_downstream_dependencies(app_name: str, namespace: str) -> dict:
    """Fetch downstream (callees) for a WCNP app — SRE-OPS call, no internal LLM."""
    logger.info(f"MCP tool: fetch_wcnp_downstream_dependencies app={app_name} ns={namespace}")
    try:
        _, downstream, breakdown = await get_upstream_and_downstream_dependencies(
            app_name, namespace, direction="downstream"
        )
        return {
            "status": "success",
            "app_name": app_name,
            "namespace": namespace,
            "direction": "downstream",
            "dependencies": downstream,
            "source_breakdown": breakdown,
            "total_count": len(downstream),
            "message": f"Found {len(downstream)} downstream dependencies for '{app_name}' in '{namespace}'",
        }
    except Exception as e:
        logger.error(f"fetch_wcnp_downstream_dependencies error: {e}")
        return {
            "status": "error",
            "app_name": app_name,
            "namespace": namespace,
            "direction": "downstream",
            "dependencies": [],
            "total_count": 0,
            "error": str(e),
        }
