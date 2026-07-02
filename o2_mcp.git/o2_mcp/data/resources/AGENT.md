# OpenObserve MCP Agent Guide (o2_mcp)

This MCP server provides **OpenObserve log querying** for Walmart's Kubernetes
workloads running on WCNP (Walmart Cloud Native Platform). It translates user
questions about application logs, errors, and request traffic into SQL queries
executed against OpenObserve streams.

---

## 1. System Overview

```
User question
    → Agent calls health_mcp to resolve endpoint + stream + filter
        → Agent calls super-agent for a live PingFederate bearer token
            → Agent queries schema → translates question → validates SQL → executes
                → Interprets results, offers follow-up queries
```

**o2_mcp is fully stateless.** Every tool that talks to OpenObserve accepts
`endpoint`, `bearer_token`, `organization`, and `stream` as direct parameters.
The calling agent owns all session state. o2_mcp stores nothing between calls.

The calling agent must:

1. Retrieve the cluster configuration (endpoint, stream, organization, default_filter, cluster_lb) from
   `health_mcp.wcnp_get_o2_config(namespace, app)`.
2. Obtain a live bearer token from `super-agent.pingfed_playwright_token(cluster_lb)`.
3. Pass `endpoint`, `bearer_token`, `organization`, and `stream` to every o2_mcp tool call.
4. Re-call `pingfed_playwright_token` whenever auth expires and pass the new token.

**70 % prompt / 30 % tool philosophy.** Tools return raw data. The value is
in how the agent interprets and presents it. Every section below is actionable
prompt-side knowledge: SQL patterns, field rules, result reading, and follow-up
suggestions. Rely on the guide, not on trial-and-error queries.

---

## 2. Full Agent Workflow

When the user asks about logs, errors, latency, or traffic for a
`namespace` + `app` pair, follow these steps in order.

### Step 1 — Resolve cluster config (health_mcp)

```
config = wcnp_get_o2_config(namespace="my-ns", app="my-app")
```

The response includes:

| Field | Example | Usage |
|---|---|---|
| `endpoint` | `https://intl.logs.prod.walmart.com` | OpenObserve API base URL |
| `stream` | `k8s_json` | Default log stream name |
| `organization` | `default` | O2 org identifier |
| `cluster_lb` | `intl.logs.prod.walmart.com` | Bare hostname, needed for token refresh |
| `default_filter` | `kubernetes_namespace_name='my-ns' AND kubernetes_labels_app='my-app'` | Pre-built WHERE fragment — always inject into your SQL |

### Step 2 — Obtain bearer token (super-agent)

```
auth = pingfed_playwright_token(cluster_lb=config["cluster_lb"])
```

Returns `{"token": "<raw_access_token>"}`. The token is short-lived (typically
60 minutes). Store `cluster_lb` in memory so you can refresh without calling
`wcnp_get_o2_config` again.

### Step 3 — Discover available fields

```python
get_stream_schema(
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    user_prompt  = <original user question>,
)
```

Pass the raw user question so the schema tool prunes the field list to what is
relevant. Check the response for:

- `fields` — grouped by data type (Utf8, Int64, Float64, Boolean)
- `settings.full_text_search_keys` — use `match_all()` for these
- `settings.partition_keys` — use in WHERE for fast, partition-pruning filters
- `total_fields` vs `returned_fields` — if truncated, call again with `fields="field1,field2"` to add more

### Step 4 — Translate the user question to SQL

Apply the ADL SQL rules in Section 4. Incorporate `default_filter` from
`wcnp_get_o2_config` into every WHERE clause.

### Step 5 — Validate before executing

```python
validate_sql_policy(sql=<your_sql>)
```

This is a local AST check (no network call, instant). It catches the three
most common O2-specific mistakes:

- `_timestamp` in WHERE
- `SELECT *`
- Subquery in SELECT clause

If `ok: false`, fix the violations before proceeding. Only call `validate_sql`
(live cluster validation) when you need to confirm complex syntax; it is slower
and uses a short 1-second window.

### Step 6 — Execute

```python
execute_sql(
    sql_query    = <validated_sql>,
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    time_range   = "1h",   # or "3h", "24h", "7d"
)
```

For incident windows use absolute microsecond timestamps:

```python
times = get_time(timezone_name="US/Central", date="2026-04-07",
                 start_time_str="14:00", end_time_str="15:30")

execute_sql(
    sql_query    = <sql>,
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    start_time   = times["date_range"]["start_us"],
    end_time     = times["date_range"]["end_us"],
)
```

### Step 7 — Interpret and present results

See Section 6 (Log Analysis Interpretation Guide) and Section 9 (Result
Presentation). Always offer follow-up queries.

### Step 8 — Auth refresh on 401 / auth_expired

When any tool returns `{"auth_expired": true}` or an HTTP 401:

```python
# 1. Get a fresh token — reuse cluster_lb stored by the agent
auth = pingfed_playwright_token(cluster_lb=<cluster_lb>)

# 2. Retry the failed call with the new bearer_token
execute_sql(..., bearer_token=auth["token"])
```

---

## 3. Tool Selection Guide

| User asks... | Use these tools |
|---|---|
| "What errors in the last hour?" | `get_stream_schema` → `execute_sql` |
| "5XX rate for my app over time" | `execute_sql` with histogram + `GROUP BY status_code` |
| "What happened at 3:15 PM?" | `get_time` for microsecond timestamp → `search_around(timestamp)` |
| "What values does `level` have?" | `get_field_values(fields=["level"])` |
| "What values does `response_code` have?" | `get_field_values(fields=["response_code"], time_range="24h")` |
| "Validate my SQL before running" | `validate_sql_policy(sql)` then `validate_sql(sql)` |
| "What streams are available?" | `list_streams(endpoint, bearer_token)` |
| "What fields does k8s_json have?" | `get_stream_schema(..., full_schema=True)` |
| "Show me error context around this log" | `search_around(timestamp=<us>, endpoint, bearer_token, stream)` |
| "What's the P99 response time?" | `execute_sql` with `approx_percentile_cont(_timestamp, 0.99)` |
| "Show error distribution by pod" | `execute_sql` with `GROUP BY kubernetes_pod_name` |
| "Write me a VRL parser" | `get_o2_rules(intent="vrl")` → write script → `validate_vrl(vrl, endpoint, bearer_token)` |

---

## 4. SQL Translation Guide (ADL Rules — CRITICAL)

This section is the **primary prompt-side knowledge**. Read it fully before
writing a single SQL query. Getting these rules wrong causes silent bad results
or O2 API errors.

### 4.1 General Rules

| Rule | Correct | Wrong |
|---|---|---|
| Time range | Use `time_range` or `start_time`/`end_time` params | `WHERE _timestamp > ...` in SQL |
| COUNT | `count(_timestamp)` | `count(*)` |
| SELECT | Name every field explicitly | `SELECT *` |
| Stream name | `FROM "k8s_json"` (double-quoted) | `FROM k8s_json` (unquoted) |
| SQL dialect | DataFusion only | PostgreSQL/MySQL-specific syntax |
| Schema fields | Only `defined_schema_fields` in SELECT/WHERE | Fields not in the schema |
| Subqueries | In FROM clause or CTE only | Subquery inside SELECT expressions |
| _raw fields | Extract with `spath(_raw, 'key')` or `spath(_raw, 'nested.key')` | Direct WHERE on non-schema fields |

### 4.2 Field Categories (from get_stream_schema)

```
defined_schema_fields   → Indexed UDS fields. Use freely in SELECT, WHERE, GROUP BY.
full_text_search_keys   → FTS-indexed. Use match_all('keyword') for these.
partition_keys          → Use in WHERE to prune partition scans (fast path).
_raw                    → All other fields stored as JSON string. Extract explicitly.
```

