---
name: edge-triage
description: >
  Edge network analysis across Akamai CDN, Torbit traversal, and F5 load balancers.
  Traces a URL or curl command through all layers of the edge network stack using
  Reliatrace probes. Use when the user asks to "analyze edge network", "trace a URL",
  "check CDN", "Akamai analysis", "Torbit analysis", "F5 analysis", "debug routing",
  "check edge cache", "compare CDN", "network analysis on <url>", or provides a URL
  and asks about edge/CDN/load-balancer behaviour.
metadata:
  adk_additional_tools:
    - comprehensive_network_analysis
    - analyze_akamai
    - analyze_torbit
    - analyze_f5
    - compare_akamai_torbit
    - compare_akamai_torbit_f5
---

# Edge Network Triage

## When to Use This Skill

Activate this skill when the user asks about:
- Edge network analysis on a URL or curl command
- Akamai CDN cache, routing, or edge behaviour
- Torbit traversal (live/staging), backend hosts, WCP routing
- F5 load balancer pool members, virtual servers, SCUS/EUS routing
- Comparing CDN platforms (Akamai vs Torbit, or all three)
- Tracing, debugging, or analysing a request through the network stack
- Cache headers, edge routing, backend URL resolution
- "Why is this URL slow / returning errors / routing wrong?"

Do **NOT** use this skill for:
- WCNP application health (CPU, memory, pods) -> use `health-triage`
- Kubernetes deployment checks -> use `deployment-check`
- Incident investigation -> use `incident-rca`

## Required Information

You need a **URL or curl command** to analyse. Examples:
- `https://www.walmart.com`
- `https://www.walmart.com/ip/12345678`
- `curl -H "Host: www.walmart.com" https://www.walmart.com/some/path`

If the user doesn't provide one, ask for it.

---

## Tool Selection Guide

| User Intent | Tool to Use |
|---|---|
| General "analyse this URL" / "trace this request" / no specific platform mentioned | `comprehensive_network_analysis` |
| Mentions **Akamai**, CDN, edge cache, edge routing | `analyze_akamai` |
| Mentions **Torbit**, traversal, staging vs live, WCP host | `analyze_torbit` |
| Mentions **F5**, load balancer, pool member, SCUS, EUS | `analyze_f5` |
| Compare **Akamai vs Torbit** or check CDN-to-origin parity | `compare_akamai_torbit` |
| Compare **all three** (Akamai + Torbit + F5) or full cross-platform routing | `compare_akamai_torbit_f5` |

> **Default**: When in doubt, use `comprehensive_network_analysis`. It runs all
> probes (Akamai + Torbit Live/Staging + F5 SCUS/EUS) and includes consistency checks.

---

## MANDATORY Workflow

### Step 1: Identify the URL or curl command

Extract the URL or full curl command from the user's request. If the user provides
a bare hostname (e.g., `walmart.com`), prepend `https://`.

### Step 2: Select and Run the Appropriate Tool

Based on the Tool Selection Guide above, call the right tool:

```
comprehensive_network_analysis(url_or_curl="https://www.walmart.com")
```

All six tools accept a single parameter:
- **`url_or_curl`** (string) — the URL or full curl command to analyse

### Step 3: Present Results

Display the results in a clear, structured format:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 EDGE NETWORK ANALYSIS — <url>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

For each probe layer, show:
- **Status Code** — HTTP response code
- **Backend URL** — where the request was routed
- **Cache Status** — HIT / MISS / EXPIRED / N/A
- **Routing Path** — edge → origin chain
- **Key Headers** — relevant CDN/LB response headers

### Step 4: Highlight Issues

Flag any anomalies:
- **Status code mismatches** across platforms (e.g., Akamai returns 200 but F5 returns 503)
- **Routing inconsistencies** (different backends for same URL)
- **Cache misses** on content that should be cached
- **SSL/TLS issues** at any layer
- **Latency outliers** if timing data is available

### Step 5: Provide Recommendations

Based on the findings, suggest:
- Which layer is causing the issue (CDN, Torbit, F5, origin)
- Whether to escalate to a specific team (Edge team, Platform, App team)
- Quick mitigation steps if applicable

---

## Combining with Other Skills

Edge triage often feeds into deeper investigation:

- If the backend URL points to a WCNP app, suggest running `health-triage` on that app
- If routing recently changed, suggest checking `deployment-check` for recent deployments
- If an incident is active, reference `incident-rca` for root cause analysis
- If dependency issues are suspected, suggest `dependency-mapping`

---

## Important Rules

- **Always use `comprehensive_network_analysis` as the default** unless the user
  explicitly asks about a specific platform
- **Pass the URL exactly as provided** — don't strip query parameters or fragments
- **For curl commands**, pass the entire curl command string as `url_or_curl`
- **Show all probe results** even if some return errors — partial data is still useful
- **Never guess at routing behaviour** — always run the tool first and report facts
