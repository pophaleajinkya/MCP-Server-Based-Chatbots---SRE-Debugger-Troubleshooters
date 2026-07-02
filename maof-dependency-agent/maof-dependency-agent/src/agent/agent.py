"""Single LangGraph DependencyAgent handling WCNP, OneOps and Managed Service queries.

Graph flow:
  parse_query
      ├─► fetch_wcnp            (wcnp, app + namespace known)
      ├─► suggest_wcnp          (wcnp, namespace only)
      ├─► fetch_oneops          (oneops)
      ├─► fetch_managed_service (managed_service)
      └─► format_response       (error / fallthrough)
              │
             END

The calling endpoint sets `query_type` in the initial state so the LLM
extraction prompt knows exactly which parameters to look for.
"""
import json
import logging
import toons
from typing import Dict, Any, Optional, List

import httpx
from langchain.schema import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from config import get_settings
from src.models.agent_state import DependencyAgentState
from src.prompts.system_prompts import PARAMETER_EXTRACTION_PROMPT
from src.services.merge_service import get_upstream_and_downstream_dependencies
from src.services.sre_ops_service import (
    fetch_managed_service_upstream_dependencies,
    fetch_oneops_upstream_dependencies,
    fetch_oneops_downstream_dependencies,
)
from src.utils.llm_client import llm_client

logger = logging.getLogger(__name__)
settings = get_settings()
_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501

_CASSANDRA_MEGHACACHE = {"cassandra", "meghacache"}
_COSMOS_SQL = {"cosmos", "sqlserver"}


# ---------------------------------------------------------------------------
# Shared routing / formatting helpers
# ---------------------------------------------------------------------------

def _route_after_parse(state: DependencyAgentState) -> str:
    return state.get("next_step", "error")


def _format_response(state: DependencyAgentState) -> DependencyAgentState:
    logger.info(f"[{state['session_id']}] Formatting response")
    return state


# ---------------------------------------------------------------------------
# WCNP nodes
# ---------------------------------------------------------------------------

def _extract_app_name_from_dict(app: Dict[str, Any]) -> Optional[str]:
    return (app.get("app_name") or app.get("appName") or
            app.get("name") or app.get("releaseName"))


async def _get_apps_for_namespace(namespace: str) -> Dict[str, Any]:
    try:
        url = f"{settings.DX_CONSOLE_URL}{settings.DX_CONSOLE_APPS_PATH}"
        params = {"profile": "prod", "namespace": namespace}
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            response = await client.get(
                url, headers={"Content-Type": "application/json"}, params=params
            )
            response.raise_for_status()
            data = response.json()

        if isinstance(data, list):
            apps = [_extract_app_name_from_dict(a) for a in data if isinstance(a, dict)]
        else:
            raw = data.get("apps") or data.get("applications") or data.get("data") or []
            apps = [_extract_app_name_from_dict(a) for a in raw if isinstance(a, dict)]

        apps = list(dict.fromkeys(a for a in apps if a))
        if apps:
            return {
                "success": True, "namespace": namespace, "available_apps": apps,
                "message": f"Found {len(apps)} apps in namespace '{namespace}'. "
                           "Please select an app to get its dependencies.",
            }
        return {
            "success": False, "namespace": namespace, "available_apps": [],
            "message": f"No apps found in namespace '{namespace}'. Please verify the namespace name.",
        }
    except Exception as e:
        logger.error(f"Error fetching apps for namespace {namespace}: {e}")
        return {
            "success": False, "namespace": namespace, "available_apps": [],
            "error": str(e),
            "message": f"Failed to fetch apps for namespace '{namespace}': {e}",
        }


async def _suggest_wcnp(state: DependencyAgentState) -> DependencyAgentState:
    """WCNP — namespace only: list available apps."""
    session_id, namespace = state["session_id"], state["namespace"]
    logger.info(f"[{session_id}] WCNP suggest: namespace={namespace}")

    result = await _get_apps_for_namespace(namespace)
    state["dependencies"] = []
    state["source_breakdown"] = {}

    if result.get("success"):
        state["available_apps"] = result["available_apps"]
        state["messages"].append(
            f"{result['message']} Available apps: [{', '.join(result['available_apps'])}]"
        )
    else:
        state["messages"].append(result.get("message", "Could not fetch apps"))
        if result.get("error"):
            state["error"] = result["error"]
    return state


