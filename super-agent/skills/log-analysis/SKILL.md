---
name: log-analysis
description: >
  Deep log analysis via OpenObserve with DataFusion SQL. Use when the user asks about
  "show logs", "error distribution", "5XX errors", "exceptions", "api calls distribution",
  "request breakdown", "what errors are happening", or any question requiring log data.
  NOT for health metrics — those use the health-triage skill.
metadata:
  adk_additional_tools:
    - execute_sql
    - search_around
    - get_field_values
    - get_stream_schema
    - list_streams
    - validate_sql
    - validate_sql_policy
    - validate_sql_functions
    - check_sql_function
    - get_sql_correction_hint
    - get_o2_rules
    - search_docs
    - get_time
    - validate_vrl
    - wcnp_get_o2_config
    - pingfed_token
---

# Log Analysis via OpenObserve

## When to Use This Skill

Activate this skill when the user asks about:
- Log queries ("show logs for cart-service")
- Error distribution ("break down 5XX by endpoint")
- Exception analysis ("what exceptions are happening?")
- API call distribution ("show request distribution")
- Stack traces ("show full stack trace for this error")
- Timestamp-based debugging ("what happened at <time>?")

**Key distinction**: "api calls distribution" = log analysis (this skill), NOT health check.

## Required Information

- **namespace** — Kubernetes namespace
- **app** — application name

## Step-by-Step Workflow

### Step 1: Resolve OpenObserve Configuration

```
wcnp_get_o2_config(namespace=<namespace>, app=<app>)
```

This returns: `endpoint`, `stream`, `organization`, `cluster_lb`, `default_filter`

### Step 2: Acquire Authentication Token

```
pingfed_token(cluster_lb=<cluster_lb from step 1>)
```

**CRITICAL**: Pass the ENTIRE JSON string returned as `bearer_token` to every
o2_mcp tool call. Do NOT extract only `access_token`.

| Correct | Wrong |
|---|---|
| `bearer_token='{"access_token":"session XXX","refresh_token":"Chl..."}'` | `bearer_token='session XXX'` |

### Step 3: Discover Schema (if needed)

```
get_stream_schema(endpoint=<endpoint>, bearer_token=<token>,
                  stream=<stream>, organization=<org>)
```

The schema response is smart-pruned based on relevance. Use it to find the exact
field names for your SQL query.

### Step 4: Write and Execute SQL

```
execute_sql(sql_query=<query>, endpoint=<endpoint>, bearer_token=<token>,
            stream=<stream>, organization=<org>, time_range=<range>)
```

**SQL Rules (DataFusion engine)**:
- SELECT only — no INSERT, UPDATE, DELETE
- Use `_timestamp` for time filtering (microsecond epoch)
- String matching: `str_match(field, 'pattern')` or `LIKE`
- Aggregations: `COUNT(*)`, `GROUP BY`, `ORDER BY` work normally
- Time bucketing: `date_bin('5 minutes', _timestamp)` for histograms

### Step 5: Error Self-Correction

If SQL fails, the system auto-retries up to 5 times using:
- `validate_sql_policy` — checks for policy violations
- `validate_sql_functions` — checks function names against 236-function registry
- `get_sql_correction_hint` — provides structured fix hints

### Step 6: Context Search (for debugging specific events)

To see logs around a specific timestamp:

```
search_around(endpoint=<endpoint>, bearer_token=<token>, stream=<stream>,
              organization=<org>, timestamp=<microsecond_epoch>, size=10)
```

## Common Query Patterns

**5XX error distribution by endpoint:**
```sql
SELECT http_path, response_code, COUNT(*) as count
FROM <stream>
WHERE response_code >= 500
GROUP BY http_path, response_code
ORDER BY count DESC
LIMIT 20
```

**Exception class breakdown:**
```sql
SELECT exception_class, COUNT(*) as count
FROM <stream>
WHERE exception_class IS NOT NULL
GROUP BY exception_class
ORDER BY count DESC
```

**Request rate histogram (5-min buckets):**
```sql
SELECT date_bin('5 minutes', _timestamp) as bucket, COUNT(*) as requests
FROM <stream>
GROUP BY bucket
ORDER BY bucket
```

## Token Refresh Rule

If any tool returns `auth_expired: true` or HTTP 401:
1. Call `pingfed_token(cluster_lb=<cluster_lb>)` again
2. Pass the FULL JSON string as `bearer_token`
3. Retry the failed tool call