**Decision tree for field usage:**

1. Is the field in `defined_schema_fields`? → Use it directly.
2. Is it in `full_text_search_keys`? → Use `match_all('keyword')` for search.
3. Is it in `partition_keys`? → Always include in WHERE when filtering by it.
4. Is it only in `_raw`? → Use `spath(_raw, 'field_name')` to extract a value, or filter with `str_match_ignore_case(_raw, 'keyword')`.

### 4.3 Error / 5XX Analysis Patterns

**Basic 5XX error count with percentile latency:**

```sql
SELECT status_code,
       count(_timestamp)                                         AS total,
       approx_percentile_cont(response_time_ms, 0.95)           AS p95_ms,
       approx_percentile_cont(response_time_ms, 0.99)           AS p99_ms
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND status_code >= 500
GROUP BY status_code
ORDER BY total DESC
LIMIT 100
```

**Error rate as percentage of total traffic:**

```sql
SELECT
    sum(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END)              AS errors,
    count(_timestamp)                                                  AS total,
    CAST(sum(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS FLOAT)
        / NULLIF(count(_timestamp), 0) * 100                          AS error_pct
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
```

**Top error messages (FTS stream):**

```sql
SELECT message,
       count(_timestamp) AS occurrences
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND match_all('error')
GROUP BY message
ORDER BY occurrences DESC
LIMIT 20
```

**5XX grouped by path and pod (when those fields are in schema):**

```sql
SELECT request_path,
       kubernetes_pod_name,
       status_code,
       count(_timestamp)  AS hits
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND status_code >= 500
GROUP BY request_path, kubernetes_pod_name, status_code
ORDER BY hits DESC
LIMIT 50
```

### 4.4 Time Series / Histogram Patterns

**Requests per minute over the last hour:**

```sql
SELECT histogram(_timestamp, 'minute') AS ts,
       count(_timestamp)               AS total
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
GROUP BY ts
ORDER BY ts
```

**Hourly error rate for the last 24 hours:**

```sql
SELECT histogram(_timestamp, 'hour')                          AS ts,
       count(_timestamp)                                       AS total,
       sum(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END)    AS errors
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
GROUP BY ts
ORDER BY ts
```

**Supported histogram intervals:** `second`, `minute`, `hour`, `day`, `week`.

**P99 latency per minute (time series):**

```sql
SELECT histogram(_timestamp, 'minute')               AS ts,
       approx_percentile_cont(response_time_ms, 0.99) AS p99_ms,
       approx_percentile_cont(response_time_ms, 0.95) AS p95_ms,
       count(_timestamp)                               AS requests
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
GROUP BY ts
ORDER BY ts
```

### 4.5 Full Text Search Rules

Use `match_all()` only for fields listed in `full_text_search_keys`. For all
other fields use `str_match_ignore_case()`.

```sql
-- FTS-indexed field (e.g. "log" or "message" is in full_text_search_keys):
WHERE match_all('NullPointerException')

-- Non-indexed field — slower but correct:
WHERE str_match_ignore_case(message, 'NullPointerException')

-- Both types in the same query:
WHERE match_all('timeout')
  AND str_match_ignore_case(kubernetes_pod_name, 'worker')
```

**Never** use `LIKE '%keyword%'` — it is slower than `str_match_ignore_case` and
not idiomatic in DataFusion SQL for O2.

### 4.6 default_filter Usage

`default_filter` is stored in the session context after `connect_o2`. It
contains a pre-built WHERE fragment that isolates exactly the app+namespace
from the global stream. **Always incorporate it** — without it, your query
scans the entire stream across all namespaces and apps.

If `default_filter = "kubernetes_namespace_name='my-ns' AND kubernetes_labels_app='my-app'"`:

```sql
-- CORRECT — filter applied:
SELECT level, message, _timestamp
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND status_code >= 500
LIMIT 100

-- WRONG — no namespace/app filter:
SELECT level, message FROM "k8s_json" WHERE status_code >= 500 LIMIT 100
```

Retrieve `default_filter` from `get_context()` if you need to inspect it
mid-session.

### 4.7 Partition Keys

Partition keys are stored separately from regular schema fields. When a user
asks a question where a partition key is relevant, **always include it in the
WHERE clause** — it prunes the physical scan dramatically.

Common partition keys in k8s streams: `kubernetes_namespace_name`,
`kubernetes_labels_app`, `_timestamp` (managed by O2 automatically).

```sql
-- Good — partition key in WHERE clause prunes scan:
SELECT count(_timestamp) AS total
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'   -- partition key
  AND kubernetes_labels_app     = 'my-app'  -- partition key
  AND level = 'ERROR'

-- Bad — no partition filtering, full stream scan:
SELECT count(_timestamp) FROM "k8s_json" WHERE level = 'ERROR'
```

### 4.8 Array Fields

Array fields in O2 are stored as stringified JSON arrays. Use `cast_to_arr`
before `unnest`:

```sql
-- Correct:
SELECT unnest(cast_to_arr(tags)) AS tag, count(_timestamp) AS cnt
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
GROUP BY tag
ORDER BY cnt DESC

-- Wrong — unnest on a raw string field:
SELECT unnest(tags) FROM "k8s_json"
```

### 4.9 CTE (WITH clause) Rules

Every column referenced in the outer query **must be explicitly projected**
inside the CTE. This is the most common CTE mistake.

```sql
-- CORRECT — _timestamp projected in CTE so outer can count it:
WITH error_events AS (
    SELECT _timestamp, pod_name, message
    FROM "k8s_json"
    WHERE kubernetes_namespace_name = 'my-ns'
      AND status_code >= 500
)
SELECT pod_name, count(_timestamp) AS errors
FROM error_events
GROUP BY pod_name
ORDER BY errors DESC

-- WRONG — _timestamp not in CTE, outer count fails:
WITH error_events AS (
    SELECT pod_name, message FROM "k8s_json" WHERE status_code >= 500
)
SELECT pod_name, count(_timestamp) AS errors   -- ERROR: _timestamp not in CTE
FROM error_events
GROUP BY pod_name
```

### 4.10 _raw Field Extraction

Fields NOT in `defined_schema_fields` live inside `_raw` as a JSON string.
Extract them with OpenObserve's `spath` function:

```sql
-- Extract a single field from _raw:
SELECT spath(_raw, 'trace_id')   AS trace_id,
       spath(_raw, 'request_id') AS request_id,
       count(_timestamp)         AS cnt
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND str_match_ignore_case(_raw, 'trace_id')
GROUP BY trace_id, request_id
LIMIT 50

-- Filter on a _raw sub-field:
WHERE str_match_ignore_case(_raw, '"error_code":"TIMEOUT"')
```

Do NOT use `_raw` fields in GROUP BY — they are unindexed and slow for
aggregation. Project to a named alias first using a CTE.

### 4.11 DataFusion-Specific Functions Reference

