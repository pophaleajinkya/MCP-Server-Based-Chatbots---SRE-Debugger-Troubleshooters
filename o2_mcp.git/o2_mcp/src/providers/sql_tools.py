"""SQL analysis and registry tools — all local, no network.

Tools:
  validate_sql_functions    Scan all functions in a SQL query against registry
  check_sql_function        Look up DataFusion/O2 function signature + examples
  get_sql_correction_hint   Diagnose failed SQL + return structured correction guide
  get_o2_rules              OpenObserve SQL/VRL rules for prompt injection
  search_docs               Keyword search across DataFusion + O2 reference docs
"""
from __future__ import annotations

import re as _re
from typing import Any

from fastmcp.server.providers import LocalProvider

from src.config import get_settings
from src.providers._shared import (
    DATAFUSION_SQL_DOC,
    O2_FUNCTIONS_DOC,
    O2_GUIDE_DOC,
    read_doc,
)
from src.tools.rules import get_rules_engine

provider = LocalProvider()

# Doc key → path mapping used by search_docs
_DOC_MAP: dict[str, tuple[str, Any]] = {
    "datafusion":  ("datafusion", DATAFUSION_SQL_DOC),
    "o2functions": ("o2functions", O2_FUNCTIONS_DOC),
    "o2guide":     ("o2guide", O2_GUIDE_DOC),
}


@provider.tool("validate_sql_functions")
def validate_sql_functions_tool(sql: str) -> str:
    """
    Scan every function call in a SQL query against the DataFusion/O2 registry.

    Call this AFTER generating SQL and BEFORE validate_sql_policy / execute_sql.
    It extracts all function names via AST (sqlglot) or regex fallback, then
    batch-checks each one against the 236-function registry.

    ── AGENT LOOP ─────────────────────────────────────────────────────────────
    1. Generate SQL
    2. validate_sql_functions(sql)     ← catches hallucinated function names
    3. validate_sql_policy(sql)        ← catches structural violations
    4. execute_sql(sql, ...)           ← only if both above pass

    ── COMMON HALLUCINATED → CORRECT MAPPINGS ─────────────────────────────────
    extract_json(...)       → spath(field, 'nested.key')
    json_get_str(...)       → spath(field, 'nested.key')
    strftime(...)           → date_trunc('minute', _timestamp)
    percentile(col, 0.99)  → approx_percentile_cont(col, 0.99)
    contains(field, 'x')   → str_match_ignore_case(field, 'x')
    string_to_array(...)    → cast_to_arr(field)

    Parameters:
        sql: SQL query string to validate (SELECT queries only).

    Returns:
        JSON string — always safe to parse, never raises.
    """
    from src.tools.sql_function_registry import validate_sql_functions
    return validate_sql_functions(sql)


@provider.tool("check_sql_function")
def check_sql_function_tool(function_name: str) -> str:
    """
    Look up a DataFusion / OpenObserve SQL function by name.

    Use this before writing a SQL query whenever you are unsure whether a
    function is supported. Returns exact syntax, description, and examples.

    ── WHEN TO CALL ───────────────────────────────────────────────────────────
    • You are about to use a function you have not verified before.
    • validate_sql_functions returned an invalid function.
    • The user asks "does O2 support X()?".

    ── KEY O2 FUNCTIONS ───────────────────────────────────────────────────────
    Time series:  histogram(_timestamp, 'minute'|'hour'|'day'|...)
    FTS search:   match_all('keyword')
    Field search: str_match_ignore_case(field, 'keyword')
    Arrays:       cast_to_arr(field), arr_descending(field)
    JSON / path:  spath(json_field, 'nested.key')
    Percentile:   approx_percentile_cont(col, 0.99)
    Aggregation:  count(_timestamp)  ← NOT count(*)

    Parameters:
        function_name: Case-insensitive function name (e.g. "histogram", "match_all").

    Returns:
        JSON string — always safe to parse, never raises.
    """
    from src.tools.sql_function_registry import check_sql_function
    return check_sql_function(function_name)


@provider.tool("get_sql_correction_hint")
def get_sql_correction_hint(sql: str, error_message: str) -> dict[str, Any]:
    """
    Diagnose a failed SQL query and return a structured correction guide.

    Call this IMMEDIATELY after execute_sql returns success=False.
    Returns error_type, correction_hint, and suggested_tools to call next —
    all without network access or an LLM inside o2_mcp.

    ── THE RETRY LOOP (super-agent implements this) ───────────────────────────
    Read o2://retry-guide for the full protocol. Summary:

      attempt = 1
      while attempt <= max_retries:
          result = execute_sql(sql, attempt=attempt, ...)
          if result["success"]: break
          hint = get_sql_correction_hint(sql, result["error"])
          if not hint["retry_allowed"]: break   ← auth error, stop
          sql = <LLM corrects SQL using correction_hint>
          attempt += 1

    ── ERROR TYPE TAXONOMY ────────────────────────────────────────────────────
    unknown_column    → column not in schema → call get_stream_schema
    unknown_function  → function not in DataFusion → call validate_sql_functions
    syntax_error      → parse error → fix DataFusion syntax, call validate_sql
    policy_violation  → ADL rule broken → call validate_sql_policy
    stream_not_found  → FROM "wrong_name" → call list_streams
    auth_error        → 401/403 → call pingfed_playwright_token (NO retry)
    timeout           → query too slow → add partition key filters, reduce range
    type_mismatch     → CAST error → add explicit CAST
    limit_exceeded    → too many rows → add/lower LIMIT
    empty_result      → 0 rows → broaden time_range or check default_filter
    unknown           → no pattern matched → call validate_sql_policy + validate_sql

    Parameters:
        sql:           The SQL string that failed.
        error_message: The error string from execute_sql result["error"].

    Returns:
        Dict with error_type, summary, correction_hint, retry_allowed, suggested_tools.
    """
    from src.tools.sql_error_classifier import classify_sql_error

    if not error_message:
        return {
            "error_type": "unknown",
            "summary": "No error message provided.",
            "correction_hint": "Check execute_sql result for the error field.",
            "retry_allowed": True,
            "suggested_tools": ["validate_sql_policy", "validate_sql"],
        }

    cfg = get_settings()
    result = classify_sql_error(error_message).to_dict()
    result["failed_sql"] = sql
    result["max_retries"] = cfg.max_retries
    result["config_env"] = "O2_MAX_RETRIES"
    return result


