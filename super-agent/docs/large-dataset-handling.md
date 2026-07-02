# Large Dataset Handling — Developer Guide

How the Super Agent prevents large MCP tool responses from overwhelming the
LLM context window, and how MCP server authors must structure their responses
to opt in.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Architecture Overview](#2-architecture-overview)
3. [The `table_data` Contract](#3-the-table_data-contract)
4. [How the Hook Strips Rows](#4-how-the-hook-strips-rows)
5. [How runner.py Restores Rows for the UI](#5-how-runnerpy-restores-rows-for-the-ui)
6. [Session Safety — Multi-User Isolation](#6-session-safety--multi-user-isolation)
7. [Building Rich Summaries](#7-building-rich-summaries)
8. [Use Cases](#8-use-cases)
9. [Before / After Example — Incident MCP](#9-before--after-example--incident-mcp)
10. [Onboarding Checklist](#10-onboarding-checklist)

---

## 1. The Problem

MCP tools often return large result sets — 200 to 2,000+ rows of incidents,
health checks, deployments, or metric data.  When the LLM receives all of
this in its context window:

| Symptom | Impact |
|---|---|
| **Context overflow** | 200K-token limit exceeded after 2-3 queries → `ContextWindowExceededError` |
| **Redis bloat** | Full history stored in Redis → memory pressure on the session store |
| **Slow follow-ups** | LLM scans thousands of rows to answer "how many P1s?" — slow and unreliable |
| **Token waste** | Paying for 50K tokens of table data the LLM doesn't need |

**Goal**: The LLM sees only a compact summary + a small sample.  The UI gets
ALL rows for rendering tables and charts.

---

## 2. Architecture Overview

```
MCP Server                  Super Agent                        UI
───────────                 ───────────                        ──
tool returns JSON       →   after_tool_callback fires
                            ├─ rows > 50?
                            │   YES → cache full rows in TABLE_ROW_CACHE
                            │         replace rows with []
                            │         set _rows_stripped = true
                            │   NO  → pass through unchanged
                            └─ return modified response to ADK
                                                           →   runner.py detects _rows_stripped
                                                               pops cached rows from TABLE_ROW_CACHE
                                                               emits render_table_data SSE event
                                                               UI renders full table
```

**Key insight**: The hook is domain-agnostic.  It doesn't know what "incidents"
or "health checks" are.  It only looks for `table_data.rows` at the top level
of the JSON response.

---

## 3. The `table_data` Contract

Every MCP server that returns tabular data **must** include a top-level
`table_data` key with this exact shape:

```json
{
  "status": "success",
  "total_count": 500,
  "summary": "Found 500 incident(s)...",
  "incidents": [ /* first 25 items — LLM inline context */ ],
  "table_data": {
    "columns": ["incidentNumber", "priority", "isActive", "createdAt"],
    "rows": [
      {"incidentNumber": "INC001", "priority": "1 - Critical", "isActive": true, "createdAt": "2026-04-02T08:15:00Z"},
      {"incidentNumber": "INC002", "priority": "2 - High", "isActive": false, "createdAt": "2026-04-02T07:30:00Z"}
    ]
  },
  "display_hint": "Display ALL incidents in a markdown table using table_data..."
}
```

### Required fields inside `table_data`

| Field | Type | Description |
|---|---|---|
| `columns` | `list[str]` | Ordered column names — drives table headers in UI |
| `rows` | `list[dict]` | All result rows.  Each row is a dict with keys matching `columns` |

### Rules

1. `table_data` **must be a top-level key** — not nested inside another object.
2. `rows` **must be a list of dicts** — not a list of lists.
3. Each row should only contain the columns listed in `columns` (projected view).
4. Keep a **separate key** (e.g., `incidents`, `checks`) with a small sample
   (≤25 items) for the LLM's inline context.
5. The hook threshold is **50 rows** — if `len(rows) <= 50`, nothing is stripped.

---

## 4. How the Hook Strips Rows

File: `src/app/hooks/session_hooks.py` → `_strip_large_table_rows()`

```python
# Simplified logic
table_data = result.get("table_data")
if isinstance(table_data, dict) and len(table_data.get("rows") or []) > 50:
    TABLE_ROW_CACHE[cache_key] = {"table_data": table_data, "_ts": monotonic()}
    result["table_data"] = {
        **{k: v for k, v in table_data.items() if k != "rows"},
        "rows": [],
        "_rows_stripped": True,
    }
```

What the LLM sees after stripping:

```json
{
  "status": "success",
  "total_count": 500,
  "summary": "Found 500 incidents...\nTotal: 500 — Active: 12, Inactive: 488\n...",
  "incidents": [ /* first 25 */ ],
  "table_data": {
    "columns": ["incidentNumber", "priority", "isActive", "createdAt"],
    "rows": [],
    "_rows_stripped": true
  }
}
```

The LLM gets: `summary` (rich stats) + `incidents` (25-item sample) + empty
`table_data.rows`.  Enough to answer analytical questions without scanning 500 rows.

---

## 5. How runner.py Restores Rows for the UI

File: `src/app/services/runner.py`

When runner.py encounters a tool response with `_rows_stripped: true`:

```python
if resp.get("table_data", {}).get("_rows_stripped"):
    cache_key = table_row_cache_key(session_id, call_id)
    cached = TABLE_ROW_CACHE.pop(cache_key, None)  # consume once
    if cached:
        resp = {**resp, "table_data": cached["table_data"]}
    # emit render_table_data SSE event with full rows
```

The UI receives the complete table via SSE.  The cache entry is popped (deleted)
after use — no lingering data.

---

## 6. Session Safety — Multi-User Isolation

### Session-scoped cache keys

Cache keys are `f"{session_id}:{call_id}"` — never just `call_id`.  This
prevents User A's incident data from leaking to User B even when both hit
the same process concurrently.

### Memory protection

| Mechanism | Value | Purpose |
|---|---|---|
| TTL eviction | 300s (5 min) | Cleans up entries from dropped SSE connections |
| Hard cap | 200 entries | Bounds total memory regardless of load |
| Pop-on-read | one-time | runner.py deletes the entry after consuming it |

### Redis safety

ADK stores the **modified** (stripped) response in Redis.  When a session is
reloaded for follow-up turns, Redis returns the stripped version — the 2,000
rows are never re-sent to the LLM on follow-up queries.

---

## 7. Building Rich Summaries

Since the LLM can't see the rows, it needs pre-computed statistics to answer
questions like "how many P1 incidents?" or "any active majors?".

### Summary anatomy

A good summary includes:

```
Found 500 incident(s) matching: market=MX, is_active=true
Total: 500 — Active: 12, Inactive: 488
Major incidents: 5 (Active: 3, Inactive: 2)
Priority breakdown: 1 - Critical: 4, 2 - High: 27, 3 - Medium: 145, 4 - Low: 324
Latest incident per priority:
  1 - Critical: INC52271769 at 2026-04-02 08:15 CST (32 min ago)
  2 - High: INC52271800 at 2026-04-02 07:58 CST (49 min ago)
  3 - Medium: INC52271812 at 2026-04-02 08:42 CST (5 min ago)
  4 - Low: INC52271815 at 2026-04-02 08:40 CST (7 min ago)
```

### Generic pattern for any domain

```python
def _build_summary(results: list[dict], filters_applied: str) -> str:
    total = len(results)
    if total == 0:
        return f"No results found matching: {filters_applied}"

    # 1. Count by status (active/inactive, pass/fail, success/error)
    active = sum(1 for r in results if r.get("is_active"))
    # 2. Count by category (priority, severity, environment)
    by_category = {}
    for r in results:
        cat = r.get("category") or "Unknown"
        by_category[cat] = by_category.get(cat, 0) + 1
    # 3. Latest per category
    latest = {}
    for r in results:
        cat = r.get("category") or "Unknown"
        ts = r.get("timestamp") or ""
        if cat not in latest or ts > latest[cat]["timestamp"]:
            latest[cat] = r
    # 4. Assemble
    ...
```

See `specs/summary-enrichment.md` for the full reference.

---

## 8. Use Cases

### 8.1 Incidents (incident-mcp)

| Field | Value |
|---|---|
| `_DISPLAY_COLUMNS` | `incidentNumber, shortDescription, priority, isActive, isMajorIncident, type, department, createdAt` |
| Sample key | `incidents` (first 25) |
| Summary stats | active/inactive, major breakdown, priority distribution, latest per priority |
| Typical size | 50–2,000 rows |

### 8.2 Health Checks (health-mcp)

| Field | Value |
|---|---|
| `_DISPLAY_COLUMNS` | `checkName, status, cluster, namespace, app, value, threshold, timestamp` |
| Sample key | `checks` (first 25) |
| Summary stats | pass/fail/warning counts, failing checks per cluster, worst offenders |
| Typical size | 50–500 rows |

### 8.3 Deployments (deploy-mcp)

| Field | Value |
|---|---|
| `_DISPLAY_COLUMNS` | `deployId, app, environment, status, version, startedAt, completedAt` |
| Sample key | `deployments` (first 25) |
| Summary stats | success/failed/in-progress counts, deployments per environment, latest per env |
| Typical size | 100–1,000 rows |

### 8.4 Audit Logs (audit-mcp)

| Field | Value |
|---|---|
| `_DISPLAY_COLUMNS` | `timestamp, actor, action, resource, result, ipAddress` |
| Sample key | `events` (first 25) |
| Summary stats | action type distribution, top actors, success/failure rate |
| Typical size | 500–10,000 rows |

### 8.5 Metric Time-Series (metrics-mcp)

| Field | Value |
|---|---|
| `_DISPLAY_COLUMNS` | `timestamp, metric, value, unit, labels` |
| Sample key | `datapoints` (first 25) |
| Summary stats | min/max/avg/p95 per metric, anomaly count, time range covered |
| Typical size | 200–5,000 rows |

---

## 9. Before / After Example — Incident MCP

### BEFORE (old approach — all data sent to LLM)

```python
def _build_list_response(results, filters_applied, extra=None):
    total = len(results)
    response = {
        "status": "success",
        "total_count": total,
        "message": f"Found {total} incident(s) matching: {filters_applied}",
        "display_hint": "Display ALL incidents in a markdown table...",
    }
    if total > 25:
        response["incidents"] = results[:25]
        response["full_results_data"] = results  # ← ALL 2000 rows to LLM!
    else:
        response["incidents"] = results
    return response
```

**Problems**:
- `full_results_data` sends all 2,000 rows — hook ignores it (not `table_data`)
- No summary — LLM must scan all rows for analytics
- Context window blows up after 2 queries

### AFTER (table_data contract + rich summary)

```python
_DISPLAY_COLUMNS = [
    "incidentNumber", "shortDescription", "priority",
    "isActive", "isMajorIncident", "type", "department", "createdAt",
]

def _build_list_response(results, filters_applied, extra=None):
    total = len(results)
    table_rows = [{col: r.get(col) for col in _DISPLAY_COLUMNS} for r in results]

    response = {
        "status":          "success",
        "total_count":     total,
        "filters_applied": filters_applied,
        "summary":         _build_summary(results, filters_applied),
        "incidents":       results[:25],
        "table_data": {
            "columns": list(_DISPLAY_COLUMNS),
            "rows":    table_rows,
        },
        "display_hint": f"Display ALL incidents using table_data. Columns: {' | '.join(_DISPLAY_COLUMNS)}.",
    }
    if extra:
        response.update(extra)
    return response
```

**What changed**:
- `full_results_data` removed — replaced by `table_data.rows`
- `table_data` follows the contract → hook strips rows > 50 automatically
- `summary` gives the LLM pre-computed stats for analytical questions
- `incidents` still capped at 25 for inline LLM context
- Row projection — each row only has `_DISPLAY_COLUMNS` fields, not all 40

---

## 10. Onboarding Checklist

When adding large-dataset support to a new MCP server:

- [ ] **Define `_DISPLAY_COLUMNS`** — the columns your table needs (single source of truth)
- [ ] **Project rows** — `{col: r.get(col) for col in _DISPLAY_COLUMNS}` for each result
- [ ] **Add `table_data`** — `{"columns": list(_DISPLAY_COLUMNS), "rows": projected_rows}` at top level
- [ ] **Keep a sample key** — e.g., `incidents[:25]` for LLM inline context
- [ ] **Build `_build_summary()`** — pre-computed stats (counts, breakdowns, latest-per-category)
- [ ] **Remove old bulk keys** — delete `full_results_data` or similar keys that sent all rows to the LLM
- [ ] **Update `display_hint`** — reference `table_data` and `_DISPLAY_COLUMNS`
- [ ] **Test with >50 rows** — verify the hook strips rows and the UI still renders the full table
