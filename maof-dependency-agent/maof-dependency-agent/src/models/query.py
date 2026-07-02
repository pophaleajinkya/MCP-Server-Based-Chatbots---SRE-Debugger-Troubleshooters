"""Models for query-based tool execution."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class QueryRequest(BaseModel):
    """Request model for query with session."""
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="session_id", description="Session identifier for tracking or fetching context from previous interactions")
    query: str = Field(..., description="Query string containing context for tool execution")


class ToolPayload(BaseModel):
    """Payload for tool execution extracted from query."""
    model_config = ConfigDict(populate_by_name=True)

    tool_name: str = Field(..., alias="toolName", description="Tool to execute")
    app_name: Optional[str] = Field(None, alias="appName", description="Application name")
    namespace: Optional[str] = Field(None, description="Namespace")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Additional parameters")


class ToolResult(BaseModel):
    """Result from tool execution."""
    model_config = ConfigDict(populate_by_name=True)

    tool_name: str = Field(..., alias="toolName", description="Tool executed")
    success: bool = Field(..., description="Success status")
    data: Optional[Any] = Field(None, description="Result data")
    error: Optional[str] = Field(None, description="Error message")
    execution_time_ms: Optional[float] = Field(None, alias="executionTimeMs", description="Execution time")


class QueryResponse(BaseModel):
    """Response for query execution."""
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId", description="Session identifier")
    query: str = Field(..., description="Original query")
    extracted_payload: ToolPayload = Field(..., alias="extractedPayload", description="Extracted tool payload")
    tool_results: List[ToolResult] = Field(..., alias="toolResults", description="Tool execution results")
    success: bool = Field(..., description="Overall success status")

