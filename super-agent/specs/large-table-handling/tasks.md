# Tasks: Large Table Handling — Onboarding Checklist

**Feature**: `large-table-handling` | **Date**: 2026-04-02
**Spec**: `spec.md` | **Plan**: `plan.md`

> Use this checklist when onboarding any MCP server to the `table_data` contract.
> Each task is independently verifiable.

---

## Pre-Flight

- [ ] Identify the response builder function (e.g., `_build_list_response`)
- [ ] Confirm it currently sends large row sets to the LLM (look for `full_results_data`, `all_results`, or unbounded `results` keys)
- [ ] Identify the data model fields available (check Pydantic models or API response shape)

---

## Implementation Tasks

### 1. Define `_DISPLAY_COLUMNS`

- [ ] Create module-level `_DISPLAY_COLUMNS` list near the top of the file
- [ ] Include only user-visible table fields (typically 6-10 columns)
- [ ] Exclude: large text fields, internal IDs, raw timestamps with formatted equivalents

**Verify**: The constant exists and contains the correct column names.

### 2. Project rows

- [ ] Add row projection: `{col: r.get(col) for col in _DISPLAY_COLUMNS}` for each result
- [ ] Verify projected rows only contain `_DISPLAY_COLUMNS` keys

**Verify**: `len(row.keys()) == len(_DISPLAY_COLUMNS)` for every row.

### 3. Add `table_data` to response

- [ ] Add `"table_data": {"columns": list(_DISPLAY_COLUMNS), "rows": table_rows}` as a top-level key
- [ ] Ensure `table_data` is NOT nested inside another object

**Verify**: `response["table_data"]["columns"]` and `response["table_data"]["rows"]` exist.

### 4. Cap inline sample

- [ ] Set `FULL_DATA_THRESHOLD = 25` (or reuse existing)
- [ ] Add domain-specific sample: `"incidents": results[:FULL_DATA_THRESHOLD]`
- [ ] Ensure sample is always present (even when total ≤ 25)

**Verify**: `len(response["incidents"]) <= 25` regardless of total count.

### 5. Build `_build_summary()`

- [ ] Create `_build_summary(results, filters_applied)` helper function
- [ ] Include: headline (total + filters), status breakdown, category distribution, latest per category
- [ ] Handle zero results: return `"No results found matching: {filters_applied}"`
- [ ] Handle missing fields: use `r.get("field") or "Unknown"`
- [ ] Add `"summary": _build_summary(results, filters_applied)` to response

**Verify**: Call `_build_summary()` with sample data and confirm output has all 4 sections.

### 6. Remove old bulk keys

- [ ] Delete `full_results_data` key from response
- [ ] Delete any other key that sends all rows (e.g., `all_checks`, `all_results`)
- [ ] Delete old `message` field if replaced by `summary`

**Verify**: Response dict does NOT contain `full_results_data` or similar bulk keys.

### 7. Update `display_hint`

- [ ] Reference `table_data` in the hint text
- [ ] Use `_DISPLAY_COLUMNS` to generate column list dynamically
- [ ] Remove hardcoded column strings

**Verify**: `display_hint` contains "table_data" and matches `_DISPLAY_COLUMNS`.

---

## Validation Tasks

### 8. Test with >50 rows

- [ ] Call the tool with parameters that return >50 results
- [ ] Confirm the Super Agent hook strips `table_data.rows` to `[]`
- [ ] Confirm `_rows_stripped: true` is set in the response
- [ ] Confirm the UI renders the complete table (rows restored from cache)

### 9. Test with ≤50 rows

- [ ] Call the tool with parameters that return ≤50 results
- [ ] Confirm `table_data.rows` passes through unchanged (not stripped)
- [ ] Confirm no `_rows_stripped` marker is set

### 10. Test summary accuracy

- [ ] Verify total count matches actual results
- [ ] Verify active/inactive breakdown sums to total
- [ ] Verify category distribution sums to total
- [ ] Verify latest-per-category timestamps are actually the most recent

### 11. Test follow-up queries

- [ ] Ask a follow-up question that requires the summary (e.g., "how many P1s?")
- [ ] Confirm LLM answers correctly from summary without needing rows
- [ ] Confirm no context window overflow after 5+ follow-up turns

---

## Domain Mapping Reference

Use this table to adapt the generic pattern to your domain:

| Concept | Incidents | Health Checks | Deployments | Audit Logs |
|---|---|---|---|---|
| Sample key | `incidents` | `checks` | `deployments` | `events` |
| Status field | `isActive` | `status` (pass/fail) | `status` (success/failed) | `result` (success/failure) |
| Category field | `priority` | `checkName` / `severity` | `environment` | `action` |
| Sub-group | `isMajorIncident` | `isCriticalCheck` | `isProduction` | — |
| Timestamp field | `createdAt` | `timestamp` | `startedAt` | `timestamp` |
| ID field | `incidentNumber` | `checkId` | `deployId` | `eventId` |
