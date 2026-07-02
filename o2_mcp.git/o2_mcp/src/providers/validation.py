"""Validation tools.

Tools:
  validate_sql_policy   AST/regex policy check — instant, no network
  validate_sql          Live SQL validation against O2 cluster
  validate_vrl          Live VRL script validation
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.providers import LocalProvider

from src.providers._shared import build_service
from src.tools.sql_policy import run_policy_preflight

provider = LocalProvider()


@provider.tool("validate_sql_policy")
def validate_sql_policy(sql: str) -> dict[str, Any]:
    """
    Run OpenObserve policy checks on SQL — instant, no network needed.

    ── ALWAYS CALL BEFORE execute_sql ─────────────────────────────────────────
    Run this on every SQL query BEFORE execute_sql to catch common ADL mistakes.
    It runs locally (AST + regex) — zero latency, no auth required.

    ── CHECKS PERFORMED ───────────────────────────────────────────────────────
    1. no_timestamp_predicate  — _timestamp in WHERE clause
       Fix: Remove WHERE _timestamp > ... and use time_range="1h" in execute_sql.

    2. no_select_star  — SELECT * usage
       Fix: Name specific fields: SELECT level, status_code, message FROM ...

    3. no_subquery_in_select  — Subquery in SELECT clause
       Fix: Use CTEs (WITH ... AS (...)) instead.

    Parameters:
        sql: SQL query string to check.

    Returns:
        {"ok": true|false, "used_ast": true|false, "violations": [...]}
    """
    return run_policy_preflight(sql).to_dict()


@provider.tool("validate_sql")
async def validate_sql(
    sql: str,
    endpoint: str,
    bearer_token: str,
    stream: str = "",
    organization: str = "default",
) -> dict[str, Any]:
    """
    Validate SQL against the live OpenObserve cluster (1-second time window).

    ── WHEN TO CALL ───────────────────────────────────────────────────────────
    Call after validate_sql_policy passes, before execute_sql on large time ranges.
    Verifies syntax, field existence, function support, and type correctness.

    ── VALIDATION SEQUENCE ────────────────────────────────────────────────────
    1. validate_sql_policy(sql)    → instant policy check (no network)
    2. validate_sql(sql, ...)      → live syntax/field check (1-second window)
    3. execute_sql(sql_query, ...) → full execution

    Parameters:
        sql:          SQL query to validate.
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        stream:       Stream name for context in error messages.
        organization: O2 org ID (default: "default").

    Returns:
        {"valid": true, "message": "Query is valid", "took_ms": N}
        {"valid": false, "error": "field 'unknown_field' not found", "status_code": 400}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}

    return await svc.validate_sql(sql=sql, stream=stream)


@provider.tool("validate_vrl")
async def validate_vrl(
    vrl: str,
    endpoint: str,
    bearer_token: str,
    organization: str = "default",
    events: list[str] | None = None,
) -> dict[str, Any]:
    """
    Validate a VRL (Vector Remap Language) script against sample events.

    ── VRL RULES ──────────────────────────────────────────────────────────────
    • Use Rust regex syntax for all patterns.
    • Named capture groups: (?P<name>...) not (?<name>...)
    • parse_regex returns a tuple: .parsed, err = parse_regex(.message, pattern)
    • Use ! for fallible single-return functions: .status = to_int!(.status_code)
    • Never overwrite _timestamp field.

    Parameters:
        vrl:          VRL script to validate.
        endpoint:     O2 API base URL from wcnp_get_o2_config.
        bearer_token: Raw PingFederate access_token.
        organization: O2 org ID (default: "default").
        events:       Sample log JSON strings to test against (optional).

    Returns:
        {"valid": true, "output": {...}}
        {"valid": false, "error": "..."}
    """
    try:
        svc = build_service(endpoint, bearer_token, organization)
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}

    return await svc.validate_vrl(vrl=vrl, events=events)
