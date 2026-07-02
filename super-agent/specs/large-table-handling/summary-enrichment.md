# Summary Enrichment for Large Datasets

**Feature**: `large-table-handling` | **Date**: 2026-04-02
**Spec**: `spec.md` | **Plan**: `plan.md`

> **Audience**: AI coding assistants (Copilot, Wibey, Claude).
> Read this when building or refactoring `_build_summary()` functions in
> any MCP server that uses the `table_data` contract.

---

## Why Summaries Matter

When the Super Agent hook strips `table_data.rows` (see `spec.md`),
the LLM sees `rows: []`.  Without a summary, the LLM cannot answer:

- "How many P1 incidents are there?"
- "Are there any active major incidents?"
- "What's the latest critical incident?"
- "Show me the priority breakdown"

The `summary` field provides **pre-computed statistics** so the LLM answers
these questions instantly — no row scanning needed.

---

## Summary Anatomy — 4 Required Sections

### 1. Headline — Total count + filters applied

```
Found 500 incident(s) matching: market=MX, is_active=true
```

Tells the LLM what the dataset contains and what filters produced it.

### 2. Status breakdown — Count by primary status dimension

```
Total: 500 — Active: 12, Inactive: 488
```

The most important binary split for the domain (active/inactive, pass/fail,
success/error, open/closed).

### 3. Category distribution — Count by primary grouping dimension

```
Priority breakdown: 1 - Critical: 4, 2 - High: 27, 3 - Medium: 145, 4 - Low: 324
Major incidents: 5 (Active: 3, Inactive: 2)
```

Distribution across the main categorical dimension.  Include sub-status
breakdowns for important categories (e.g., major incidents split by active/inactive).

### 4. Latest per category — Most recent item in each group

```
Latest incident per priority:
  1 - Critical: INC52271769 at 2026-04-02 08:15 CST (32 min ago)
  2 - High: INC52271800 at 2026-04-02 07:58 CST (49 min ago)
  3 - Medium: INC52271812 at 2026-04-02 08:42 CST (5 min ago)
```

Critical for time-sensitive domains.  Lets the LLM answer "what's the latest P1?"
without scanning rows.

---

## Real Example — Incident MCP `_build_summary()`

Actual implementation from `maof-incident-agent/src/mcp_server/tools/incident.py`:

```python
def _build_summary(results: list[dict[str, Any]], filters_applied: str) -> str:
    """Compute a rich text summary from the result set.

    The LLM receives this summary instead of scanning all rows, so it can
    answer follow-up questions ("how many P1s?", "any active majors?")
    without needing the full table_data.rows in context.
    """
    total = len(results)
    if total == 0:
        return f"No incidents found matching: {filters_applied}"

    # ── Active / Inactive ────────────────────────────────────────────────
    active_count   = sum(1 for r in results if r.get("isActive") is True)
    inactive_count = total - active_count

    # ── Major incidents ──────────────────────────────────────────────────
    majors         = [r for r in results if r.get("isMajorIncident") is True]
    major_active   = sum(1 for r in majors if r.get("isActive") is True)
    major_inactive = len(majors) - major_active

    # ── Priority distribution ────────────────────────────────────────────
    priority_counts: dict[str, int] = {}
    for r in results:
        p = r.get("priority") or "Unknown"
        priority_counts[p] = priority_counts.get(p, 0) + 1
    priority_line = ", ".join(
        f"{p}: {c}" for p, c in sorted(priority_counts.items())
    )

    # ── Latest incident per priority ─────────────────────────────────────
    latest_per_priority: dict[str, dict[str, Any]] = {}
    for r in results:
        p = r.get("priority") or "Unknown"
        ts = r.get("createdAt") or ""
        prev = latest_per_priority.get(p)
        if prev is None or str(ts) > str(prev.get("createdAt", "")):
            latest_per_priority[p] = r

    latest_lines = []
    for p in sorted(latest_per_priority):
        inc = latest_per_priority[p]
        latest_lines.append(
            f"  {p}: {inc.get('incidentNumber', '?')} at {inc.get('createdAt', '?')}"
        )

    # ── Assemble ─────────────────────────────────────────────────────────
    parts = [
        f"Found {total} incident(s) matching: {filters_applied}",
        f"Total: {total} — Active: {active_count}, Inactive: {inactive_count}",
        f"Major incidents: {len(majors)} (Active: {major_active}, Inactive: {major_inactive})",
        f"Priority breakdown: {priority_line}",
        "Latest incident per priority:",
        *latest_lines,
    ]
    return "\n".join(parts)
```