| Need | Function | Example |
|---|---|---|
| Case-insensitive substring match | `str_match_ignore_case(field, 'kw')` | `str_match_ignore_case(message, 'timeout')` |
| FTS indexed search | `match_all('keyword')` | `match_all('OutOfMemoryError')` |
| Time buckets | `histogram(_timestamp, 'interval')` | `histogram(_timestamp, 'minute')` |
| Approximate percentile | `approx_percentile_cont(col, p)` | `approx_percentile_cont(latency_ms, 0.99)` |
| Count (non-null rows) | `count(_timestamp)` | `count(_timestamp) AS total` |
| Cast array strings | `cast_to_arr(field)` | `unnest(cast_to_arr(tags))` |
| JSON field extraction | `spath(col, 'key')` | `spath(_raw, 'user_id')`, `spath(_raw, 'nested.key')` |
| Conditional aggregation | `sum(CASE WHEN ... THEN 1 ELSE 0 END)` | See error rate example above |
| NULL-safe division | `NULLIF(denominator, 0)` | `cnt / NULLIF(total, 0)` |
| Window function | `row_number() OVER (PARTITION BY ...)` | See §4.10 |
| Fuzzy search | `fuzzy_match(field, 'term')` | `fuzzy_match(message, 'conection')` |
| Previous row comparison | `lag(col, 1) OVER (ORDER BY _timestamp)` | See §4.10 |
| Date bin (custom intervals) | `date_bin('5 minutes', _timestamp, 0)` | See §4.11 |
| Exact percentile (O2) | `percentile_cont(col, 0.99)` | `percentile_cont(latency_ms, 0.99)` |

---

### 4.10 Window Functions

Window functions run over a set of rows related to the current row without
collapsing them into a group. **All window functions require an `OVER` clause.**

> Full reference: `search_docs("window", doc="datafusion")` or `o2://datafusion-sql`

```sql
-- Rank errors per pod by count
SELECT pod_name,
       count(_timestamp) AS error_count,
       rank() OVER (ORDER BY count(_timestamp) DESC) AS rank
FROM "k8s_json"
WHERE str_match_ignore_case(message, 'error')
GROUP BY pod_name
LIMIT 20

-- Compare current value to previous row (lag/lead)
SELECT _timestamp,
       error_count,
       lag(error_count, 1) OVER (ORDER BY _timestamp) AS prev_error_count,
       error_count - lag(error_count, 1) OVER (ORDER BY _timestamp) AS delta
FROM (
    SELECT histogram(_timestamp, 'minute') AS _timestamp,
           count(_timestamp) AS error_count
    FROM "k8s_json"
    WHERE str_match_ignore_case(level, 'error')
    GROUP BY 1
) ORDER BY _timestamp

-- Running total
SELECT _timestamp,
       count(_timestamp) AS cnt,
       sum(count(_timestamp)) OVER (ORDER BY _timestamp ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total
FROM "k8s_json"
GROUP BY histogram(_timestamp, 'minute') AS _timestamp
ORDER BY _timestamp
```

**Available window functions:**

| Function | Purpose |
|---------|---------|
| `row_number()` | Sequential row number within partition |
| `rank()` | Rank with gaps on ties |
| `dense_rank()` | Rank without gaps on ties |
| `lag(col, n)` | Value from N rows before current |
| `lead(col, n)` | Value from N rows after current |
| `first_value(col)` | First value in window frame |
| `last_value(col)` | Last value in window frame |
| `nth_value(col, n)` | Nth value in window frame |
| `percent_rank()` | Relative rank 0.0–1.0 |
| `cume_dist()` | Cumulative distribution |
| `ntile(n)` | Divide rows into N buckets |

---

### 4.11 date_bin vs date_trunc

Both bucket timestamps — but `date_bin` is more flexible:

```sql
-- date_trunc: round down to nearest unit (standard)
SELECT date_trunc('minute', to_timestamp(_timestamp / 1000000)) AS bucket,
       count(_timestamp) AS cnt
FROM "k8s_json"
GROUP BY 1 ORDER BY 1

-- date_bin: custom interval (DataFusion-specific)
-- Bins into 5-minute windows aligned to Unix epoch
SELECT date_bin(INTERVAL '5 minutes', to_timestamp(_timestamp / 1000000),
                TIMESTAMP '1970-01-01') AS bucket,
       count(_timestamp) AS cnt
FROM "k8s_json"
GROUP BY 1 ORDER BY 1

-- histogram: OpenObserve preferred — handles _timestamp natively
SELECT histogram(_timestamp, '5 minutes') AS bucket,
       count(_timestamp) AS cnt
FROM "k8s_json"
GROUP BY 1 ORDER BY 1
```

**Rule:** Prefer `histogram(_timestamp, 'interval')` for time-series in O2 — it handles the microsecond conversion internally. Use `date_bin` / `date_trunc` only when `histogram` doesn't fit (e.g. on non-timestamp fields).

---

### 4.12 Fuzzy Match and Full-Text Search Hierarchy

O2 provides three levels of text search — choose by field type and tolerance needed:

| Function | Use When | Cost |
|---------|---------|------|
| `match_all('term')` | Field is in `full_text_search_keys` (inverted index) | O(log N) — fastest |
| `str_match_ignore_case(field, 'term')` | Field NOT in FTS keys, exact substring | O(N) — full scan |
| `fuzzy_match(field, 'term')` | Typo-tolerant search (e.g. 'conection' → 'connection') | O(N) — full scan |
| `re_match(field, 'pattern')` | Regex match (Rust syntax) | O(N) — full scan |
| `re_not_match(field, 'pattern')` | Negative regex match | O(N) — full scan |

```sql
-- Fastest: FTS field
WHERE match_all('OutOfMemoryError')

-- Substring on non-FTS field
WHERE str_match_ignore_case(service_name, 'payment')

-- Typo-tolerant (user misspelled the error)
WHERE fuzzy_match(message, 'conection refused')

-- Regex (Rust syntax — use named groups)
WHERE re_match(message, '(?i)error.*timeout')

-- Negative regex
WHERE re_not_match(level, '^(info|debug)$')
```

---

### 4.13 OpenObserve Percentile Functions

O2 has **two** percentile functions — they behave differently:

| Function | Use When | Notes |
|---------|---------|-------|
| `approx_percentile_cont(col, p)` | Standard percentile from raw rows | DataFusion built-in, fast |
| `percentile_cont(col, p)` | Exact percentile from raw rows | O2 UDA — replaces DataFusion's version |
| `summary_percentile(count, min, max, sum, p)` | Pre-aggregated data | O2 only — use with histogram roll-ups |

```sql
-- Standard usage (approx is fine for most cases)
SELECT approx_percentile_cont(response_time_ms, 0.99) AS p99,
       approx_percentile_cont(response_time_ms, 0.95) AS p95,
       approx_percentile_cont(response_time_ms, 0.50) AS p50
FROM "k8s_json"
WHERE str_match_ignore_case(endpoint, '/api/checkout')

-- Exact percentile (O2 UDA)
SELECT percentile_cont(response_time_ms, 0.99) AS p99_exact
FROM "k8s_json"

-- From pre-aggregated rollup data
SELECT summary_percentile(count_col, min_col, max_col, sum_col, 0.99) AS p99
FROM "rollup_stream"
```

---

### 4.14 cast_to_timestamp and time_range

O2's `_timestamp` is in **microseconds** (BIGINT). Standard DataFusion datetime
functions expect timestamps — bridge with these:

```sql
-- cast_to_timestamp: convert microsecond BIGINT to DataFusion TIMESTAMP
SELECT cast_to_timestamp(_timestamp) AS ts,
       date_trunc('hour', cast_to_timestamp(_timestamp)) AS hour_bucket
FROM "k8s_json"

-- time_range: O2 helper — filter by time window without _timestamp in WHERE
-- time_range(field, start_microseconds, end_microseconds)
-- Note: prefer passing start_time/end_time as execute_sql params instead
SELECT level, count(_timestamp)
FROM "k8s_json"
WHERE time_range(_timestamp, 1704067200000000, 1704153600000000)
GROUP BY level

-- to_timestamp_micros: DataFusion → convert to micros for comparison
SELECT to_timestamp_micros('2024-01-01T00:00:00Z') AS us
```

