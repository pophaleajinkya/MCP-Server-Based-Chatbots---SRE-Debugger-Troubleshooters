"""MCP tools for managed services — thin, structured, no internal LLM.

Four separate tools, one per service type.
Every parameter is required — no ambiguity for the client LLM.
"""
import logging

from src.mcp_server.server import mcp
from src.services.sre_ops_service import fetch_managed_service_upstream_dependencies

logger = logging.getLogger(__name__)


@mcp.tool(
    name="fetch_cassandra_upstream_dependencies",
    description=(
        "Fetch UPSTREAM dependencies for a Cassandra managed service (NoSQL DB on OneOps).\n"
        "Upstream = services that read/write INTO this Cassandra instance (its callers / consumers).\n"
        "NOTE: Only upstream callers are available for managed services — there is no downstream tool.\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Parameters:\n"
        "  assembly — OneOps assembly name (e.g. 'mx-rms', 'payments-prod')\n"
        "  platform — OneOps platform name (e.g. 'rmsag2', 'pay-platform')"
    ),
)
async def fetch_cassandra_upstream_dependencies(assembly: str, platform: str) -> dict:
    """Fetch Cassandra upstream deps from SRE-OPS."""
    logger.info(f"MCP tool: fetch_cassandra_upstream_dependencies assembly={assembly} platform={platform}")
    return await _fetch(service_type="cassandra", params={"assembly": assembly, "platform": platform, "serviceType": "cassandra"})


@mcp.tool(
    name="fetch_meghacache_upstream_dependencies",
    description=(
        "Fetch UPSTREAM dependencies for a MeghaCache managed service (distributed cache on OneOps).\n"
        "Upstream = services that read/write INTO this MeghaCache instance (its callers / consumers).\n"
        "NOTE: Only upstream callers are available for managed services — there is no downstream tool.\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Parameters:\n"
        "  assembly — OneOps assembly name (e.g. 'payments-prod')\n"
        "  platform — OneOps platform name (e.g. 'pay-platform')"
    ),
)
async def fetch_meghacache_upstream_dependencies(assembly: str, platform: str) -> dict:
    """Fetch MeghaCache upstream deps from SRE-OPS."""
    logger.info(f"MCP tool: fetch_meghacache_upstream_dependencies assembly={assembly} platform={platform}")
    return await _fetch(service_type="meghacache", params={"assembly": assembly, "platform": platform, "serviceType": "meghacache"})


@mcp.tool(
    name="fetch_cosmos_upstream_dependencies",
    description=(
        "Fetch UPSTREAM dependencies for a Cosmos DB managed service (Azure NoSQL database).\n"
        "Upstream = services that read/write INTO this Cosmos DB instance (its callers / consumers).\n"
        "NOTE: Only upstream callers are available for managed services — there is no downstream tool.\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Parameters:\n"
        "  resource_group  — Azure resource group (e.g. 'my-rg')\n"
        "  subscription_id — Azure subscription ID (e.g. 'sub-123')\n"
        "  database_name   — Cosmos database name (e.g. 'orders-db')"
    ),
)
async def fetch_cosmos_upstream_dependencies(
    resource_group: str,
    subscription_id: str,
    database_name: str,
) -> dict:
    """Fetch Cosmos DB upstream deps from SRE-OPS."""
    logger.info(f"MCP tool: fetch_cosmos_upstream_dependencies rg={resource_group} db={database_name}")
    return await _fetch(
        service_type="cosmos",
        params={
            "resourceGroup": resource_group,
            "subscriptionId": subscription_id,
            "databaseName": database_name,
            "serviceType": "cosmos",
        },
    )


@mcp.tool(
    name="fetch_sqlserver_upstream_dependencies",
    description=(
        "Fetch UPSTREAM dependencies for a SQL Server managed service (Azure relational database).\n"
        "Upstream = services that read/write INTO this SQL Server instance (its callers / consumers).\n"
        "NOTE: Only upstream callers are available for managed services — there is no downstream tool.\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Parameters:\n"
        "  resource_group  — Azure resource group (e.g. 'prod-rg')\n"
        "  subscription_id — Azure subscription ID (e.g. 'abc-456')\n"
        "  database_name   — SQL Server database name (e.g. 'inventory-db')"
    ),
)
async def fetch_sqlserver_upstream_dependencies(
    resource_group: str,
    subscription_id: str,
    database_name: str,
) -> dict:
    """Fetch SQL Server upstream deps from SRE-OPS."""
    logger.info(f"MCP tool: fetch_sqlserver_upstream_dependencies rg={resource_group} db={database_name}")
    return await _fetch(
        service_type="sqlserver",
        params={
            "resourceGroup": resource_group,
            "subscriptionId": subscription_id,
            "databaseName": database_name,
            "serviceType": "sqlserver",
        },
    )


async def _fetch(service_type: str, params: dict) -> dict:
    """Shared SRE-OPS call for all managed service tools."""
    try:
        dependencies = await fetch_managed_service_upstream_dependencies(params)
        return {
            "status": "success",
            "service_type": service_type,
            "direction": "upstream",
            "dependencies": dependencies,
            "total_count": len(dependencies),
            "message": f"Found {len(dependencies)} upstream dependencies for {service_type}",
        }
    except Exception as e:
        logger.error(f"fetch_{service_type}_dependencies error: {e}")
        return {
            "status": "error",
            "service_type": service_type,
            "direction": "upstream",
            "dependencies": [],
            "total_count": 0,
            "error": str(e),
        }