async def _fetch_wcnp(state: DependencyAgentState) -> DependencyAgentState:
    """WCNP — app + namespace: fetch upstream/downstream dependencies."""
    session_id = state["session_id"]
    app_name, namespace, direction = state["app_name"], state["namespace"], state.get("direction")
    logger.info(f"[{session_id}] WCNP fetch: app={app_name}, ns={namespace}, dir={direction}")

    try:
        upstream_deps, downstream_deps, source_breakdown = \
            await get_upstream_and_downstream_dependencies(app_name, namespace, direction=direction)

        if direction == "upstream":
            state["dependencies"] = upstream_deps
            state["messages"].append(f"Found {len(upstream_deps)} upstream dependencies")
            state["source_breakdown"] = {
                "upstream_count": len(upstream_deps), "downstream_count": 0,
                "total": len(upstream_deps),
            }
        elif direction == "downstream":
            state["dependencies"] = downstream_deps
            state["messages"].append(f"Found {len(downstream_deps)} downstream dependencies")
            state["source_breakdown"] = {
                "upstream_count": 0, "downstream_count": len(downstream_deps),
                "total": len(downstream_deps),
            }
        else:
            state["upstream_dependencies"] = upstream_deps
            state["downstream_dependencies"] = downstream_deps
            state["dependencies"] = upstream_deps + downstream_deps
            state["source_breakdown"] = source_breakdown
            state["messages"].append(
                f"Found {len(upstream_deps)} upstream and {len(downstream_deps)} downstream dependencies"
            )
    except Exception as e:
        logger.error(f"[{session_id}] WCNP fetch error: {e}")
        state["error"] = str(e)
        state.setdefault("dependencies", [])
        state.setdefault("source_breakdown", {})
    return state


# ---------------------------------------------------------------------------
# OneOps node
# ---------------------------------------------------------------------------

async def _fetch_oneops(state: DependencyAgentState) -> DependencyAgentState:
    """OneOps — fetch dependencies from SRE-OPS only (no Topology)."""
    session_id = state["session_id"]
    org, platform, assembly = state["org"], state["platform"], state["assembly"]
    direction = state.get("direction")
    # Treat "both" the same as None — fetch upstream and downstream
    if direction == "both":
        direction = None
    logger.info(
        f"[{session_id}] OneOps fetch: org={org}, platform={platform}, "
        f"assembly={assembly}, dir={direction}"
    )

    try:
        upstream_deps: List[Dict] = []
        downstream_deps: List[Dict] = []

        if direction in ("upstream", "both", None):
            upstream_deps = await fetch_oneops_upstream_dependencies(org, platform, assembly)

        if direction in ("downstream", "both", None):
            downstream_deps = await fetch_oneops_downstream_dependencies(org, platform, assembly)

        state["upstream_dependencies"] = upstream_deps
        state["downstream_dependencies"] = downstream_deps
        state["source_breakdown"] = {
            "upstream_count": len(upstream_deps),
            "downstream_count": len(downstream_deps),
            "total": len(upstream_deps) + len(downstream_deps),
        }

        if direction == "upstream":
            state["dependencies"] = upstream_deps
            state["messages"].append(f"Found {len(upstream_deps)} upstream dependencies")
        elif direction == "downstream":
            state["dependencies"] = downstream_deps
            state["messages"].append(f"Found {len(downstream_deps)} downstream dependencies")
        else:
            state["dependencies"] = upstream_deps + downstream_deps
            state["messages"].append(
                f"Found {len(upstream_deps)} upstream and {len(downstream_deps)} downstream dependencies"
            )

    except Exception as e:
        logger.error(f"[{session_id}] OneOps fetch error: {e}")
        state["error"] = str(e)
        state.setdefault("dependencies", [])
        state.setdefault("source_breakdown", {})
    return state


# ---------------------------------------------------------------------------
# Managed Service node
# ---------------------------------------------------------------------------

def _build_managed_sre_params(state: DependencyAgentState) -> Dict:
    service_type = state["service_type"]
    if service_type in _CASSANDRA_MEGHACACHE:
        return {"assembly": state["assembly"], "platform": state["platform"], "serviceType": service_type}
    return {
        "resourceGroup": state["resource_group"],
        "subscriptionId": state["subscription_id"],
        "databaseName": state["database_name"],
        "serviceType": service_type,
    }


