"""Base classes and shared types for MCP tool schemas.

Separate from MAOF models. All models produce flat JSON Schema (draft 2020-12)
compatible with Anthropic's strict validator.

Rules enforced here:
  - No Optional / Union / anyOf / oneOf / allOf
  - No enums (use plain str)
  - No nested models (use list[dict] for collections)
  - No $schema in json_schema_extra
  - extra="forbid" on inputs  → additionalProperties: false
  - extra="allow"  on outputs → SRE-OPS passthrough accepted
"""
from pydantic import BaseModel, ConfigDict, Field


class MCPInputBase(BaseModel):
    """Base for MCP tool input models — strict, no extra fields."""
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )


class MCPOutputBase(BaseModel):
    """Base for MCP tool output models — permissive, SRE-OPS passthrough allowed."""
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
    )


class BaseDepsOutput(MCPOutputBase):
    """Common fields for all dependency-fetch tool outputs.

    dependencies is list[dict] — no nested model so no $defs/$ref in schema.
    status / direction are plain str — no enum so no $defs in schema.
    message / error default to "" — no Optional so no anyOf in schema.
    """
    status: str = Field("", description="success or error")
    direction: str = Field("", description="upstream or downstream")
    dependencies: list[dict] = Field(default_factory=list, description="Dependency list")
    total_count: int = Field(0, description="Total dependencies found")
    message: str = Field("", description="Summary message")
    error: str = Field("", description="Error detail when status=error")