### Sample output

```
Found 500 incident(s) matching: market=MX
Total: 500 — Active: 12, Inactive: 488
Major incidents: 5 (Active: 3, Inactive: 2)
Priority breakdown: 1 - Critical: 4, 2 - High: 27, 3 - Medium: 145, 4 - Low: 324
Latest incident per priority:
  1 - Critical: INC52271769 at 2026-04-02 08:15 CST (32 min ago)
  2 - High: INC52271800 at 2026-04-02 07:58 CST (49 min ago)
  3 - Medium: INC52271812 at 2026-04-02 08:42 CST (5 min ago)
  4 - Low: INC52271815 at 2026-04-02 08:40 CST (7 min ago)
```

### What the LLM can answer from this summary alone

| User Question | Answer Source |
|---|---|
| "How many incidents total?" | Line 1: `Found 500` |
| "How many are active?" | Line 2: `Active: 12` |
| "Any active major incidents?" | Line 3: `Active: 3` |
| "How many P1 incidents?" | Line 4: `1 - Critical: 4` |
| "What's the latest P1?" | Line 6: `INC52271769 at 2026-04-02 08:15` |
| "Priority breakdown?" | Line 4: full distribution |

---

## Generic Template — Adapt for Any Domain

```python
def _build_summary(results: list[dict], filters_applied: str) -> str:
    total = len(results)
    if total == 0:
        return f"No results found matching: {filters_applied}"

    # ── 1. Status breakdown ──────────────────────────────────────────
    # Replace "isActive" with your domain's primary boolean dimension:
    #   Health checks  → "status" == "pass"
    #   Deployments    → "status" == "success"
    #   Audit logs     → "result" == "success"
    active = sum(1 for r in results if r.get("isActive") is True)
    inactive = total - active

    # ── 2. Sub-group breakdown (optional) ────────────────────────────
    # Replace with your domain's important sub-group:
    #   Incidents  → isMajorIncident
    #   Health     → isCriticalCheck
    #   Deploys    → isProduction
    subgroup = [r for r in results if r.get("isMajorIncident") is True]
    sub_active = sum(1 for r in subgroup if r.get("isActive") is True)
    sub_inactive = len(subgroup) - sub_active

    # ── 3. Category distribution ─────────────────────────────────────
    # Replace "priority" with your domain's primary category:
    #   Health checks  → "checkName" or "severity"
    #   Deployments    → "environment"
    #   Audit logs     → "action"
    #   Metrics        → "metric"
    counts: dict[str, int] = {}
    for r in results:
        cat = r.get("priority") or "Unknown"
        counts[cat] = counts.get(cat, 0) + 1
    dist_line = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))

    # ── 4. Latest per category ───────────────────────────────────────
    # Replace "createdAt" with your domain's timestamp field:
    #   Health checks  → "timestamp"
    #   Deployments    → "startedAt"
    #   Audit logs     → "timestamp"
    latest: dict[str, dict] = {}
    for r in results:
        cat = r.get("priority") or "Unknown"
        ts = r.get("createdAt") or ""
        prev = latest.get(cat)
        if prev is None or str(ts) > str(prev.get("createdAt", "")):
            latest[cat] = r

    latest_lines = []
    for cat in sorted(latest):
        item = latest[cat]
        latest_lines.append(
            f"  {cat}: {item.get('id', '?')} at {item.get('createdAt', '?')}"
        )

    # ── Assemble ─────────────────────────────────────────────────────
    parts = [
        f"Found {total} result(s) matching: {filters_applied}",
        f"Total: {total} — Active: {active}, Inactive: {inactive}",
        f"Sub-group: {len(subgroup)} (Active: {sub_active}, Inactive: {sub_inactive})",
        f"Distribution: {dist_line}",
        "Latest per category:",
        *latest_lines,
    ]
    return "\n".join(parts)
```

---

## Domain-Specific Examples

### Health Checks (health-mcp)