> **Rule:** Do NOT put `_timestamp > N` in WHERE — always use `start_time`/`end_time`
> params in `execute_sql`. Use `cast_to_timestamp` only when you need date arithmetic.

---

### 4.15 Array Functions

O2 stores array fields as stringified JSON arrays (`'["a","b","c"]'`). Always
cast before using DataFusion array functions:

```sql
-- Unnest array field
SELECT unnest(cast_to_arr(tags)) AS tag, count(_timestamp) AS cnt
FROM "k8s_json"
GROUP BY tag ORDER BY cnt DESC LIMIT 20

-- Count elements in array
SELECT arrcount(tags) AS tag_count, count(_timestamp) AS events
FROM "k8s_json"
GROUP BY tag_count

-- Join array elements into string
SELECT arrjoin(tags, ', ') AS tag_list
FROM "k8s_json"
WHERE arrcount(tags) > 0
LIMIT 50

-- Sort and get first element
SELECT arrindex(arrsort(scores), 0, 1) AS min_score
FROM "k8s_json"

-- DataFusion native array functions (after cast_to_arr)
WITH arr_data AS (
    SELECT cast_to_arr(tags) AS tags_arr, _timestamp
    FROM "k8s_json"
)
SELECT array_length(tags_arr) AS len,
       array_contains(tags_arr, 'production') AS is_prod
FROM arr_data
```

**O2 Array functions:**

| Function | Purpose |
|---------|---------|
| `cast_to_arr(field)` | String JSON array → native DataFusion array |
| `to_array_string(arr)` | Native array → string JSON array (reverse) |
| `arrcount(field)` | Count elements in string JSON array |
| `arrindex(field, start, end)` | Slice elements from string JSON array |
| `arrjoin(field, delim)` | Join string JSON array with delimiter |
| `arrsort(field)` | Sort string JSON array |
| `arr_descending(field)` | Sort string JSON array descending |
| `arrzip(arr1, arr2, delim)` | Zip two arrays with delimiter |

---

## 5. Auth Refresh Pattern

Token expiry is the most common operational interruption. Any tool may return:

```json
{"auth_expired": true, "error": "401 Unauthorized"}
```

**Exact recovery sequence:**

```python
# 1. Pull cluster_lb from session context (stored by connect_o2)
ctx = get_context()
cluster_lb = ctx["cluster_lb"]   # e.g. "intl.logs.prod.walmart.com"

# 2. Get a fresh token via super-agent
auth = pingfed_playwright_token(cluster_lb=cluster_lb)

# 3. Re-establish the session (all other context fields unchanged)
connect_o2(
    endpoint       = ctx["endpoint"],
    stream         = ctx["stream"],
    organization   = ctx["org"],
    bearer_token   = auth["token"],
    default_filter = ctx.get("default_filter", ""),
    cluster_lb     = cluster_lb,
    namespace      = ctx.get("namespace", ""),
    app            = ctx.get("app", ""),
)

# 4. Retry the exact same tool call that failed
execute_sql(sql_query=..., time_range=...)
```

**Do not** ask the user to re-authenticate. Handle it silently and retry.
Tell the user "re-authenticated and retried" in your response if you did so.

---

## 6. Log Analysis Interpretation Guide

Raw query results require interpretation. Apply these patterns.

### 6.1 Error Analysis

When `execute_sql` returns rows grouped by `status_code` or `level`:

1. **Identify the dominant error class.** 5XX errors indicate server-side
   failures; 4XX indicate client-side misuse or auth issues.
2. **Calculate error rate** = errors / total × 100. Below 1% is generally
   healthy; 1–5% is degraded; above 5% is an incident.
3. **Check for a spike pattern** by running a histogram query. A sudden
   onset (visible in the histogram) suggests a deployment, config change,
   or traffic event rather than a chronic bug.
4. **Correlate with health_mcp.** If 5XX rate is elevated, check Istio
   server success rate in health_mcp to confirm from the mesh side.

### 6.2 Latency Analysis

1. **P99 is the signal.** P50 hides the tail. Use
   `approx_percentile_cont(response_time_ms, 0.99)` first.
2. **Compare P99 over time** with a histogram query. Gradual increase
   → memory leak or connection pool exhaustion. Sudden spike → deployment or
   downstream dependency failure.
3. **Per-pod breakdown** — if one pod has dramatically higher P99, it may
   need a restart. Filter by `kubernetes_pod_name`.

### 6.3 Traffic Analysis

1. **Requests per minute** — use `histogram(_timestamp, 'minute')` to
   visualise request rate. Compare the incident window against a
   pre-incident baseline.
2. **Traffic drop** (low count) is as important as a spike. A sudden drop
   to near-zero means the app stopped receiving traffic — check health_mcp
   for replica readiness.
3. **Unusual traffic sources** — group by `client_ip` or
   `kubernetes_pod_name` of callers to identify rogue callers or
   misconfigured routing.

### 6.4 Startup / Restart Analysis

After a deployment or pod restart, logs often show a warm-up period with
elevated errors or latency. Check pod age from health_mcp alongside the
error histogram to distinguish "post-restart noise" from a genuine
regression.

### 6.5 Root-Cause Correlation Checklist

| Observation | Check next |
|---|---|
| 5XX spike starts at a specific minute | Run `search_around(timestamp)` at the first error microsecond |
| Errors only on one pod | Query with `GROUP BY kubernetes_pod_name` to confirm |
| Errors started after a deployment | Check `wcnp_analyze(checks=["rollout"])` in health_mcp |
| P99 latency spiked but error rate stable | Check downstream dependencies with health_mcp cross-service RCA |
| Error messages mention connection refused | Check replica readiness in health_mcp |
| Errors mention OOM or SIGKILL | Check memory health + container restarts in health_mcp |
| Errors are 4XX only | Likely a client contract issue; check if a field was renamed in a deploy |

---

## 7. Timestamp Rules

All timestamps in OpenObserve are in **MICROSECONDS** (seconds × 1,000,000).

### 7.0 Timezone is Mandatory — Read it from Your System Context

Your system instruction contains a **Current User Time Context** block
injected by the super-agent from the `x-user-timezone` browser header:

```
## Current User Time Context
User timezone : America/Chicago
Current UTC   : 2026-04-07T19:32:00Z
Epoch ms      : 1744054320000
```

**ALWAYS pass `timezone_name` to every `get_time()` call using the IANA
value from this block.** When the user says "3 PM" or "yesterday afternoon",
they mean their local time — not UTC.

```python
# WRONG — produces UTC timestamps; wrong for non-UTC users:
get_time(time_range="3h")

# CORRECT — uses the user's actual timezone from system context:
get_time(timezone_name="America/Chicago", time_range="3h")
```

If `get_time()` returns `"timezone_warning"` in its response, `timezone_name`
was missing or unrecognised. Re-call immediately with the correct value from
your system context before proceeding with any SQL.

| Operation | Correct approach |
|---|---|
| Get current time | `get_time(timezone_name=<from_context>)` → `now_us` |
| Relative window (1 hour back) | `get_time(timezone_name=<from_context>, time_range="1h")` → `start_us`, `end_us` |
| Specific date + time window | `get_time(timezone_name=<from_context>, date="2026-04-07", start_time_str="14:00", end_time_str="15:30")` |
| Convert a `_timestamp` value to local ISO | `get_time(timezone_name=<from_context>, convert_timestamp=<us>)` |
| search_around target | Pass `_timestamp` value from a log row directly (already in microseconds) |

