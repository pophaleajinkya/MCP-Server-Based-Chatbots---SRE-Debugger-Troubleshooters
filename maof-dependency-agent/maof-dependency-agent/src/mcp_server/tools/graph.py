"""MCP tools that return Mermaid diagram markup for dependency graphs.

Each tool fetches dependencies from SRE-OPS and transforms the result into
a Mermaid flowchart string ready for rendering in any markdown-capable client
(Claude, GitHub, Confluence, etc.).

No LLM inside — pure data transform.
"""
import logging
import re
from typing import List, Dict

from src.mcp_server.server import mcp
from src.services.merge_service import get_upstream_and_downstream_dependencies
from src.services.sre_ops_service import (
    fetch_oneops_upstream_dependencies as _oneops_up,
    fetch_oneops_downstream_dependencies as _oneops_down,
    fetch_managed_service_upstream_dependencies,
)

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _node_id(label: str) -> str:
    """Convert a service name to a valid Mermaid node identifier."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", label)


def _dep_label(dep: dict) -> str:
    """Extract the best display name from a raw SRE-OPS dependency record."""
    return (
        dep.get("appName")
        or dep.get("app_name")
        or dep.get("name")
        or dep.get("platform")
        or dep.get("assembly")
        or str(dep)[:40]
    )


def _build_mermaid(
    center: str,
    upstream: List[Dict],
    downstream: List[Dict],
) -> str:
    """Build a Mermaid LR flowchart with upstream callers → center → downstream callees."""
    lines = ["graph LR"]
    center_id = _node_id(center)
    lines.append(f'  {center_id}["{center}"]:::center')

    seen_edges: set = set()

    for dep in upstream:
        label = _dep_label(dep)
        nid = _node_id(label)
        edge = (nid, center_id)
        if edge not in seen_edges:
            lines.append(f'  {nid}["{label}"] --> {center_id}')
            seen_edges.add(edge)

    for dep in downstream:
        label = _dep_label(dep)
        nid = _node_id(label)
        edge = (center_id, nid)
        if edge not in seen_edges:
            lines.append(f'  {center_id} --> {nid}["{label}"]')
            seen_edges.add(edge)

    lines.append("  classDef center fill:#f90,color:#000,font-weight:bold")

    if not upstream and not downstream:
        lines.append(f'  note[" No dependencies found "]')

    return "\n".join(lines)


# ── WCNP tool ─────────────────────────────────────────────────────────────────

@mcp.tool(
    name="get_wcnp_dependency_graph",
    description=(
        "Fetch BOTH upstream and downstream dependencies for a WCNP (Kubernetes) app\n"
        "and return a Mermaid flowchart diagram string.\n"
        "Upstream callers appear on the LEFT; downstream callees appear on the RIGHT.\n"
        "Paste the 'mermaid' field into any markdown block to render the graph.\n"
        "Parameters:\n"
        "  app_name  — application/deployment name (e.g. 'item-read-service-prod2-tg2')\n"
        "  namespace — Kubernetes namespace (e.g. 'prod', 'iro-async')"
    ),
)
async def get_wcnp_dependency_graph(app_name: str, namespace: str) -> dict:
    """Return a Mermaid diagram of all WCNP deps — upstream + downstream in one call."""
    logger.info(f"MCP graph tool: get_wcnp_dependency_graph app={app_name} ns={namespace}")
    try:
        upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
            app_name, namespace, direction=None
        )
        diagram = _build_mermaid(app_name, upstream, downstream)
        return {
            "status": "success",
            "app_name": app_name,
            "namespace": namespace,
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "mermaid": diagram,
            "message": (
                f"Dependency graph for '{app_name}' in '{namespace}': "
                f"{len(upstream)} upstream, {len(downstream)} downstream.\n"
                f"Render the 'mermaid' field in a ```mermaid``` code block."
            ),
        }
    except Exception as e:
        logger.error(f"get_wcnp_dependency_graph error: {e}")
        return {
            "status": "error",
            "app_name": app_name,
            "namespace": namespace,
            "mermaid": "",
            "error": str(e),
        }


# ── OneOps tool ───────────────────────────────────────────────────────────────

@mcp.tool(
    name="get_oneops_dependency_graph",
    description=(
        "Fetch BOTH upstream and downstream dependencies for a OneOps application\n"
        "and return a Mermaid flowchart diagram string.\n"
        "Upstream callers appear on the LEFT; downstream callees appear on the RIGHT.\n"
        "Paste the 'mermaid' field into any markdown block to render the graph.\n"
        "Parameters:\n"
        "  org      — OneOps organisation (e.g. 'mexicoecomm', 'walmart-ecomm')\n"
        "  platform — OneOps platform name (e.g. 'rmsag2', 'pay-platform')\n"
        "  assembly — OneOps assembly name (e.g. 'mx-rms', 'payments-prod')"
    ),
)
async def get_oneops_dependency_graph(org: str, platform: str, assembly: str) -> dict:
    """Return a Mermaid diagram of all OneOps deps — upstream + downstream in one call."""
    logger.info(f"MCP graph tool: get_oneops_dependency_graph org={org} platform={platform} assembly={assembly}")
    center = f"{assembly}/{platform}"
    try:
        upstream = await _oneops_up(org, platform, assembly)
        downstream = await _oneops_down(org, platform, assembly)
        diagram = _build_mermaid(center, upstream, downstream)
        return {
            "status": "success",
            "org": org,
            "platform": platform,
            "assembly": assembly,
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "mermaid": diagram,
            "message": (
                f"Dependency graph for '{center}' (org={org}): "
                f"{len(upstream)} upstream, {len(downstream)} downstream.\n"
                f"Render the 'mermaid' field in a ```mermaid``` code block."
            ),
        }
    except Exception as e:
        logger.error(f"get_oneops_dependency_graph error: {e}")
        return {
            "status": "error",
            "org": org,
            "platform": platform,
            "assembly": assembly,
            "mermaid": "",
            "error": str(e),
        }


# ── Managed service tools ─────────────────────────────────────────────────────

@mcp.tool(
    name="get_cassandra_dependency_graph",
    description=(
        "Fetch upstream dependencies for a Cassandra managed service and return a Mermaid diagram.\n"
        "Only upstream callers are available for managed services.\n"
        "Parameters:\n"
        "  assembly — OneOps assembly name (e.g. 'mx-rms')\n"
        "  platform — OneOps platform name (e.g. 'rmsag2')"
    ),
)
async def get_cassandra_dependency_graph(assembly: str, platform: str) -> dict:
    """Return a Mermaid diagram of Cassandra upstream callers."""
    return await _managed_graph(
        center=f"cassandra/{assembly}",
        service_type="cassandra",
        params={"assembly": assembly, "platform": platform, "serviceType": "cassandra"},
    )


@mcp.tool(
    name="get_meghacache_dependency_graph",
    description=(
        "Fetch upstream dependencies for a MeghaCache managed service and return a Mermaid diagram.\n"
        "Only upstream callers are available for managed services.\n"
        "Parameters:\n"
        "  assembly — OneOps assembly name (e.g. 'payments-prod')\n"
        "  platform — OneOps platform name (e.g. 'pay-platform')"
    ),
)
async def get_meghacache_dependency_graph(assembly: str, platform: str) -> dict:
    """Return a Mermaid diagram of MeghaCache upstream callers."""
    return await _managed_graph(
        center=f"meghacache/{assembly}",
        service_type="meghacache",
        params={"assembly": assembly, "platform": platform, "serviceType": "meghacache"},
    )


@mcp.tool(
    name="get_cosmos_dependency_graph",
    description=(
        "Fetch upstream dependencies for a Cosmos DB managed service and return a Mermaid diagram.\n"
        "Only upstream callers are available for managed services.\n"
        "Parameters:\n"
        "  resource_group  — Azure resource group\n"
        "  subscription_id — Azure subscription ID\n"
        "  database_name   — Cosmos database name"
    ),
)
async def get_cosmos_dependency_graph(
    resource_group: str, subscription_id: str, database_name: str
) -> dict:
    """Return a Mermaid diagram of Cosmos DB upstream callers."""
    return await _managed_graph(
        center=f"cosmos/{database_name}",
        service_type="cosmos",
        params={
            "resourceGroup": resource_group,
            "subscriptionId": subscription_id,
            "databaseName": database_name,
            "serviceType": "cosmos",
        },
    )


@mcp.tool(
    name="get_sqlserver_dependency_graph",
    description=(
        "Fetch upstream dependencies for a SQL Server managed service and return a Mermaid diagram.\n"
        "Only upstream callers are available for managed services.\n"
        "Parameters:\n"
        "  resource_group  — Azure resource group\n"
        "  subscription_id — Azure subscription ID\n"
        "  database_name   — SQL Server database name"
    ),
)
async def get_sqlserver_dependency_graph(
    resource_group: str, subscription_id: str, database_name: str
) -> dict:
    """Return a Mermaid diagram of SQL Server upstream callers."""
    return await _managed_graph(
        center=f"sqlserver/{database_name}",
        service_type="sqlserver",
        params={
            "resourceGroup": resource_group,
            "subscriptionId": subscription_id,
            "databaseName": database_name,
            "serviceType": "sqlserver",
        },
    )


async def _managed_graph(center: str, service_type: str, params: dict) -> dict:
    """Shared Mermaid builder for all managed service graph tools."""
    logger.info(f"MCP graph tool: {service_type} dependency graph params={params}")
    try:
        upstream = await fetch_managed_service_upstream_dependencies(params)
        diagram = _build_mermaid(center, upstream, downstream=[])
        return {
            "status": "success",
            "service_type": service_type,
            "upstream_count": len(upstream),
            "mermaid": diagram,
            "message": (
                f"Dependency graph for '{center}': {len(upstream)} upstream callers.\n"
                f"Render the 'mermaid' field in a ```mermaid``` code block."
            ),
        }
    except Exception as e:
        logger.error(f"get_{service_type}_dependency_graph error: {e}")
        return {
            "status": "error",
            "service_type": service_type,
            "mermaid": "",
            "error": str(e),
        }
