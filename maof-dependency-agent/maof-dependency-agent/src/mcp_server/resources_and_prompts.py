"""MCP resources and prompts for the dependency agent.

Resources — static context the client LLM can load at startup:
    dependency://agent-guide   Tool selection guide (which tool for which scenario)

Prompts — reusable templates for multi-tool workflows only:
    trace_wcnp_app             Fetch full dependency picture for a WCNP app
    trace_oneops_app           Fetch full dependency picture for a OneOps app

Note: managed services are single-tool calls (upstream only) — no prompt needed.
"""
from src.mcp_server.server import mcp

# ── Resource: agent guide ─────────────────────────────────────────────────────

_AGENT_GUIDE = """
# Dependency Agent — Tool Selection Guide

## When to use which tool

### WCNP (Kubernetes)
Use when the app runs on Kubernetes / WCNP.
You need: `app_name` + `namespace`

- **Only namespace known?**
  → call `list_apps_in_namespace(namespace)` first to discover app names.

- **Who calls INTO this app?** (upstream / callers)
  → call `fetch_wcnp_upstream_dependencies(app_name, namespace)`

- **What does this app call OUT TO?** (downstream / dependencies)
  → call `fetch_wcnp_downstream_dependencies(app_name, namespace)`

### OneOps
Use when the app is deployed via OneOps.
You need: `org` + `platform` + `assembly`

- **Who calls INTO this app?** (upstream)
  → call `fetch_oneops_upstream_dependencies(org, platform, assembly)`

- **What does this app call OUT TO?** (downstream)
  → call `fetch_oneops_downstream_dependencies(org, platform, assembly)`

### Managed Services (upstream callers only — no downstream)
Use for infrastructure services. Only upstream callers are available.

| Service     | Tool                                    | Required params                              |
|-------------|----------------------------------------|----------------------------------------------|
| Cassandra   | fetch_cassandra_upstream_dependencies  | assembly, platform                           |
| MeghaCache  | fetch_meghacache_upstream_dependencies | assembly, platform                           |
| Cosmos DB   | fetch_cosmos_upstream_dependencies     | resource_group, subscription_id, database_name |
| SQL Server  | fetch_sqlserver_upstream_dependencies  | resource_group, subscription_id, database_name |

## Decision tree

```
User asks about an app dependency
│
├── Is it a managed service (Cassandra / MeghaCache / Cosmos / SQL)?
│   └── YES → use the matching fetch_*_upstream_dependencies tool
│
└── NO → What platform?
    ├── WCNP / Kubernetes (has namespace)
    │   ├── Only namespace given → list_apps_in_namespace first
    │   ├── Need upstream (callers) → fetch_wcnp_upstream_dependencies
    │   └── Need downstream (deps) → fetch_wcnp_downstream_dependencies
    │
    └── OneOps (has org/platform/assembly)
        ├── Need upstream (callers) → fetch_oneops_upstream_dependencies
        └── Need downstream (deps) → fetch_oneops_downstream_dependencies
```
""".strip()


@mcp.resource("dependency://agent-guide")
def agent_guide() -> str:
    """Tool selection guide — helps the client LLM pick the right dependency tool."""
    return _AGENT_GUIDE


# ── Prompts ───────────────────────────────────────────────────────────────────

@mcp.prompt("trace_wcnp_app")
def trace_wcnp_app(app_name: str, namespace: str) -> str:
    """Full dependency picture for a WCNP app — fetches both upstream and downstream."""
    return (
        f"Fetch the complete dependency picture for the WCNP application '{app_name}' "
        f"in namespace '{namespace}'.\n\n"
        f"Steps:\n"
        f"1. Call fetch_wcnp_upstream_dependencies(app_name='{app_name}', namespace='{namespace}') "
        f"to find all services that call INTO this app.\n"
        f"2. Call fetch_wcnp_downstream_dependencies(app_name='{app_name}', namespace='{namespace}') "
        f"to find all services this app calls OUT TO.\n"
        f"3. Summarise: total upstream count, total downstream count, "
        f"highlight any T0-tier dependencies as critical."
    )


@mcp.prompt("trace_oneops_app")
def trace_oneops_app(org: str, platform: str, assembly: str) -> str:
    """Full dependency picture for a OneOps app — fetches both upstream and downstream."""
    return (
        f"Fetch the complete dependency picture for the OneOps application "
        f"org='{org}' platform='{platform}' assembly='{assembly}'.\n\n"
        f"Steps:\n"
        f"1. Call fetch_oneops_upstream_dependencies(org='{org}', platform='{platform}', "
        f"assembly='{assembly}') to find all services that call INTO this app.\n"
        f"2. Call fetch_oneops_downstream_dependencies(org='{org}', platform='{platform}', "
        f"assembly='{assembly}') to find all services this app calls OUT TO.\n"
        f"3. Summarise: total upstream count, total downstream count, "
        f"highlight any T0-tier dependencies as critical."
    )


