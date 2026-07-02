"""Query tools — stateless, all credentials passed per call.

Tools:
  execute_sql        Run a SQL SELECT query (ADL / DataFusion dialect)
  search_around      Fetch logs ±5 min around a timestamp
  get_field_values   Get unique field values with counts
  get_stream_schema  Fetch compact, pruned stream schema
  list_streams       List all streams in org
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import build_service

provider = LocalProvider()


@provider.tool("execute_sql")
async def execute_sql(
    sql_query: str,
    endpoint: str,
    bearer_token: str,
    stream: str = "",
    organization: str = "default",
    time_range: str = "1h",
    limit: int = 1000,
    start_time: int = 0,
    end_time: int = 0,
    attempt: int = 1,
) -> dict[str, Any]:
    """
    Execute a SQL SELECT query against OpenObserve (DataFusion / ADL dialect).

    ── CREDENTIALS ────────────────────────────────────────────────────────────
    endpoint:     From wcnp_get_o2_config → "endpoint"
    bearer_token: From pingfed_playwright_token → "token"
    organization: From wcnp_get_o2_config → "organization" (default: "default")
    stream:       From wcnp_get_o2_config → "stream" (e.g. "k8s_json")

    ── TOOL SELECTION GUIDE ───────────────────────────────────────────────────
    Use this tool for ALL log queries: error counts, 5XX rates, latency
    percentiles, histogram trends, field groupings, and full-text search.
    Call get_stream_schema first to understand available fields.
    Always run validate_sql_policy before this tool to catch common mistakes.

    ── SQL TRANSLATION RULES (ADL) ────────────────────────────────────────────
    CRITICAL — NEVER add _timestamp filters: O2 auto-applies time range.
    Always quote stream name: FROM "stream_name"
    Use count(_timestamp) not count(*) for aggregations.
    NEVER SELECT * — always name specific fields.
    For FTS-indexed fields (full_text_search_keys): match_all('keyword')
    For other fields: str_match_ignore_case(field, 'keyword')
    DataFusion functions only — no PostgreSQL/MySQL syntax.

    ── DEFAULT FILTER ─────────────────────────────────────────────────────────
    ALWAYS inject the default_filter from wcnp_get_o2_config into your WHERE clause.
    Example — 5XX error count with default_filter:

        SELECT status_code, count(_timestamp) AS total
        FROM   "k8s_json"
        WHERE  kubernetes_namespace_name = 'my-ns'
          AND  kubernetes_labels_app = 'my-app'
          AND  CAST(status_code AS INT) >= 500
        GROUP BY status_code
        ORDER BY total DESC
        LIMIT 100

    ── TIME WINDOWS ───────────────────────────────────────────────────────────
    time_range: "30m" | "1h" | "3h" | "24h" | "7d"  (default: "1h")
    For incident windows use start_time + end_time in MICROSECONDS.
    Call get_time to convert dates → microseconds.

    ── AUTH ERRORS ────────────────────────────────────────────────────────────
    If result contains {"auth_expired": true}:
        1. Call pingfed_playwright_token(cluster_lb=<cluster_lb>)
        2. Retry this tool with the new bearer_token.

    Parameters:
        sql_query:    SQL SELECT statement. Stream quoted in FROM clause.
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        stream:       Stream name (e.g. "k8s_json"). FROM clause takes precedence.
        organization: O2 org ID (default: "default").
        time_range:   Relative window: "30m"|"1h"|"3h"|"24h"|"7d" (default: "1h").
        limit:        Max rows (default: 1000).
        start_time:   Absolute start in MICROSECONDS (overrides time_range).
        end_time:     Absolute end in MICROSECONDS (overrides time_range).
        attempt:      Retry attempt number (1-based) for error enrichment.

    Returns:
        {"success": true, "hits": [...], "total": N, "took_ms": N}
        {"success": false, "error": "...", "auth_expired": true}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return await svc.execute_sql(
        sql=sql_query,
        stream=stream,
        time_range=time_range,
        limit=limit,
        start_time=start_time if start_time > 0 else None,
        end_time=end_time if end_time > 0 else None,
        attempt=max(1, attempt),
    )


