"""Agent response models for MAOF integration."""
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict


class AgentResponse(BaseModel):
    """Response model for MAOF agent."""
    model_config = ConfigDict(populate_by_name=True)

    status: str = Field(..., description="Status of agent execution (success, error).")
    query: str = Field(..., description="The original user query processed by the agent.")
    data: Optional[Dict[str, Any]] = Field(None, description="Structured data returned by the agent (dependencies, apps, etc).")
    error: Optional[str] = Field(None, description="Error message if the agent execution failed.")

