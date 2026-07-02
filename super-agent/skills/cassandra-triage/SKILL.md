---
name: cassandra-triage
description: >
  Cassandra cluster health triage — checks unavailable exceptions, timeout spikes,
  P99 latency anomalies, and bad-node detection. Use when the user asks about
  Cassandra health, timeouts, or latency for a specific cluster.
metadata:
  aliases:
    - cassandra-health
  adk_additional_tools:
    - cassandra_check_cluster_health
    - cassandra_analyze
    - cassandra_query_prometheus
    - fetch_cassandra_upstream_dependencies
    - get_cassandra_dependency_graph
---

# Cassandra Triage

## When to Use This Skill

Activate this skill when the user asks about:
- Cassandra cluster health
- Unavailable exceptions
- Timeout spikes
- P99 latency anomalies
- Bad node detection

## 4 Health Checks

| Check | What It Detects |
|---|---|
| Unavailable Exceptions | Consistency level failures |
| Timeout Spikes | Read/write timeout rate increase |
| P99 Latency Anomalies | Tail latency degradation |
| Bad-Node Detection | Individual node performance outliers |

## Step-by-Step Workflow

### Step 1: Full Health Check

```
cassandra_check_cluster_health(cluster_name=<cluster>)
```

### Step 2: Targeted Analysis

```
cassandra_analyze(cluster_name=<cluster>, checks=["unavailable", "timeouts"])
```

Available check values: `unavailable`, `timeouts`, `latency`, `bad_node`

### Step 3: Custom PromQL (advanced)

```
cassandra_query_prometheus(cluster_name=<cluster>, query=<promql>)
```

### Step 4: Upstream Callers

```
fetch_cassandra_upstream_dependencies(assembly=<assembly>, platform=<platform>)
```

For a visual graph:
```
get_cassandra_dependency_graph(assembly=<assembly>, platform=<platform>)
```