@provider.tool("search_around")
async def search_around(
    timestamp: int,
    endpoint: str,
    bearer_token: str,
    stream: str,
    organization: str = "default",
    size: int = 10,
) -> dict[str, Any]:
    """
    Fetch logs immediately before and after a known _timestamp using OpenObserve's
    dedicated index-seek API (GET /{org}/{stream}/_around).

    ── WHAT THIS DOES (and why it's NOT SQL) ──────────────────────────────────
    This calls OpenObserve's /_around endpoint — NOT a SQL query.
    O2 performs a direct index seek to the exact microsecond position in the
    stream and returns `size` log lines before + after that point in one call.

    You CANNOT replicate this with execute_sql + match_all because:
    • match_all() is a full-text inverted index search (keyword → documents)
    • /_around is a time-position seek (timestamp → surrounding rows)
    These are fundamentally different operations on different indexes.

    ── WHEN TO USE (after execute_sql, not instead of it) ─────────────────────
    Use ONLY when you already have an exact `_timestamp` value from a prior
    execute_sql result and need surrounding log context for root-cause analysis.

    Wrong use — do NOT call this to search for errors:
      ✗ search_around(timestamp=<now>)         ← no known event yet
      ✗ search_around to find "OOMKilled"      ← use execute_sql + match_all()

    Correct use — call AFTER finding a specific event:
      1. execute_sql → finds error event, returns its _timestamp (e.g. 1704067200123456)
      2. search_around(timestamp=1704067200123456) → gets the 10 lines before + after

    ── DO NOT CONFUSE WITH ────────────────────────────────────────────────────
    match_all('keyword')              → full-text search, use in execute_sql WHERE
    str_match_ignore_case(f, 'kw')   → field-level keyword search, use in SQL
    execute_sql with time_range       → scan a time window with SQL filters

    Parameters:
        timestamp:    Exact _timestamp in MICROSECONDS from a prior execute_sql hit.
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        stream:       Stream name from wcnp_get_o2_config.
        organization: O2 org ID (default: "default").
        size:         Total log lines to return (split evenly before/after, default: 10).

    Returns:
        {"success": true, "data": {...}, "stream": "...", "timestamp": N}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return await svc.search_around(stream=stream, timestamp=timestamp, size=size)


@provider.tool("get_field_values")
async def get_field_values(
    fields: list[str],
    endpoint: str,
    bearer_token: str,
    stream: str,
    organization: str = "default",
    time_range: str = "1h",
    size: int = 100,
    keyword: str = "",
    no_count: bool = False,
) -> dict[str, Any]:
    """
    Get unique values (with occurrence counts) for specific fields.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use this to EXPLORE a field before writing a SQL query:
    • Check what values status_code has ("200", "404", "500"?)
    • See what log levels exist ("INFO", "ERROR", "WARN"?)
    • Understand field cardinality before grouping

    ── VS. execute_sql ────────────────────────────────────────────────────────
    get_field_values:  exploration — "what values does this field have?"
    execute_sql:       analysis — "how many 5XX per endpoint?"

    Parameters:
        fields:       List of field names to explore, e.g. ["status_code", "level"].
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        stream:       Stream name from wcnp_get_o2_config.
        organization: O2 org ID (default: "default").
        time_range:   Time window: "30m"|"1h"|"3h"|"24h"|"7d" (default: "1h").
        size:         Max unique values per field (default: 100).
        keyword:      Filter returned values to those containing this substring.
        no_count:     Skip counting occurrences (faster when only values needed).

    Returns:
        {"success": true, "fields": [{"field": "...", "values": [{"value": "...", "count": N}]}]}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return await svc.get_field_values(
        stream=stream,
        fields=fields,
        time_range=time_range,
        size=size,
        keyword=keyword,
        no_count=no_count,
    )


@provider.tool("get_stream_schema")
async def get_stream_schema(
    endpoint: str,
    bearer_token: str,
    stream: str,
    organization: str = "default",
    stream_type: str = "logs",
    user_prompt: str = "",
    fields: str = "",
    full_schema: bool = False,
) -> dict[str, Any]:
    """
    Fetch a compact, token-efficient schema for a log stream.

    ── CALL THIS FIRST ────────────────────────────────────────────────────────
    Always call get_stream_schema before the first execute_sql in any session.
    It tells you:
    • Which fields exist (defined_schema_fields) — use ONLY these in SELECT/WHERE
    • Which fields have inverted index (full_text_search_keys) → use match_all()
    • Which fields are partition keys → best for WHERE clause (faster scans)

    ── HOW TO USE THE SCHEMA ──────────────────────────────────────────────────
    1. defined_schema_fields → use in SELECT and WHERE clauses
       Other fields live in _raw — extract with: spath(_raw, 'field_name')

    2. full_text_search_keys → use match_all('keyword') for full-text search

    3. partition_keys → put these in WHERE first for fastest query performance

    ── SMART FIELD PRUNING ────────────────────────────────────────────────────
    When stream has >30 fields and user_prompt is provided, the schema is
    automatically pruned to fields mentioned in user_prompt + essential fields.
    Pass the user's ORIGINAL question as user_prompt for best results.

    Parameters:
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        stream:       Stream name from wcnp_get_o2_config.
        organization: O2 org ID (default: "default").
        stream_type:  "logs" | "metrics" | "traces" (default: "logs").
        user_prompt:  Original user question — drives smart field pruning.
        fields:       Comma-separated explicit fields to include.
        full_schema:  If True, return ALL fields without pruning.

    Returns:
        {"name": "k8s_json", "fields": {...}, "settings": {...}, "total_fields": N}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return await svc.get_stream_schema(
        stream=stream,
        stream_type=stream_type,
        user_prompt=user_prompt,
        fields=fields,
        full_schema=full_schema,
    )


@provider.tool("list_streams")
async def list_streams(
    endpoint: str,
    bearer_token: str,
    organization: str = "default",
    fetch_schema: bool = False,
    stream_type: str = "logs",
) -> dict[str, Any]:
    """
    List all streams in the OpenObserve organization.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Use this when:
    • You need to find the correct stream name before querying
    • User asks "what log streams are available?"
    • You're unsure whether to use k8s_json, app_logs, or another stream

    The stream name from wcnp_get_o2_config is usually correct, but use this
    to verify or explore alternatives.

    Parameters:
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        organization: O2 org ID (default: "default").
        fetch_schema: Include field schema for each stream (slower — use sparingly).
        stream_type:  "logs" | "metrics" | "traces" (default: "logs").

    Returns:
        {"success": true, "streams": [{"name": "k8s_json", ...}], "total": N}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return await svc.list_streams(fetch_schema=fetch_schema, stream_type=stream_type)