**Never hardcode timestamps in SQL.** Always use `get_time` to generate them
so they remain correct across sessions and time zones.

**Example — incident window query:**

```python
# User says: "what happened between 2PM and 3PM on April 7?"
# System context says → User timezone: America/Chicago

times = get_time(
    timezone_name  = "America/Chicago",   # ← read from system context, NOT hardcoded
    date           = "2026-04-07",
    start_time_str = "14:00",
    end_time_str   = "15:00",
)

execute_sql(
    sql_query  = """
        SELECT level, message, kubernetes_pod_name, status_code
        FROM "k8s_json"
        WHERE kubernetes_namespace_name = 'my-ns'
          AND kubernetes_labels_app     = 'my-app'
        ORDER BY _timestamp DESC
        LIMIT 200
    """,
    start_time = times["date_range"]["start_us"],
    end_time   = times["date_range"]["end_us"],
)
```

---

## 8. Schema-First Approach

**Always call `get_stream_schema` before writing the first query of a
session.** Without schema knowledge you risk:

- Querying fields that do not exist (runtime error).
- Using `str_match_ignore_case` on an FTS-indexed field (slower than needed).
- Missing a partition key that would make the query 10× faster.
- Attempting to GROUP BY a `_raw` sub-field directly (not supported).

### 8.1 Schema Response Anatomy

```json
{
  "name": "k8s_json",
  "fields": {
    "Utf8": ["level", "message", "kubernetes_pod_name", "kubernetes_namespace_name",
             "kubernetes_labels_app", "request_path", "client_ip"],
    "Int64": ["status_code", "response_time_ms"],
    "Float64": ["bytes_sent"]
  },
  "settings": {
    "partition_keys": ["kubernetes_namespace_name", "kubernetes_labels_app"],
    "full_text_search_keys": ["message", "log"]
  },
  "total_fields": 142,
  "returned_fields": 9,
  "hint": "133 additional fields available. Call with fields='...' to include specific fields."
}
```

### 8.2 What to extract from schema

- **`fields` by type** — determines which aggregation functions apply. Use
  `approx_percentile_cont` on `Int64`/`Float64` fields only.
- **`full_text_search_keys`** — use `match_all('kw')` for these, not
  `str_match_ignore_case`.
- **`partition_keys`** — include at least one in every WHERE clause. Missing
  partition keys cause full-stream scans.
- **`total_fields` vs `returned_fields`** — when pruned, call
  `get_stream_schema(fields="field_a,field_b")` to reveal specific fields
  not returned in the default view.

### 8.3 Schema-to-Query Workflow Example

User asks: "How many 5XX errors did my app produce in the last hour, and
which paths are affected?"

```
Step A: get_stream_schema(user_prompt="5XX errors by path last hour")
         → confirms: status_code (Int64), request_path (Utf8) are in schema
         → confirms: kubernetes_namespace_name is a partition_key
         → confirms: message is in full_text_search_keys

Step B: Build SQL using confirmed fields:
```

```sql
SELECT request_path,
       status_code,
       count(_timestamp)                                AS hits,
       approx_percentile_cont(response_time_ms, 0.99)  AS p99_ms
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND status_code >= 500
GROUP BY request_path, status_code
ORDER BY hits DESC
LIMIT 50
```

```
Step C: validate_sql_policy(sql) → ok: true
Step D: execute_sql(sql_query=..., time_range="1h")
```

---

## 9. Result Presentation

When `execute_sql` returns results, present them clearly and offer actionable
next steps.

### 9.1 Standard Result Anatomy

```json
{
  "success": true,
  "hits": [
    {"status_code": 503, "request_path": "/api/order", "hits": 1420, "p99_ms": 8300},
    {"status_code": 500, "request_path": "/api/item",  "hits":  214, "p99_ms": 1200}
  ],
  "total": 2,
  "took_ms": 340
}
```

- `hits` = the result rows (up to `limit`, default 1000).
- `total` = total matching rows scanned (may exceed `hits` length if truncated).
- `took_ms` = server-side query execution time.

### 9.2 Presenting Error Results

Always show:

1. **Total error count + error rate** (if total traffic known).
2. **Top N error types** grouped by status code or error message.
3. **P99 latency** alongside errors if the schema has a latency field.
4. **Time of first error** — prompt user to run `search_around` if they want
   context around the first occurrence.

Example response:

> In the last hour, your app produced **1,634 5XX errors** across 2 paths:
>
> | Path | Status | Count | P99 |
> |---|---|---|---|
> | /api/order | 503 | 1,420 | 8.3 s |
> | /api/item | 500 | 214 | 1.2 s |
>
> The /api/order path has a P99 of 8.3 seconds with 503s — this suggests
> a downstream dependency is timing out. Suggested follow-ups:
> - Run the histogram query below to see when errors started.
> - Use `search_around` on the first error's `_timestamp` for context logs.
> - Check health_mcp `wcnp_analyze` for downstream latency spikes.

### 9.3 No Results

When `hits` is empty:

1. Suggest a broader time range: `time_range="3h"` or `"24h"`.
2. Confirm the stream name is correct with `list_streams()`.
3. Check whether the `default_filter` fields match what is actually in the
   stream (e.g. app label may differ from deployment name).
4. Try `get_field_values(fields=["kubernetes_labels_app"], time_range="24h")`
   to confirm the app label value.

### 9.4 Suggested Follow-Up Query Templates

After every result, offer at least one follow-up. Copy-paste ready queries
reduce friction for the user.

**After a 5XX count result:**

```sql
-- See when errors started (histogram over time):
SELECT histogram(_timestamp, 'minute') AS ts,
       count(_timestamp)               AS errors
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND status_code >= 500
GROUP BY ts
ORDER BY ts
```

**After identifying a spike timestamp:**

```python
# Get context around the first error:
search_around(timestamp=<first_error_timestamp_us>, size=20)
```

**After seeing one pod dominate the error count:**

```sql
-- Compare error distribution across all pods:
SELECT kubernetes_pod_name,
       count(_timestamp)  AS errors
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
  AND status_code >= 500
GROUP BY kubernetes_pod_name
ORDER BY errors DESC
```

**After seeing high P99 latency:**

```sql
-- Latency percentile trend over the last 3 hours:
SELECT histogram(_timestamp, 'minute')               AS ts,
       approx_percentile_cont(response_time_ms, 0.99) AS p99_ms,
       approx_percentile_cont(response_time_ms, 0.50) AS p50_ms,
       count(_timestamp)                               AS requests
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'my-ns'
  AND kubernetes_labels_app     = 'my-app'
GROUP BY ts
ORDER BY ts
```

### 9.5 Presenting Time Series Results

When the result is a histogram:

- Identify the **onset point** — when did the error/latency rate first
  deviate from baseline?
- Identify **peak** and **duration** of the event.
- Note if the series is still elevated at the most recent bucket (ongoing).
- Offer `search_around` at the onset microsecond for log context.

---

## 10. VRL Scripting Guide

VRL (Vector Remap Language) is used in OpenObserve for log enrichment, field
extraction, and transformation pipelines. Use `get_o2_rules(intent="vrl")` to
load the full VRL rule set before writing any VRL.

### 10.1 VRL Key Rules

- Use Rust regex syntax (not PCRE or Python).
- Always use named capture groups: `(?P<name>pattern)`.
- Define regex patterns in a variable before `parse_regex`.
- Do NOT overwrite `_timestamp`.
- Use `!` (bang) for fallible functions that return a single value:
  `.status_code = to_int!(.parsed.status)`.
- Use the error-tuple pattern for `parse_regex`:
  `.parsed, err = parse_regex(.message, pattern)`.
