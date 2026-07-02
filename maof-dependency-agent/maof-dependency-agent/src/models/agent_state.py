"""Agent state model for the single DependencyAgent LangGraph workflow."""
from typing import TypedDict, List, Dict, Any, Optional


class DependencyAgentState(TypedDict):
    """
    Single state covering all three query types:
      - wcnp           : app_name + namespace (WCNP / Kubernetes)
      - oneops         : org + platform + assembly
      - managed_service: service_type + type-specific params

    query_type is set by the endpoint before the graph runs so the LLM
    and routing logic know which parameters to extract and validate.
    """
    query: str
    session_id: str
    conversation_history: Optional[List[Dict[str, Any]]]

    # "wcnp" | "oneops" | "managed_service"  — set by the calling endpoint
    query_type: Optional[str]

    # ── WCNP ─────────────────────────────────────────────────────────────────
    app_name: Optional[str]
    namespace: Optional[str]
    available_apps: Optional[List[str]]

    # ── OneOps ───────────────────────────────────────────────────────────────
    org: Optional[str]

    # Shared by OneOps + Managed Service
    platform: Optional[str]
    assembly: Optional[str]

    # ── Managed Service ───────────────────────────────────────────────────────
    # cassandra | meghacache | cosmos | sqlserver
    service_type: Optional[str]
    resource_group: Optional[str]
    subscription_id: Optional[str]
    database_name: Optional[str]

    # ── Common output ─────────────────────────────────────────────────────────
    direction: Optional[str]
    dependencies: List[Dict[str, Any]]
    upstream_dependencies: Optional[List[Dict[str, Any]]]
    downstream_dependencies: Optional[List[Dict[str, Any]]]
    source_breakdown: Dict[str, Any]
    messages: List[str]
    error: Optional[str]
    next_step: str