@provider.tool("get_o2_rules")
def get_o2_rules(intent: str = "sql") -> dict[str, Any]:
    """
    Return OpenObserve-specific rules for generating SQL or VRL.

    ── WHEN TO USE ────────────────────────────────────────────────────────────
    Call this when you need a formatted rules reference for a specific intent.
    The returned "formatted" string can be injected into an LLM prompt to
    guide SQL/VRL generation.

    Useful intents:
    • "sql"               → DataFusion SQL rules for OpenObserve queries
    • "vrl"               → VRL scripting rules for pipelines
    • "query_optimization" → How to make queries faster (partition keys, FTS)
    • "log_analysis"      → Patterns for analyzing log data

    Parameters:
        intent: "sql" | "vrl" | "query_optimization" | "vrl_optimization" |
                "log_analysis" | "general"  (default: "sql")

    Returns:
        {"intent": "sql", "rules": [...], "formatted": "...", "available_intents": [...]}
    """
    engine = get_rules_engine()
    return {
        "success": True,
        "intent": intent,
        "rules": engine.get_rules(intent),
        "formatted": engine.format_rules(intent),
        "available_intents": list(engine.INTENT_CATEGORY_MAP.keys()),
    }


@provider.tool("search_docs")
def search_docs(query: str, doc: str = "all") -> dict[str, Any]:
    """
    Search the DataFusion and OpenObserve documentation for a keyword or function.

    Use this when you need to look up a specific function, pattern, or concept
    WITHOUT reading an entire reference document. Returns matching sections with
    surrounding context.

    ── WHEN TO CALL ───────────────────────────────────────────────────────────
    • You need the exact syntax for a function (e.g. "date_bin", "fuzzy_match")
    • You want to know if a function exists and what it does
    • You're looking for usage examples for a specific pattern
    • validate_sql_functions returned an unknown function — search for alternatives
    • You want to understand a DataFusion concept (window functions, CTEs, etc.)

    ── DOCS AVAILABLE ─────────────────────────────────────────────────────────
    doc="datafusion"   → 223 standard DataFusion SQL functions
    doc="o2functions"  → 20+ OpenObserve-specific UDFs/UDAFs
    doc="o2guide"      → SQL philosophy, field names, VRL patterns
    doc="all"          → Search all three (default)

    Parameters:
        query: Keyword or function name to search for (case-insensitive).
        doc:   Which doc to search: "datafusion" | "o2functions" | "o2guide" | "all"

    Returns:
        Dict with matches list and total_match_count.
    """
    if not query or not query.strip():
        return {"error": "query is required", "matches": [], "total_matches": 0}

    targets = (
        list(_DOC_MAP.values())
        if doc == "all"
        else [v for k, v in _DOC_MAP.items() if k == doc.lower()]
    )

    if not targets:
        return {
            "error": f"Unknown doc '{doc}'. Use: datafusion, o2functions, o2guide, all",
            "matches": [],
            "total_matches": 0,
        }

    pattern = _re.compile(_re.escape(query.strip()), _re.IGNORECASE)
    all_matches: list[dict[str, Any]] = []

    for doc_key, doc_path in targets:
        if not doc_path.exists():
            continue

        lines = read_doc(doc_path, "").splitlines()
        sections: list[dict[str, Any]] = []
        i = 0
        while i < len(lines):
            if pattern.search(lines[i]):
                start = max(0, i - 2)
                end = min(len(lines), i + 8)
                snippet = "\n".join(lines[start:end])
                heading = next(
                    (lines[j].strip() for j in range(i, -1, -1) if lines[j].startswith("#")),
                    "",
                )
                sections.append({"heading": heading, "snippet": snippet, "line": i + 1})
                i = end
            else:
                i += 1

        if sections:
            seen: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for s in sections:
                if s["heading"] not in seen:
                    seen.add(s["heading"])
                    deduped.append(s)

            all_matches.append({
                "doc": doc_key,
                "match_count": len(sections),
                "sections": deduped[:5],
            })

    total = sum(m["match_count"] for m in all_matches)
    return {
        "query": query,
        "matches": all_matches,
        "total_matches": total,
        "hint": (
            "Use o2://datafusion-sql, o2://o2-functions, or o2://o2-guide "
            "to read the full document."
        ) if total == 0 else None,
    }