- Extract parsed fields to a new sub-object:
  `.parsed_log = parse_regex!(.message, pattern)`.

### 10.2 VRL Example — Extract structured fields from a log line

```vrl
# Parse "2026-04-07T14:32:11Z ERROR [order-service] 503 /api/order 8412ms"
let pattern = r'(?P<ts>[^\s]+)\s+(?P<level>[A-Z]+)\s+\[(?P<svc>[^\]]+)\]\s+(?P<status>\d+)\s+(?P<path>[^\s]+)\s+(?P<latency_ms>\d+)ms'

.parsed, err = parse_regex(.message, pattern)

if err == null {
    .log_level    = .parsed.level
    .service_name = .parsed.svc
    .status_code  = to_int!(.parsed.status)
    .request_path = .parsed.path
    .latency_ms   = to_int!(.parsed.latency_ms)
}
```

Validate with: `validate_vrl(vrl=<script>, events=['{"message": "..."}'])`

---

## 11. Common Mistakes Quick Reference

| Mistake | Symptom | Fix |
|---|---|---|
| `_timestamp` in WHERE | O2 returns error or ignores time param | Remove from WHERE; use `time_range` param |
| `SELECT *` | Slow query, large response payload | Name all needed fields explicitly |
| No `default_filter` | Results from all namespaces | Add `WHERE kubernetes_namespace_name='ns' AND kubernetes_labels_app='app'` |
| Unquoted stream name | SQL parse error | `FROM "k8s_json"` with double quotes |
| `count(*)` | DataFusion type error in some O2 versions | Use `count(_timestamp)` |
| Using `LIKE '%kw%'` | Slow full scan | Use `str_match_ignore_case(field, 'kw')` |
| `match_all` on non-FTS field | Incorrect results or error | Use `str_match_ignore_case` instead |
| Subquery in SELECT | O2 API error | Move to CTE or FROM subquery |
| Aggregating `_raw` directly | Slow / unsupported | Extract to alias in CTE first |
| Hardcoded microsecond timestamp | Query breaks in different timezones | Use `get_time(timezone_name=<from_context>)` every time |
| `get_time()` called without `timezone_name` | Result shows `"timezone_warning"` — timestamps are in UTC not user's local time | Read `User timezone` from your system context block and pass it as `timezone_name` |
| CTE missing columns used in outer SELECT | DataFusion column not found error | Include all referenced columns in CTE SELECT |
| `unnest` on raw string field | Type error | `unnest(cast_to_arr(field))` |
| Auth expired mid-session | `{"auth_expired": true}` | Call `pingfed_playwright_token` → `connect_o2` → retry |
| Wrong stream name | Empty results | Call `list_streams()` to enumerate available streams |

---

## 12. Tool Reference Summary

| Tool | When to call | Key parameters |
|---|---|---|
| `connect_o2` | Start of every session | `endpoint`, `stream`, `bearer_token`, `organization`, `default_filter`, `cluster_lb` |
| `get_context` | Verify session / get cluster_lb for token refresh | — |
| `clear_context` | End of session or switching to a different app | — |
| `set_context` | Manual context setup (not the preferred path; use `connect_o2`) | `endpoint`, `stream`, `org` |
| `configure_auth` | Add auth to an existing `set_context` session | `auth_token` |
| `get_stream_schema` | BEFORE the first query of a session | `user_prompt`, `full_schema`, `fields` |
| `list_streams` | Discover available streams in the org | `stream_type` |
| `execute_sql` | Run any SELECT query | `sql_query`, `time_range`, `start_time`, `end_time`, `limit` |
| `search_around` | Get ±5 min of logs around a known event | `timestamp` (microseconds), `size` |
| `get_field_values` | Enumerate unique values in a field | `fields`, `time_range`, `size`, `keyword` |
| `validate_sql_policy` | Local policy check (instant, no network) | `sql` |
| `validate_sql` | Live cluster SQL validation | `sql` |
| `validate_vrl` | Validate a VRL script against sample events | `vrl`, `events` |
| `get_o2_rules` | Load SQL/VRL rules for prompt injection | `intent` (`sql`, `vrl`, `log_analysis`, etc.) |
| `get_time` | Generate microsecond timestamps for queries | `timezone_name`, `time_range`, `date`, `start_time_str`, `end_time_str`, `convert_timestamp` |

---

## 13. End-to-End Example Walkthrough

User says: **"Show me the 5XX errors for the order service in the last 3 hours
and tell me which pods are responsible."**

### Step 1 — Resolve config

```python
config = wcnp_get_o2_config(namespace="order-ns", app="order-service")
# Returns: endpoint, stream="k8s_json", organization, cluster_lb, default_filter
```

### Step 2 — Get token

```python
auth = pingfed_playwright_token(cluster_lb=config["cluster_lb"])
```

### Step 3 — Connect

```python
connect_o2(
    endpoint       = config["endpoint"],
    stream         = "k8s_json",
    organization   = config["organization"],
    bearer_token   = auth["token"],
    default_filter = config["default_filter"],
    cluster_lb     = config["cluster_lb"],
    namespace      = "order-ns",
    app            = "order-service",
)
```

### Step 4 — Schema

```python
get_stream_schema(user_prompt="5XX errors by pod last 3 hours")
# Confirms: status_code (Int64), kubernetes_pod_name (Utf8) in defined_schema_fields
# Confirms: partition_keys = ["kubernetes_namespace_name", "kubernetes_labels_app"]
```

### Step 5 — Build SQL

```sql
SELECT kubernetes_pod_name,
       status_code,
       count(_timestamp)                                AS hits,
       approx_percentile_cont(response_time_ms, 0.99)  AS p99_ms
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'order-ns'
  AND kubernetes_labels_app     = 'order-service'
  AND status_code >= 500
GROUP BY kubernetes_pod_name, status_code
ORDER BY hits DESC
LIMIT 100
```

### Step 6 — Policy check

```python
validate_sql_policy(sql=<above>)
# Returns: {"ok": true, "violations": []}
```

### Step 7 — Execute

```python
execute_sql(sql_query=<above>, time_range="3h")
```

### Step 8 — Sample result

```json
{
  "hits": [
    {"kubernetes_pod_name": "order-service-abc12", "status_code": 503, "hits": 2140, "p99_ms": 9200},
    {"kubernetes_pod_name": "order-service-def34", "status_code": 503, "hits":  310, "p99_ms": 8800},
    {"kubernetes_pod_name": "order-service-ghi56", "status_code": 500, "hits":   42, "p99_ms": 1400}
  ],
  "total": 3,
  "took_ms": 480
}
```

### Step 9 — Interpret and present

> **5XX errors — order-service — last 3 hours**
>
> | Pod | Status | Count | P99 |
> |---|---|---|---|
> | order-service-abc12 | 503 | 2,140 | 9.2 s |
> | order-service-def34 | 503 | 310 | 8.8 s |
> | order-service-ghi56 | 500 | 42 | 1.4 s |
>
> Two pods are producing the bulk of 503s with P99 around 9 seconds —
> characteristic of a downstream timeout. The third pod has 500s with
> lower latency, which may be a different error class.
>
> **Suggested next steps:**
> 1. Run the histogram query to see when the 503s started.
> 2. Use `search_around` on the first 503 timestamp for surrounding log context.
> 3. Check `wcnp_analyze` in health_mcp for downstream latency spikes that
>    correlate with the 503 onset.

### Step 10 — Offer follow-up histogram

```sql
SELECT histogram(_timestamp, 'minute') AS ts,
       count(_timestamp)               AS errors_503
FROM "k8s_json"
WHERE kubernetes_namespace_name = 'order-ns'
  AND kubernetes_labels_app     = 'order-service'
  AND status_code = 503
GROUP BY ts
ORDER BY ts
```

