# O2 SQL Self-Correction Retry Loop

## Configuration
- max_retries: {max_retries}  (set via O2_MAX_RETRIES env var, range 1-10)
- Configurable per-session without restarting o2_mcp

## Protocol

When execute_sql returns success=false, follow this loop:

```
attempt = 1
sql = <initial SQL generated from user question>

while attempt <= {max_retries}:
    result = execute_sql(sql=sql, attempt=attempt, endpoint=..., bearer_token=..., ...)

    if result["success"]:
        return result  # ✅ Done

    # Step 1: Get structured diagnosis
    hint = get_sql_correction_hint(sql=sql, error_message=result["error"])

    # Step 2: Check if retry is worth attempting
    if not hint["retry_allowed"]:
        # Auth error — refresh token first
        # Call pingfed_playwright_token → then retry with new bearer_token
        break

    # Step 3: Run suggested diagnostic tools (in order)
    for tool_name in hint["suggested_tools"]:
        call tool_name with relevant args

    # Step 4: Use correction_hint to fix the SQL
    sql = <corrected SQL based on correction_hint + diagnostic tool results>

    attempt += 1

# All retries exhausted
return {{
    "success": False,
    "all_attempts_failed": True,
    "attempts": attempt - 1,
    "last_error": result["error"],
    "last_sql": sql,
}}
```

## Error Types and Fix Strategies

| error_type | Fix Strategy |
|-----------|-------------|
| unknown_column | Call get_stream_schema → replace column with valid field |
| unknown_function | Call validate_sql_functions → check_sql_function → replace function |
| syntax_error | Fix DataFusion syntax → call validate_sql to confirm |
| policy_violation | Call validate_sql_policy → fix the specific violation |
| stream_not_found | Call list_streams → use exact stream name with double quotes |
| auth_error | Call pingfed_playwright_token → retry with new bearer_token — DO NOT retry SQL immediately |
| timeout | Add partition key filters, reduce time_range, lower LIMIT |
| type_mismatch | Add explicit CAST(field AS type) |
| limit_exceeded | Lower LIMIT or narrow WHERE clause |
| empty_result | Broaden time_range, check default_filter, call get_field_values |
| unknown | Call validate_sql_policy + validate_sql + get_stream_schema |

## Key Rules

1. ALWAYS pass attempt=N to execute_sql so error responses include retry context
2. NEVER retry after auth_error without refreshing the token first
3. After fixing unknown_column — re-run validate_sql_policy to catch any other violations
4. After fixing unknown_function — re-run validate_sql_functions to confirm all clear
5. On empty_result: this is NOT a failure — broaden search, do not count as retry
6. Track all attempted SQL strings for debugging — include in final response if all fail

## Common Corrections

```sql
-- unknown_column: use spath for _raw fields
-- WRONG: SELECT trace_id FROM "stream"
-- RIGHT: SELECT spath(_raw, 'trace_id') AS trace_id FROM "stream"

-- policy_violation: remove _timestamp from WHERE
-- WRONG: WHERE _timestamp > 1704067200000000
-- RIGHT: (remove it) pass start_time/end_time as execute_sql params instead

-- unknown_function: replace hallucinated function
-- WRONG: SELECT extract_json(body, '$.error') FROM "stream"
-- RIGHT: SELECT spath(body, 'error') FROM "stream"

-- syntax_error: quote stream name
-- WRONG: FROM stream_name
-- RIGHT: FROM "stream_name"

-- policy_violation: fix count
-- WRONG: SELECT count(*) FROM "stream"
-- RIGHT: SELECT count(_timestamp) FROM "stream"
```
