---
name: cosmos-triage
description: >
  Cosmos DB health triage — checks latency, availability, throttled requests (429s),
  traffic spikes, and RU exhaustion. Use when the user asks about Cosmos DB health,
  throttling, or performance for a specific Cosmos account.
metadata:
  aliases:
    - cosmos-health
    - cosmosdb-triage
  adk_additional_tools:
    - cosmos_check_account_health
    - cosmos_analyze
    - cosmos_query_prometheus
    - fetch_cosmos_upstream_dependencies
    - get_cosmos_dependency_graph
---

# Cosmos DB Triage

## When to Use This Skill

Activate this skill when the user asks about:
- Cosmos DB health ("is my Cosmos account healthy?")
- Throttled requests / 429 errors
- Cosmos DB latency or availability
- RU exhaustion
- Traffic spikes on Cosmos

## 5 Health Checks

| Check | What It Detects |
|---|---|
| Service Latency | Abnormal response times |
| Availability | Drops below 99.9% |
| Throttled Requests | 429 status codes (RU limit hit) |
| Traffic Spikes | Unusual volume changes |
| RU Exhaustion | Request Unit consumption vs provisioned |

## Step-by-Step Workflow

### Step 1: Full Health Check

```
cosmos_check_account_health(account_name=<account>)
```

### Step 2: Targeted Analysis (if needed)

```
cosmos_analyze(account_name=<account>, checks=["throttled", "ru"])
```

Available check values: `latency`, `availability`, `throttled`, `traffic`, `ru`

### Step 3: Custom PromQL (advanced)

```
cosmos_query_prometheus(account_name=<account>, query=<promql>)
```

### Step 4: Check Who Uses This Database

```
fetch_cosmos_upstream_dependencies(resource_group=<rg>,
                                   subscription_id=<sub>,
                                   database_name=<db>)
```

## Important Rules

- **Always start with `cosmos_check_account_health`** for the full picture
- Throttled requests (429s) usually indicate RU provisioning needs increase
- Check upstream dependencies to understand blast radius