---

## 14. Rules Engine Integration

`get_o2_rules(intent)` returns a formatted string of rules for the given
intent. Available intents:

| Intent | What it returns |
|---|---|
| `sql` | All SQL generation rules (see Section 4) |
| `vrl` | VRL scripting rules (see Section 10) |
| `query_optimization` | Partition key and index usage tips |
| `log_analysis` | Log analysis and follow-up suggestion principles |
| `vrl_optimization` | VRL performance rules |
| `general` | Global rules (field verification, conciseness) |

Call `get_o2_rules(intent="sql")` when you want to inject the current rule set
into a prompt for a second-pass query generation step. The `formatted` field
is ready for prompt injection.

---

## 15. Multi-App and Multi-Stream Sessions

When the user asks about multiple apps in the same conversation:

1. Each app may live in a different O2 cluster (different `endpoint` and
   `cluster_lb`). Call `wcnp_get_o2_config` per app.
2. `connect_o2` replaces the current session context — there is only one
   active context at a time. Finish all queries for app A before switching
   to app B.
3. If both apps share the same cluster endpoint, switch is cheaper — only
   the `default_filter` and `stream` may differ.
4. Use `get_context()` to confirm which app/namespace the current session
   belongs to before executing a query.

---

## 16. SQL Self-Correction Retry Loop

When `execute_sql` fails, **do not give up**. Follow this protocol to
self-correct and retry. The loop is configurable via `O2_MAX_RETRIES`
(default: 5).

Read `o2://retry-guide` at session start for the complete protocol.

### 16.1 Loop Overview

```
attempt = 1
sql = <initial generated SQL>

while attempt <= max_retries:
    result = execute_sql(sql=sql, attempt=attempt)
    if result["success"]: break   ✅

    hint = get_sql_correction_hint(sql=sql, error_message=result["error"])
    if not hint["retry_allowed"]: break   ← auth error, refresh first

    # Run suggested diagnostic tools, then fix SQL using correction_hint
    sql = <corrected SQL>
    attempt += 1
```

### 16.2 Error Types and What To Do

| error_type | Root Cause | Fix |
|-----------|-----------|-----|
| `unknown_column` | Column doesn't exist in schema | `get_stream_schema` → use valid field |
| `unknown_function` | Function not in DataFusion/O2 | `validate_sql_functions` → `check_sql_function` |
| `syntax_error` | Bad SQL syntax | Fix DataFusion syntax → `validate_sql` |
| `policy_violation` | ADL rule broken | `validate_sql_policy` → fix violation |
| `stream_not_found` | Wrong stream name | `list_streams` → use exact name |
| `auth_error` | 401/403 expired token | `pingfed_playwright_token` → `connect_o2` |
| `timeout` | Query scans too much | Add partition key filter, reduce `time_range` |
| `type_mismatch` | CAST error | Add `CAST(field AS type)` |
| `limit_exceeded` | Too many rows | Lower `LIMIT` or narrow `WHERE` |
| `empty_result` | 0 rows (not a failure) | Broaden `time_range`, check `default_filter` |
| `unknown` | No pattern matched | `validate_sql_policy` + `validate_sql` + `get_stream_schema` |

### 16.3 The execute_sql Response on Failure

When `execute_sql` fails it now returns enriched correction context:

```json
{
  "success": false,
  "error": "column 'levl' does not exist",
  "sql_error_type": "unknown_column",
  "correction_hint": "Call get_stream_schema() to get the actual field list...",
  "retry_allowed": true,
  "retries_remaining": 4,
  "attempt": 1,
  "max_retries": 5,
  "suggested_tools": ["get_stream_schema"],
  "retry_instructions": "Attempt 1/5 failed. Read correction_hint..."
}
```

### 16.4 Critical Retry Rules

1. Always pass `attempt=N` to `execute_sql` — it tracks loop progress
2. **Never** retry after `auth_error` without refreshing token first
3. After fixing `unknown_column` → re-run `validate_sql_policy`
4. After fixing `unknown_function` → re-run `validate_sql_functions`
5. `empty_result` is **not** a failure — broaden search instead of retrying
6. If all retries fail — return last error + all attempted SQLs for user

### 16.5 Example: unknown_function correction

```
Attempt 1 — execute_sql fails:
  error: "function 'extract_json' not found"
  sql_error_type: "unknown_function"
  suggested_tools: ["validate_sql_functions", "check_sql_function"]

→ validate_sql_functions(sql)
  → invalid: [{"name": "extract_json", "suggestions": ["spath"]}]

→ check_sql_function("spath")
  → syntax: "spath(json_field, 'path.to.value')"

→ Fix SQL: replace extract_json(body, 'error') with spath(body, 'error')

Attempt 2 — execute_sql succeeds ✅
```

---

## 17. Key Design Principles

1. **Schema first, always.** Never write a WHERE clause against a field you
   have not confirmed exists in the stream schema.
2. **default_filter is mandatory.** Without it, every query scans the full
   shared stream across all namespaces and apps.
3. **Timestamps are microseconds.** Every off-by-1000 mistake means missing
   data. Use `get_time()` and never hardcode.
4. **Validate before execute.** `validate_sql_policy` is instant and catches
   the most expensive mistakes before they reach the cluster.
5. **Offer follow-ups.** A single count query is rarely enough. Always suggest
   the histogram, the per-pod breakdown, and `search_around` for context.
6. **Auth is ephemeral.** Handle `auth_expired` silently, refresh, and retry.
   Never ask the user to re-authenticate.
7. **Interpret, don't dump.** Raw row counts mean nothing. Convert them to
   error rates, percentiles, and plain-English summaries with clear next
   steps.

---

## 18. Investigating 4XX / 5XX Errors (health_mcp → o2_mcp Handoff)

health_mcp and o2_mcp are **complementary layers** of the same investigation:

| Layer | Tool | Answers |
|---|---|---|
| **Detect** | `health_mcp.wcnp_check_app_health` | *Is* there a problem? How bad? (error rate %, P99) |
| **Locate** | `health_mcp.wcnp_analyze` | Which pod/deployment/downstream is the source? |
| **Explain** | `o2_mcp.execute_sql` | *What* is in the logs? Which paths? Which messages? |
| **Contextualise** | `o2_mcp.search_around` | *Why* did it start? What happened immediately before? |

health_mcp tells you **metrics** (numbers). o2_mcp tells you **logs** (why).
Always use both. A 5XX rate from Prometheus without log context is incomplete.

### 18.1 Full Dual-Path Workflow

