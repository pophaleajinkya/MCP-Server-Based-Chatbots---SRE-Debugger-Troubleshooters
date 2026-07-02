"""MCP schemas for WCNP (Kubernetes) dependency tools.

  list_apps_in_namespace        → ListAppsInput  / ListAppsOutput
  fetch_wcnp_upstream_*         → WcnpDepsInput  / WcnpDepsOutput
  fetch_wcnp_downstream_*       → WcnpDepsInput  / WcnpDepsOutput

No Optional / anyOf / oneOf / allOf / $defs — flat schemas only.
"""
from pydantic import Field

from src.mcp_models.base import MCPInputBase, MCPOutputBase, BaseDepsOutput


class ListAppsInput(MCPInputBase):
    """Input: list all apps in a WCNP namespace."""

    namespace: str = Field(..., description="Kubernetes namespace, e.g. 'iro-async'")


class ListAppsOutput(MCPOutputBase):
    """Output: list of apps found in the namespace."""

    status: str = Field("", description="success or error")
    namespace: str = Field("", description="Namespace that was queried")
    available_apps: list[str] = Field(default_factory=list, description="App names in the namespace")
    message: str = Field("", description="Summary message")
    error: str = Field("", description="Error detail when status=error")


class WcnpDepsInput(MCPInputBase):
    """Input: fetch upstream or downstream dependencies for a WCNP app."""

    app_name: str = Field(..., description="Deployment name, e.g. 'payment-service'")
    namespace: str = Field(..., description="Kubernetes namespace, e.g. 'iro-async'")


class WcnpDepsOutput(BaseDepsOutput):
    """Output: WCNP dependency graph for one app."""

    app_name: str = Field("", description="App that was queried")
    namespace: str = Field("", description="Namespace that was queried")
