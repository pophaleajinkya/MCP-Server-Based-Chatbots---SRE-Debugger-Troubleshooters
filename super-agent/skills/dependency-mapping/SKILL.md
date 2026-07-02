---
name: dependency-mapping
description: >
  Upstream and downstream dependency tracing with visual Mermaid graphs across
  WCNP, OneOps, Cassandra, MeghaCache, Cosmos DB, and SQL Server. Use when the
  user asks "who calls this app?", "what does this app depend on?", "show
  dependency graph", "blast radius", or "list apps in namespace".
metadata:
  adk_additional_tools:
    - list_apps_in_namespace
    - fetch_wcnp_upstream_dependencies
    - fetch_wcnp_downstream_dependencies
    - fetch_oneops_upstream_dependencies
    - fetch_oneops_downstream_dependencies
    - fetch_cassandra_upstream_dependencies
    - fetch_meghacache_upstream_dependencies
    - fetch_cosmos_upstream_dependencies
    - fetch_sqlserver_upstream_dependencies
    - get_wcnp_dependency_graph
    - get_oneops_dependency_graph
    - get_cassandra_dependency_graph
    - get_meghacache_dependency_graph
    - get_cosmos_dependency_graph
    - get_sqlserver_dependency_graph
---

# Dependency Mapping

## When to Use This Skill

Activate this skill when the user asks about:
- Upstream dependencies ("who calls cart-service?")
- Downstream dependencies ("what does cart-service depend on?")
- Dependency graphs / visual diagrams
- Blast radius analysis ("what's impacted if this goes down?")
- Listing all apps in a namespace
- Cross-platform dependency tracing

## Platform Decision Matrix

| App Platform | Upstream Tool | Downstream Tool | Graph Tool |
|---|---|---|---|
| WCNP (Kubernetes) | `fetch_wcnp_upstream_dependencies` | `fetch_wcnp_downstream_dependencies` | `get_wcnp_dependency_graph` |
| OneOps | `fetch_oneops_upstream_dependencies` | `fetch_oneops_downstream_dependencies` | `get_oneops_dependency_graph` |
| Cassandra | `fetch_cassandra_upstream_dependencies` | — | `get_cassandra_dependency_graph` |
| MeghaCache | `fetch_meghacache_upstream_dependencies` | — | `get_meghacache_dependency_graph` |
| Cosmos DB | `fetch_cosmos_upstream_dependencies` | — | `get_cosmos_dependency_graph` |
| SQL Server | `fetch_sqlserver_upstream_dependencies` | — | `get_sqlserver_dependency_graph` |

**Note**: Managed services (Cassandra, MeghaCache, Cosmos, SQL Server) only have
upstream dependencies — they don't call other services.

## Step-by-Step Workflows

### Workflow 1: Full WCNP Dependency View

Run upstream and downstream in parallel:
```
fetch_wcnp_upstream_dependencies(app_name=<app>, namespace=<namespace>)
fetch_wcnp_downstream_dependencies(app_name=<app>, namespace=<namespace>)
```

For a visual graph:
```
get_wcnp_dependency_graph(app_name=<app>, namespace=<namespace>)
```

The graph is returned as Mermaid flowchart markup.

### Workflow 2: List Apps in a Namespace

```
list_apps_in_namespace(namespace=<namespace>)
```

### Workflow 3: Blast Radius Analysis

1. Get upstream dependencies (who calls this app)
2. For each upstream caller, check their health (load health-triage skill)
3. Get downstream dependencies (what this app calls)
4. Check if any incidents exist for related services (load incident-rca skill)

### Workflow 4: Cross-Platform Dependencies

For a WCNP app that depends on Cassandra:
```
# WCNP dependencies
fetch_wcnp_downstream_dependencies(app_name=<app>, namespace=<namespace>)

# Cassandra callers (to confirm the relationship)
fetch_cassandra_upstream_dependencies(assembly=<assembly>, platform=<platform>)
```

## Important Rules

- **Run upstream + downstream in parallel** for faster results
- **Mermaid graphs** are rendered as visual diagrams in the UI
- Dependency data is merged from SRE-OPS and Topology API for comprehensive coverage