```
User: "My cart service has elevated 5XX errors — what's happening?"

Step 1 — DETECT (health_mcp)
─────────────────────────────────────────────────────────────────────────
config  = wcnp_get_o2_config(namespace="my-ns", app="cart-service")
health  = wcnp_check_app_health(namespace="my-ns", app="cart-service")
# health contains: { "error_rate_5xx": 8.4, "p99_latency_ms": 4200,
#                    "cluster_lb": "intl.logs.prod.walmart.com" }

Step 2 — AUTHENTICATE (super-agent)
─────────────────────────────────────────────────────────────────────────
auth = pingfed_playwright_token(cluster_lb=config["cluster_lb"])
# auth["token"] = '{"access_token":"session XXX","refresh_token":"Chl..."}'

Step 3 — EXPLORE SCHEMA (o2_mcp)
─────────────────────────────────────────────────────────────────────────
get_stream_schema(
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    user_prompt  = "5XX errors by path and pod",
)
# Confirms which fields exist: status_code, request_path, kubernetes_pod_name

Step 4 — COUNT BY STATUS CODE + PATH (o2_mcp)
─────────────────────────────────────────────────────────────────────────
execute_sql(
    sql_query = """
        SELECT status_code,
               request_path,
               count(_timestamp)                                AS hits,
               approx_percentile_cont(response_time_ms, 0.99)  AS p99_ms
        FROM   "wcnp_mx_cart_services"
        WHERE  kubernetes_namespace_name = 'my-ns'
          AND  kubernetes_labels_app     = 'cart-service'
          AND  CAST(status_code AS INT) >= 400
        GROUP BY status_code, request_path
        ORDER BY hits DESC
        LIMIT 50
    """,
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    time_range   = "1h",
)

Step 5 — TIME SERIES TO FIND ONSET (o2_mcp)
─────────────────────────────────────────────────────────────────────────
execute_sql(
    sql_query = """
        SELECT histogram(_timestamp, 'minute')                              AS ts,
               count(_timestamp)                                             AS total,
               sum(CASE WHEN CAST(status_code AS INT) >= 500 THEN 1 ELSE 0 END) AS errors_5xx,
               sum(CASE WHEN CAST(status_code AS INT) BETWEEN 400 AND 499
                        THEN 1 ELSE 0 END)                                  AS errors_4xx
        FROM   "wcnp_mx_cart_services"
        WHERE  kubernetes_namespace_name = 'my-ns'
          AND  kubernetes_labels_app     = 'cart-service'
        GROUP BY ts
        ORDER BY ts
    """,
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    time_range   = "3h",
)
# Histogram shows the spike onset — note the _timestamp of the first spike bucket

Step 6 — GET CONTEXT AROUND FIRST ERROR (o2_mcp)
─────────────────────────────────────────────────────────────────────────
# Take _timestamp of the very first error row from Step 4 results
search_around(
    timestamp    = <first_error._timestamp>,
    endpoint     = config["endpoint"],
    bearer_token = auth["token"],
    stream       = config["stream"],
    organization = config["organization"],
    size         = 20,
)
# Returns 10 log lines before + 10 after the first failure
# Look for: upstream timeout, OOMKilled pod, dependency errors, config changes
```

### 18.2 What Each Error Class Means

| Error Class | health_mcp signals | o2_mcp signals | Likely root cause |
|---|---|---|---|
| **503 Service Unavailable** | Istio server success rate < 95% | Log messages: "upstream connect error", "connection refused" | Pod OOMKilled or not ready; upstream dep down |
| **502 Bad Gateway** | Elevated 5XX rate, normal latency | Log: "upstream response error", "502" | Nginx/Envoy proxy issue; backend process crashed |
| **504 Gateway Timeout** | High P99 latency + 5XX | Log: "upstream timed out", "context deadline exceeded" | Downstream service slow; DB query too slow |
| **500 Internal Server Error** | 5XX rate elevated | Log: stack traces, "NullPointerException", "panic" | Application bug; uncaught exception |
| **429 Too Many Requests** | Spike then drop in traffic | Log: "rate limit exceeded", "429" | Client sending too many requests; retry storm |
| **401/403 from app** | 4XX elevated, P99 normal | Log: "unauthorized", "forbidden", "invalid token" | Auth config regression; expired service account |
| **404 from app** | 4XX elevated | Log: "path not found", "no route" | API contract change; client using old endpoint |

### 18.3 4XX vs 5XX Separation

When investigating, always **split 4XX and 5XX** — they have different owners:

```sql
-- Step A: see the breakdown
SELECT CASE
         WHEN CAST(status_code AS INT) BETWEEN 400 AND 499 THEN '4XX'
         WHEN CAST(status_code AS INT) BETWEEN 500 AND 599 THEN '5XX'
         ELSE 'other'
       END                     AS error_class,
       status_code,
       count(_timestamp)       AS hits
FROM   "wcnp_mx_cart_services"
WHERE  kubernetes_namespace_name = 'my-ns'
  AND  kubernetes_labels_app     = 'cart-service'
  AND  CAST(status_code AS INT) >= 400
GROUP BY error_class, status_code
ORDER BY hits DESC
LIMIT 30
```

- **4XX spike** = client-side issue, bad input, auth regression, or endpoint removed
- **5XX spike** = server-side failure, dependency down, resource exhaustion
- **Both rising together** = infrastructure event (network partition, cert expiry)

### 18.4 Correlating health_mcp Timestamp with o2_mcp

health_mcp Prometheus alerts include a `triggered_at` or metric timestamp.
Convert it to microseconds for precise log lookup:

```python
# health_mcp returned: triggered_at = "2026-04-07T14:23:00Z"
times = get_time(
    timezone_name  = "UTC",
    date           = "2026-04-07",
    start_time_str = "14:20",   # 3 min before the alert
    end_time_str   = "14:35",   # 12 min after
)

execute_sql(
    sql_query  = """
        SELECT level, message, kubernetes_pod_name, status_code, request_path
        FROM   "wcnp_mx_cart_services"
        WHERE  kubernetes_namespace_name = 'my-ns'
          AND  kubernetes_labels_app     = 'cart-service'
          AND  CAST(status_code AS INT) >= 500
        ORDER BY _timestamp ASC
        LIMIT 200
    """,
    endpoint   = config["endpoint"],
    bearer_token = auth["token"],
    stream     = config["stream"],
    organization = config["organization"],
    start_time = times["date_range"]["start_us"],
    end_time   = times["date_range"]["end_us"],
)
```

### 18.5 Auth Errors from o2_mcp During 4XX/5XX Investigation

If **o2_mcp itself returns a 401/403** (different from your app's 4XX errors):

```json
{"success": false, "auth_expired": true, "error": "O2 API error (401): ..."}
```

This is an **o2_mcp authentication failure** — your PingFederate session for
OpenObserve expired. It has nothing to do with your application's errors.

**Recovery:**

```python
# 1. Get fresh token (reuse cluster_lb from wcnp_get_o2_config)
auth = pingfed_playwright_token(cluster_lb=config["cluster_lb"])

# 2. Retry the exact same query with the new bearer_token
execute_sql(..., bearer_token=auth["token"])
```

Do NOT invalidate or debug your app's auth config — this is purely the
log-query session expiry.

### 18.6 get_field_values auth_expired Propagation

`get_field_values` runs one SQL query **per field concurrently**. If any
field query returns 401/403, the top-level response will include:

```json
{
  "success": true,
  "auth_expired": true,
  "partial_errors": ["status_code: O2 API 401: Unauthorized"],
  "fields": [...]
}
```

Note: `success` may still be `true` if some fields succeeded. Always check for
`auth_expired` independently of `success` when calling `get_field_values`.

### 18.7 Summary Decision Tree

```
health_mcp reports elevated error rate
    │
    ├─ 4XX only?
    │    ├─ o2_mcp: GROUP BY status_code, request_path
    │    ├─ Look for: 401/403 → auth regression; 404 → endpoint removed
    │    └─ search_around first 4XX for log context
    │
    ├─ 5XX only?
    │    ├─ o2_mcp: GROUP BY status_code, kubernetes_pod_name
    │    ├─ histogram → find onset time
    │    ├─ search_around onset timestamp
    │    └─ health_mcp wcnp_analyze → check downstream deps + pod restarts
    │
    └─ Both 4XX and 5XX rising?
         ├─ Infrastructure event likely (cert expiry, network partition)
         ├─ o2_mcp: histogram of both classes to confirm same onset
         └─ health_mcp: check Istio mesh health, certificate expiry, ingress status
```
