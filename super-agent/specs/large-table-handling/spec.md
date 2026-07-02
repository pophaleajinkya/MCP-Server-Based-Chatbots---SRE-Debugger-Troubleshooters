# Spec: Large Table Handling — `table_data` Response Contract

**Feature**: `large-table-handling` | **Date**: 2026-04-02 | **Status**: Active
**Input**: Super Agent hook system (`session_hooks.py`, `runner.py`)

> **Audience**: AI coding assistants (Copilot, Wibey, Claude) + MCP server developers.
> This spec is auto-loaded as context when editing any MCP server that returns
> tabular data to the Super Agent.

---

## Summary

MCP tool responses with large row sets (50–2,000+ rows) overflow the LLM's
context window, bloat Redis session storage, and waste tokens.  The Super Agent
provides a generic hook that automatically strips large rows before the LLM
sees them and restores them for the UI.  For this to work, every MCP server
returning tabular data **must** follow the `table_data` contract.

---

## User Scenarios

### P1 — Core: Hook strips large rows automatically

**Given** an MCP server returns `table_data.rows` with >50 rows
**When** the Super Agent's `after_tool_callback` fires
**Then** rows are cached in `TABLE_ROW_CACHE`, replaced with `[]`, and `_rows_stripped: true` is set
**And** the LLM receives `summary` + 25-item sample + empty rows
**And** `runner.py` restores full rows from cache for the UI via `render_table_data` SSE event

### P1 — Contract compliance

**Given** an MCP server that returns list/table data
**When** the response uses `full_results_data` or any key other than `table_data`
**Then** the hook ignores it and ALL rows go to the LLM — causing context overflow
**And** this is a bug that must be fixed by adopting the `table_data` contract

### P2 — Rich summary for analytical questions

**Given** the hook strips rows to `[]`
**When** the user asks "how many P1 incidents?" or "any active majors?"
**Then** the LLM answers from the pre-computed `summary` field — no row scanning needed

### P2 — Multi-user isolation

**Given** two users hit the same Super Agent process concurrently
**When** User A's tool response is cached
**Then** User B cannot access User A's cached rows (session-scoped keys)

### P3 — Memory safety

**Given** many concurrent sessions produce cached rows
**When** cache exceeds 200 entries or entries age past 5 minutes
**Then** stale entries are evicted automatically

---

## Requirements

### FR-001: `table_data` must be a top-level key

The response dict must contain `table_data` at the top level — not nested
inside another object.

```json
{
  "table_data": {
    "columns": ["col1", "col2", "col3"],
    "rows": [
      {"col1": "val", "col2": 42, "col3": true}
    ]
  }
}
```

### FR-002: `columns` is required

`table_data.columns` must be a `list[str]` — ordered column names for the
table header.  Drives UI rendering and `display_hint`.

### FR-003: `rows` is a list of dicts

`table_data.rows` must be a `list[dict]` — each dict has keys matching
`columns`.  Not a list of lists, not a list of strings.

### FR-004: Rows must be projected

Each row should only contain the columns listed in `columns` (projected view).
Do not include all 40 fields from the raw data — only the 6-10 fields the user
sees in the table.

### FR-005: Inline sample capped at 25

A separate key (e.g., `incidents`, `checks`, `deploys`) holds ≤25 items for
LLM inline context.  This key is NOT stripped by the hook.

### FR-006: `summary` provides pre-computed statistics

The `summary` field is a multi-line string with:
- Total count + filters applied
- Status breakdown (active/inactive, pass/fail)
- Category distribution (priority, severity, environment)
- Latest item per category with timestamp

See `summary-enrichment.md` in this folder for the full pattern.

### FR-007: Old bulk keys must be removed

Keys like `full_results_data`, `all_checks`, `all_results` that previously
sent all rows to the LLM must be deleted.  They are replaced by
`table_data.rows` (for UI) + `summary` (for LLM).

---

## Hook Behavior (Super Agent internals)

### Stripping threshold

`_TABLE_ROW_STRIP_THRESHOLD = 50` — rows ≤ 50 pass through unchanged.

### Cache mechanics

| Mechanism | Value | Purpose |
|---|---|---|
| Cache key | `f"{session_id}:{call_id}"` | Prevents cross-user data leakage |
| TTL eviction | 300s (5 min) | Cleans up entries from dropped SSE connections |
| Hard cap | 200 entries | Bounds total memory regardless of load |
| Pop-on-read | one-time consume | runner.py deletes entry after restoring rows |

### What the hook produces

```json
{
  "table_data": {
    "columns": ["incidentNumber", "priority", "isActive", "createdAt"],
    "rows": [],
    "_rows_stripped": true
  }
}
```

### Redis safety

ADK stores the **modified** (stripped) response in Redis.  On follow-up turns,
Redis returns the stripped version — 2,000 rows are never re-loaded into the
LLM context.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Fix |
|---|---|---|
| `"full_results_data": results` | Not `table_data` — hook ignores it | Use `table_data.rows` |
| `"table_data": results` (list not dict) | Hook checks `isinstance(table_data, dict)` | Wrap in `{"columns": [...], "rows": results}` |
| `"table_data": {"rows": results}` (no columns) | UI can't render table headers | Add `"columns": list(_DISPLAY_COLUMNS)` |
| Nesting `table_data` inside another key | Hook only checks top-level keys | Move `table_data` to top level |
| Putting all 40 fields in each row | Wastes tokens on hidden columns | Project rows to `_DISPLAY_COLUMNS` only |
| No `summary` field | LLM can't answer analytics with empty rows | Add `_build_summary()` |
| Sample size > 25 | Too many inline rows for LLM | Cap at `FULL_DATA_THRESHOLD = 25` |

---

## Success Criteria

- **SC-001**: Tool responses with >50 rows have `table_data.rows` stripped before reaching the LLM
- **SC-002**: LLM can answer common analytical questions from `summary` alone (no row scanning)
- **SC-003**: UI renders the complete table via `render_table_data` SSE event (restored from cache)
- **SC-004**: No cross-user data leakage under concurrent load
- **SC-005**: Memory usage bounded (≤200 cache entries, 5-min TTL eviction)
- **SC-006**: Context window does not overflow after 10+ follow-up queries on the same dataset

---

## Response Shape — After Hook Processing

What the LLM actually sees:

```json
{
  "status": "success",
  "total_count": 500,
  "filters_applied": "market=MX",
  "summary": "Found 500 incident(s) matching: market=MX\nTotal: 500 — Active: 12, Inactive: 488\nMajor incidents: 5 (Active: 3, Inactive: 2)\nPriority breakdown: 1 - Critical: 4, 2 - High: 27, 3 - Medium: 145, 4 - Low: 324\nLatest incident per priority:\n  1 - Critical: INC52271769 at 2026-04-02 08:15 CST",
  "incidents": ["... first 25 items ..."],
  "table_data": {
    "columns": ["incidentNumber", "shortDescription", "priority", "isActive", "isMajorIncident", "type", "department", "createdAt"],
    "rows": [],
    "_rows_stripped": true
  },
  "display_hint": "Display ALL incidents in a markdown table using table_data. Columns: incidentNumber | shortDescription | ..."
}
```

The LLM has: `summary` (analytics) + `incidents` (25-item sample) + `table_data.columns` (schema) + `total_count` (scale).
The UI has: runner.py restores full `table_data.rows` from cache → renders complete table.