def _missing_managed_params(state: DependencyAgentState) -> List[str]:
    service_type = state.get("service_type")
    if service_type in _CASSANDRA_MEGHACACHE:
        return [f for f, v in [("assembly", state.get("assembly")), ("platform", state.get("platform"))] if not v]
    if service_type in _COSMOS_SQL:
        return [f for f, v in [
            ("resource_group", state.get("resource_group")),
            ("subscription_id", state.get("subscription_id")),
            ("database_name", state.get("database_name")),
        ] if not v]
    return ["service_type"]


async def _fetch_managed_service(state: DependencyAgentState) -> DependencyAgentState:
    """Managed Service — call SRE-OPS upstream only."""
    session_id = state["session_id"]
    service_type = state["service_type"]
    sre_params = _build_managed_sre_params(state)
    logger.info(f"[{session_id}] ManagedService fetch: type={service_type}, params={sre_params}")

    try:
        dependencies = await fetch_managed_service_upstream_dependencies(sre_params)
        state["dependencies"] = dependencies
        state["source_breakdown"] = {"upstream_count": len(dependencies), "total": len(dependencies)}
        state["messages"].append(f"Found {len(dependencies)} upstream dependencies for {service_type}")
    except Exception as e:
        logger.error(f"[{session_id}] ManagedService fetch error: {e}")
        state["error"] = str(e)
        state.setdefault("dependencies", [])
        state.setdefault("source_breakdown", {})
    return state


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class DependencyAgent:
    """Single LangGraph agent handling WCNP, OneOps, and Managed Service queries."""

    def __init__(self):
        self.llm = llm_client.chat
        self.graph = self._create_graph()

    def _create_graph(self):
        workflow = StateGraph(DependencyAgentState)

        workflow.add_node("parse_query", self._parse_query)
        workflow.add_node("fetch_wcnp", _fetch_wcnp)
        workflow.add_node("suggest_wcnp", _suggest_wcnp)
        workflow.add_node("fetch_oneops", _fetch_oneops)
        workflow.add_node("fetch_managed_service", _fetch_managed_service)
        workflow.add_node("format_response", _format_response)

        workflow.set_entry_point("parse_query")

        workflow.add_conditional_edges(
            "parse_query",
            _route_after_parse,
            {
                "fetch_wcnp": "fetch_wcnp",
                "suggest_wcnp": "suggest_wcnp",
                "fetch_oneops": "fetch_oneops",
                "fetch_managed_service": "fetch_managed_service",
                "error": "format_response",
            },
        )

        for node in ("fetch_wcnp", "suggest_wcnp", "fetch_oneops", "fetch_managed_service"):
            workflow.add_edge(node, "format_response")
        workflow.add_edge("format_response", END)

        return workflow.compile()

    async def _parse_query(self, state: DependencyAgentState) -> DependencyAgentState:
        """LLM extracts parameters; routing is decided by query_type set by the endpoint."""
        query = state["query"]
        session_id = state["session_id"]
        query_type = state.get("query_type", "wcnp")
        conversation_history = state.get("conversation_history", [])

        logger.info(f"[{session_id}] Parsing query — type={query_type}")

        context_data: Dict[str, Any] = {"current_query": query, "query_type": query_type}
        if conversation_history:
            context_data["previous_conversations"] = [
                {"role": c.get("role", "unknown"), "content": c.get("content", ""),
                 "timestamp": c.get("timestamp")}
                for c in conversation_history
            ]

        context_toon = toons.dumps(context_data)
        logger.debug(f"[{session_id}] Context TOON:\n{context_toon}")

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=PARAMETER_EXTRACTION_PROMPT),
                HumanMessage(content=context_toon),
            ])
            logger.debug(f"[{session_id}] LLM raw: {response.content}")
            extracted = json.loads(response.content)

            # Populate all fields; unused ones stay None
            state["app_name"] = extracted.get("app_name")
            state["namespace"] = extracted.get("namespace")
            state["direction"] = extracted.get("direction")
            state["org"] = extracted.get("org")
            state["platform"] = extracted.get("platform")
            state["assembly"] = extracted.get("assembly")
            state["service_type"] = extracted.get("service_type")
            state["resource_group"] = extracted.get("resource_group")
            state["subscription_id"] = extracted.get("subscription_id")
            state["database_name"] = extracted.get("database_name")

            # Honour LLM-detected query_type; fall back to the endpoint-provided one
            query_type = extracted.get("query_type") or query_type
            state["query_type"] = query_type

            state["messages"].append(
                f"Extracted: query_type={query_type}, app_name={state['app_name']}, "
                f"namespace={state['namespace']}, org={state['org']}, "
                f"platform={state['platform']}, assembly={state['assembly']}, "
                f"direction={state['direction']}, service_type={state['service_type']}"
            )
            logger.info(f"[{session_id}] {state['messages'][-1]}")

            # Route based on query_type
            if query_type == "managed_service":
                missing = _missing_managed_params(state)
                if not missing:
                    state["next_step"] = "fetch_managed_service"
                else:
                    svc = state.get("service_type") or "unknown"
                    if svc in _CASSANDRA_MEGHACACHE:
                        hint = "Required: assembly, platform, serviceType (cassandra|meghacache)"
                    elif svc in _COSMOS_SQL:
                        hint = "Required: resourceGroup, subscriptionId, databaseName, serviceType (cosmos|sqlserver)"
                    else:
                        hint = "Specify serviceType: cassandra, meghacache, cosmos, or sqlserver."
                    state["next_step"] = "error"
                    state["error"] = f"Missing required parameters: {', '.join(missing)}. {hint}"
                    logger.warning(f"[{session_id}] ManagedService missing: {missing}")

            elif query_type == "oneops":
                missing = [f for f, v in [
                    ("org", state["org"]),
                    ("platform", state["platform"]),
                    ("assembly", state["assembly"]),
                ] if not v]
                if not missing:
                    state["next_step"] = "fetch_oneops"
                else:
                    state["next_step"] = "error"
                    state["error"] = (
                        f"Missing OneOps parameters: {', '.join(missing)}. "
                        "Please provide org, platform and assembly."
                    )
                    logger.warning(f"[{session_id}] OneOps missing: {missing}")

            else:  # wcnp (default)
                if state["app_name"] and state["namespace"]:
                    state["next_step"] = "fetch_wcnp"
                elif state["namespace"]:
                    state["next_step"] = "suggest_wcnp"
                elif state["app_name"]:
                    state["next_step"] = "error"
                    state["error"] = (
                        f"Found application '{state['app_name']}' but namespace is missing. "
                        "Please provide the namespace."
                    )
                else:
                    state["next_step"] = "error"
                    state["error"] = (
                        "Could not extract application name or namespace. "
                        "Please provide at least a namespace or both app_name and namespace."
                    )

        except json.JSONDecodeError as e:
            logger.error(f"[{session_id}] JSON parse error: {e}")
            state["error"] = f"Failed to parse LLM response as JSON: {e}"
            state["next_step"] = "error"
        except Exception as e:
            logger.error(f"[{session_id}] Parse error: {e}")
            state["error"] = f"Failed to parse query: {e}"
            state["next_step"] = "error"

        return state

    async def process_query(
        self,
        query: str,
        session_id: str,
        query_type: str = "wcnp",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run the LangGraph workflow and return structured results."""
        initial_state: DependencyAgentState = {
            "query": query,
            "session_id": session_id,
            "conversation_history": conversation_history or [],
            "query_type": query_type,
            # WCNP
            "app_name": None, "namespace": None, "available_apps": None,
            # OneOps
            "org": None,
            # Shared
            "platform": None, "assembly": None,
            # Managed Service
            "service_type": None, "resource_group": None,
            "subscription_id": None, "database_name": None,
            # Common output
            "direction": None,
            "dependencies": [], "upstream_dependencies": None, "downstream_dependencies": None,
            "source_breakdown": {}, "messages": [], "error": None, "next_step": "",
        }

        final_state = await self.graph.ainvoke(initial_state)

        return {
            "query_type": final_state.get("query_type"),
            "app_name": final_state.get("app_name"),
            "namespace": final_state.get("namespace"),
            "available_apps": final_state.get("available_apps"),
            "org": final_state.get("org"),
            "platform": final_state.get("platform"),
            "assembly": final_state.get("assembly"),
            "service_type": final_state.get("service_type"),
            "resource_group": final_state.get("resource_group"),
            "subscription_id": final_state.get("subscription_id"),
            "database_name": final_state.get("database_name"),
            "direction": final_state.get("direction"),
            "dependencies": final_state.get("dependencies", []),
            "upstream_dependencies": final_state.get("upstream_dependencies"),
            "downstream_dependencies": final_state.get("downstream_dependencies"),
            "source_breakdown": final_state.get("source_breakdown", {}),
            "total_count": len(final_state.get("dependencies", [])),
            "messages": final_state.get("messages", []),
            "error": final_state.get("error"),
            "success": final_state.get("error") is None,
        }


# Global singleton — shared by all three endpoints
dependency_agent = DependencyAgent()

