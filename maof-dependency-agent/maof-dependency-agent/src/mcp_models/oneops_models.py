"""MCP schemas for OneOps dependency tools.

  fetch_oneops_upstream_dependencies   → OneOpsDepsInput / OneOpsDepsOutput
  fetch_oneops_downstream_dependencies → OneOpsDepsInput / OneOpsDepsOutput

No Optional / anyOf / oneOf / allOf / $defs — flat schemas only.
"""
from pydantic import Field

from src.mcp_models.base import MCPInputBase, BaseDepsOutput


class OneOpsDepsInput(MCPInputBase):
    """Input: fetch upstream or downstream dependencies for a OneOps app."""

    org: str = Field(..., description="OneOps org, e.g. 'mexicoecomm'")
    platform: str = Field(..., description="OneOps platform, e.g. 'rmsag2'")
    assembly: str = Field(..., description="OneOps assembly, e.g. 'mx-rms'")


class OneOpsDepsOutput(BaseDepsOutput):
    """Output: OneOps dependency graph for one assembly."""

    org: str = Field("", description="Org that was queried")
    platform: str = Field("", description="Platform that was queried")
    assembly: str = Field("", description="Assembly that was queried")
