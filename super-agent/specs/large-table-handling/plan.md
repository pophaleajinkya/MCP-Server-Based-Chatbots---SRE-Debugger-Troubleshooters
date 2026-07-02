# Implementation Plan: Large Table Handling

**Feature**: `large-table-handling` | **Date**: 2026-04-02 | **Spec**: `spec.md`
**Input**: Feature specification from `specs/large-table-handling/spec.md`

> **Audience**: AI coding assistants (Copilot, Wibey, Claude).
> Follow this plan step-by-step when refactoring any MCP server's list/table
> response builder to adopt the `table_data` contract.

---

## Summary

Refactor an MCP server's response builder to use the `table_data` contract so
the Super Agent hook automatically strips large row sets before the LLM sees
them.  No changes to core functions, services, or models — only the response
builder function.

---

## Technical Context

**Language**: Python 3.11+
**Framework**: MCP server (FastMCP / custom)
**Hook system**: Super Agent `session_hooks.py` → `after_tool_callback`
**UI restore**: Super Agent `runner.py` → `render_table_data` SSE event
**Testing**: pytest (unit tests for `_build_summary`, integration for hook stripping)

---

## Step-by-Step Refactoring

### Step 1: Define `_DISPLAY_COLUMNS`

Create a module-level constant — single source of truth for table columns.
Place it near the top of the file, after imports and singletons.

```python
_DISPLAY_COLUMNS = [
    "incidentNumber",
    "shortDescription",
    "priority",
    "isActive",
    "isMajorIncident",
    "type",
    "department",
    "createdAt",
]
```

**How to choose columns**:
- Include only fields a user sees in a table view
- Exclude large text fields (`description`, `workNotes`, `comments`)
- Exclude internal IDs (`sysId`, `deploymentId[]`)
- Exclude raw timestamps that have formatted equivalents
- Typically 6-10 columns

### Step 2: Project rows to display columns only

Inside the response builder, create projected rows:

```python
table_rows = [
    {col: r.get(col) for col in _DISPLAY_COLUMNS}
    for r in results
]
```

This keeps each row small (8 fields instead of 40), reducing token count even
for rows the LLM sees in the inline sample.

### Step 3: Build the `table_data` object

Add `table_data` as a top-level key in the response:

```python
"table_data": {
    "columns": list(_DISPLAY_COLUMNS),
    "rows":    table_rows,
}
```

### Step 4: Keep a small sample for LLM inline context

The LLM still needs a few rows for data shape and simple lookups.
Cap at 25 items under a domain-specific key:

```python
"incidents":   results[:FULL_DATA_THRESHOLD],    # incident-mcp
"checks":      results[:FULL_DATA_THRESHOLD],    # health-mcp
"deployments": results[:FULL_DATA_THRESHOLD],    # deploy-mcp
```

This key is NOT stripped — it stays in the LLM context.  Keep it at ≤25.

### Step 5: Build `_build_summary()` helper

Create a helper function that computes pre-computed statistics from ALL results.
The LLM uses this instead of scanning rows.

See `summary-enrichment.md` in this folder for the full pattern and
domain-specific examples.

```python
"summary": _build_summary(results, filters_applied),
```

### Step 6: Remove old bulk data keys

Delete any key that previously sent all rows to the LLM:

```python
# DELETE these lines:
response["full_results_data"] = results     # ← all 2000 rows to LLM!
response["all_checks"]        = results     # ← same problem
response["all_results"]       = results     # ← same problem
```

These are replaced by `table_data.rows` (for UI) + `summary` (for LLM).

### Step 7: Update `display_hint`

Reference `_DISPLAY_COLUMNS` so the LLM knows which columns to render:

```python
"display_hint": (
    "Display ALL data in a markdown table using table_data. "
    f"Columns: {' | '.join(_DISPLAY_COLUMNS)}. "
    "Do not omit any rows or columns."
),
```

---

## Complete Before/After — Incident MCP

### BEFORE (broken — hook ignores this)

```python
FULL_DATA_THRESHOLD = 25

def _build_list_response(results, filters_applied, extra=None):
    total = len(results)
    response = {
        "status":          "success",
        "total_count":     total,
        "filters_applied": filters_applied,
        "message":         f"Found {total} incident(s) matching: {filters_applied}",
        "display_hint": (
            "Display ALL incidents in a markdown table. "
            "Columns: incidentNumber | shortDescription | priority | isActive | "
            "isMajorIncident | type | department | createdAt | openedAt. "
            "Do not omit any rows or columns."
        ),
    }
    if extra:
        response.update(extra)

    if total > FULL_DATA_THRESHOLD:
        response["incidents"]         = results[:FULL_DATA_THRESHOLD]
        response["full_results_data"] = results   # ALL rows → LLM context!
    else:
        response["incidents"] = results
    return response
```