```python
_DISPLAY_COLUMNS = ["checkName", "status", "cluster", "namespace", "app", "value", "threshold", "timestamp"]

def _build_summary(results, filters_applied):
    total = len(results)
    passed  = sum(1 for r in results if r.get("status") == "pass")
    failed  = sum(1 for r in results if r.get("status") == "fail")
    warning = total - passed - failed

    # Failing checks per cluster
    fail_by_cluster = {}
    for r in results:
        if r.get("status") == "fail":
            c = r.get("cluster") or "Unknown"
            fail_by_cluster[c] = fail_by_cluster.get(c, 0) + 1

    # Worst offenders (top 5 failing checks)
    fail_by_check = {}
    for r in results:
        if r.get("status") == "fail":
            name = r.get("checkName") or "Unknown"
            fail_by_check[name] = fail_by_check.get(name, 0) + 1
    worst = sorted(fail_by_check.items(), key=lambda x: -x[1])[:5]

    parts = [
        f"Found {total} health check(s) matching: {filters_applied}",
        f"Status: {passed} passed, {failed} failed, {warning} warning",
        f"Failures by cluster: {', '.join(f'{c}: {n}' for c, n in sorted(fail_by_cluster.items()))}",
        f"Top failing checks: {', '.join(f'{name} ({n}x)' for name, n in worst)}",
    ]
    return "\n".join(parts)
```

### Deployments (deploy-mcp)

```python
_DISPLAY_COLUMNS = ["deployId", "app", "environment", "status", "version", "startedAt", "completedAt"]

def _build_summary(results, filters_applied):
    total = len(results)
    success     = sum(1 for r in results if r.get("status") == "success")
    failed      = sum(1 for r in results if r.get("status") == "failed")
    in_progress = sum(1 for r in results if r.get("status") == "in_progress")

    # Deployments per environment
    by_env = {}
    for r in results:
        env = r.get("environment") or "Unknown"
        by_env[env] = by_env.get(env, 0) + 1

    # Latest deployment per environment
    latest_per_env = {}
    for r in results:
        env = r.get("environment") or "Unknown"
        ts = r.get("startedAt") or ""
        prev = latest_per_env.get(env)
        if prev is None or str(ts) > str(prev.get("startedAt", "")):
            latest_per_env[env] = r

    latest_lines = [
        f"  {env}: {d.get('app', '?')} v{d.get('version', '?')} at {d.get('startedAt', '?')}"
        for env, d in sorted(latest_per_env.items())
    ]

    parts = [
        f"Found {total} deployment(s) matching: {filters_applied}",
        f"Status: {success} success, {failed} failed, {in_progress} in-progress",
        f"By environment: {', '.join(f'{e}: {n}' for e, n in sorted(by_env.items()))}",
        "Latest per environment:",
        *latest_lines,
    ]
    return "\n".join(parts)
```

### Audit Logs (audit-mcp)

```python
_DISPLAY_COLUMNS = ["timestamp", "actor", "action", "resource", "result", "ipAddress"]

def _build_summary(results, filters_applied):
    total = len(results)
    success = sum(1 for r in results if r.get("result") == "success")
    failure = total - success

    # Action type distribution
    by_action = {}
    for r in results:
        a = r.get("action") or "Unknown"
        by_action[a] = by_action.get(a, 0) + 1

    # Top 5 actors by activity count
    by_actor = {}
    for r in results:
        actor = r.get("actor") or "Unknown"
        by_actor[actor] = by_actor.get(actor, 0) + 1
    top_actors = sorted(by_actor.items(), key=lambda x: -x[1])[:5]

    parts = [
        f"Found {total} audit event(s) matching: {filters_applied}",
        f"Results: {success} success, {failure} failure ({failure/total*100:.1f}% failure rate)" if total else "",
        f"Action distribution: {', '.join(f'{a}: {n}' for a, n in sorted(by_action.items()))}",
        f"Top actors: {', '.join(f'{a} ({n} events)' for a, n in top_actors)}",
    ]
    return "\n".join(p for p in parts if p)
```

---

## Key Principles

1. **Summary is computed from ALL rows** — not just the 25-item sample.
   Build it before `_build_list_response` returns, while you still have the
   full result set.

2. **Summary must be self-sufficient** — the LLM should be able to answer
   any common analytical question from the summary alone.

3. **Use the domain's natural dimensions**:
   - Status dimension (active/inactive, pass/fail, success/error)
   - Category dimension (priority, severity, environment, action type)
   - Time dimension (latest per category)

4. **Keep it compact** — typically 5-10 lines.  The summary itself consumes
   LLM tokens, so don't make it longer than necessary.

5. **Handle zero results** — return a simple "No results found" message.

6. **Handle missing fields defensively** — use `r.get("field") or "Unknown"`
   to avoid `None` in output.
