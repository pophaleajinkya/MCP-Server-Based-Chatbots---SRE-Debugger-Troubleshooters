"""MCP-specific Pydantic models for dependency-agent tools.

These models are intentionally decoupled from MAOF application models.
They produce flat JSON Schema (draft 2020-12) with no anyOf/oneOf/allOf/$defs/$schema.

Package layout
--------------
  base.py                   — base classes, shared output base
  wcnp_models.py            — WCNP / Kubernetes tool schemas
  oneops_models.py          — OneOps tool schemas
  managed_service_models.py — Cassandra / MeghaCache / Cosmos / SQL Server schemas
"""
from src.mcp_models.base import (
    MCPInputBase,
    MCPOutputBase,
    BaseDepsOutput,
)
from src.mcp_models.wcnp_models import (
    ListAppsInput,
    ListAppsOutput,
    WcnpDepsInput,
    WcnpDepsOutput,
)
from src.mcp_models.oneops_models import (
    OneOpsDepsInput,
    OneOpsDepsOutput,
)
from src.mcp_models.managed_service_models import (
    CassandraInput,
    MeghaCacheInput,
    CosmosInput,
    SqlServerInput,
    ManagedServiceOutput,
)

__all__ = [
    # Base
    "MCPInputBase",
    "MCPOutputBase",
    "BaseDepsOutput",
    # WCNP
    "ListAppsInput",
    "ListAppsOutput",
    "WcnpDepsInput",
    "WcnpDepsOutput",
    # OneOps
    "OneOpsDepsInput",
    "OneOpsDepsOutput",
    # Managed Services
    "CassandraInput",
    "MeghaCacheInput",
    "CosmosInput",
    "SqlServerInput",
    "ManagedServiceOutput",
]
