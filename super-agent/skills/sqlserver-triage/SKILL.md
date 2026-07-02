---
name: sqlserver-triage
description: >
  SQL Server health triage — checks offline status, CPU, storage, I/O latency,
  deadlocks, replication lag, and TempDB usage. Use when the user asks about
  SQL Server health, deadlocks, or performance.
metadata:
  aliases:
    - sqlserver-health
    - sql-server-triage
  adk_additional_tools:
    - sqlserver_check_database_health
    - sqlserver_analyze
    - sqlserver_query_prometheus
    - fetch_sqlserver_upstream_dependencies
    - get_sqlserver_dependency_graph
---

# SQL Server Triage

## When to Use This Skill

Activate this skill when the user asks about:
- SQL Server database health
- Deadlocks or blocking
- CPU or storage pressure
- I/O latency
- Replication lag
- TempDB usage

## 12 Health Checks

Covers: offline status, CPU, storage, I/O latency, deadlocks, replication lag,
TempDB usage, connection count, wait stats, and more.

## Step-by-Step Workflow

### Step 1: Full Health Check

```
sqlserver_check_database_health(database_name=<database>)
```

### Step 2: Targeted Analysis

```
sqlserver_analyze(database_name=<database>, checks=["cpu", "deadlocks", "io_latency"])
```

### Step 3: Custom PromQL (advanced)

```
sqlserver_query_prometheus(database_name=<database>, query=<promql>)
```

### Step 4: Upstream Callers

```
fetch_sqlserver_upstream_dependencies(resource_group=<rg>,
                                      subscription_id=<sub>,
                                      database_name=<db>)
```