**Why it's broken**: `full_results_data` is not `table_data` — the hook
ignores it.  All 2,000 rows go to the LLM.  Context overflows after 2 queries.

### AFTER (correct — hook strips automatically)

```python
FULL_DATA_THRESHOLD = 25

_DISPLAY_COLUMNS = [
    "incidentNumber",
    "shortDescription",
    "priority",
    "isActive",
    "isMajorIncident",
    "type",
    "department",
    "createdAt",
]


def _build_summary(results: list[dict[str, Any]], filters_applied: str) -> str:
    """Compute rich text summary — see summary-enrichment.md for full pattern."""
    total = len(results)
    if total == 0:
        return f"No incidents found matching: {filters_applied}"

    active_count   = sum(1 for r in results if r.get("isActive") is True)
    inactive_count = total - active_count

    majors       = [r for r in results if r.get("isMajorIncident") is True]
    major_active = sum(1 for r in majors if r.get("isActive") is True)

    priority_counts: dict[str, int] = {}
    for r in results:
        p = r.get("priority") or "Unknown"
        priority_counts[p] = priority_counts.get(p, 0) + 1
    priority_line = ", ".join(f"{p}: {c}" for p, c in sorted(priority_counts.items()))

    latest_per_priority: dict[str, dict] = {}
    for r in results:
        p  = r.get("priority") or "Unknown"
        ts = r.get("createdAt") or ""
        prev = latest_per_priority.get(p)
        if prev is None or str(ts) > str(prev.get("createdAt", "")):
            latest_per_priority[p] = r

    latest_lines = [
        f"  {p}: {inc.get('incidentNumber', '?')} at {inc.get('createdAt', '?')}"
        for p, inc in sorted(latest_per_priority.items())
    ]

    return "\n".join([
        f"Found {total} incident(s) matching: {filters_applied}",
        f"Total: {total} — Active: {active_count}, Inactive: {inactive_count}",
        f"Major incidents: {len(majors)} (Active: {major_active}, Inactive: {len(majors) - major_active})",
        f"Priority breakdown: {priority_line}",
        "Latest incident per priority:",
        *latest_lines,
    ])


def _build_list_response(results, filters_applied, extra=None):
    total = len(results)
    table_rows = [{col: r.get(col) for col in _DISPLAY_COLUMNS} for r in results]

    response = {
        "status":          "success",
        "total_count":     total,
        "filters_applied": filters_applied,
        "summary":         _build_summary(results, filters_applied),
        "incidents":       results[:FULL_DATA_THRESHOLD],
        "table_data": {
            "columns": list(_DISPLAY_COLUMNS),
            "rows":    table_rows,
        },
        "display_hint": (
            "Display ALL incidents in a markdown table using table_data. "
            f"Columns: {' | '.join(_DISPLAY_COLUMNS)}. "
            "Do not omit any rows or columns."
        ),
    }
    if extra:
        response.update(extra)
    return response
```

### What changed

| # | Change | Why |
|---|---|---|
| 1 | Added `_DISPLAY_COLUMNS` constant | Single source of truth for table columns |
| 2 | Rows projected to display columns (8 fields, not 40) | Reduces token count per row |
| 3 | `table_data` with `columns` + `rows` at top level | Hook strips automatically when >50 rows |
| 4 | `summary` replaces `message` | Pre-computed stats for LLM analytics |
| 5 | `full_results_data` removed | No longer needed — `table_data.rows` carries all data for UI |
| 6 | `incidents` always capped at 25 | Consistent LLM inline context |
| 7 | `display_hint` references `_DISPLAY_COLUMNS` | LLM knows exact columns to render |

---

## Architecture Flow

```
MCP Server                  Super Agent                        UI
───────────                 ───────────                        ──
_build_list_response()  →   after_tool_callback fires
returns:                    ├─ len(table_data.rows) > 50?
  summary (rich stats)      │   YES → cache full rows in TABLE_ROW_CACHE
  incidents[:25]            │         replace rows with []
  table_data.rows (all)     │         set _rows_stripped = true
                            │   NO  → pass through unchanged
                            └─ return modified response to ADK
                                                           →   runner.py detects _rows_stripped
                                ADK stores stripped response    pops cached rows
                                in Redis (safe for follow-ups)  emits render_table_data SSE
                                                               UI renders complete table
```

---

## Constraints

- **Do NOT touch core functions** — `IncidentService`, `SeedBeesClient`, models, etc.
- **Do NOT touch tool function bodies** — only refactor the shared response builder
- **Do NOT add new dependencies** — pure Python, no external libraries
- **Do NOT change the hook** — the hook is domain-agnostic and already handles `table_data`
- **Do NOT change runner.py** — it already restores `table_data.rows` from cache
