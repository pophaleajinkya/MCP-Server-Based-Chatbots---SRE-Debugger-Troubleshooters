"""MCP schemas for managed service dependency tools.

Each service type has its own input model (parameters differ per service):
  fetch_cassandra_upstream_dependencies  → CassandraInput  / ManagedServiceOutput
  fetch_meghacache_upstream_dependencies → MeghaCacheInput / ManagedServiceOutput
  fetch_cosmos_upstream_dependencies     → CosmosInput     / ManagedServiceOutput
  fetch_sqlserver_upstream_dependencies  → SqlServerInput  / ManagedServiceOutput

No Optional / anyOf / oneOf / allOf / $defs / min_length — flat schemas only.
"""
from pydantic import Field

from src.mcp_models.base import MCPInputBase, BaseDepsOutput


class CassandraInput(MCPInputBase):
    """Input: fetch upstream dependencies for a Cassandra managed service."""

    assembly: str = Field(..., description="OneOps assembly, e.g. 'mx-rms'")
    platform: str = Field(..., description="OneOps platform, e.g. 'rmsag2'")


class MeghaCacheInput(MCPInputBase):
    """Input: fetch upstream dependencies for a MeghaCache managed service."""

    assembly: str = Field(..., description="OneOps assembly, e.g. 'payments-prod'")
    platform: str = Field(..., description="OneOps platform, e.g. 'pay-platform'")


class CosmosInput(MCPInputBase):
    """Input: fetch upstream dependencies for a Cosmos DB managed service."""

    resource_group: str = Field(..., description="Azure resource group, e.g. 'my-rg'")
    subscription_id: str = Field(..., description="Azure subscription ID")
    database_name: str = Field(..., description="Cosmos DB name, e.g. 'orders-db'")


class SqlServerInput(MCPInputBase):
    """Input: fetch upstream dependencies for a SQL Server managed service."""

    resource_group: str = Field(..., description="Azure resource group, e.g. 'prod-rg'")
    subscription_id: str = Field(..., description="Azure subscription ID")
    database_name: str = Field(..., description="SQL Server DB name, e.g. 'inventory-db'")


class ManagedServiceOutput(BaseDepsOutput):
    """Output: upstream dependency graph for a managed service."""

    service_type: str = Field("", description="Service type: cassandra | meghacache | cosmos | sqlserver")
