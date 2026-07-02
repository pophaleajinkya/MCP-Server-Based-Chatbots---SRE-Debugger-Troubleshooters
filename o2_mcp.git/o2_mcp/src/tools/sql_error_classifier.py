"""SQL error classifier for the o2_mcp retry loop.

Converts raw OpenObserve / DataFusion error messages into structured
correction payloads that the super-agent LLM can act on directly.

No LLM required — pure regex/string pattern matching.
The super-agent reads the classification and self-corrects the SQL
using its own language model capabilities.

Error taxonomy
──────────────
unknown_column       Column referenced in SQL does not exist in stream schema.
unknown_function     Function not available in DataFusion/OpenObserve.
syntax_error         SQL parse error — bad tokens, missing keywords, etc.
policy_violation     Violates ADL rules (_timestamp in WHERE, SELECT *, etc.).
stream_not_found     Stream / table not found in organization.
auth_error           401/403 — token expired, need fresh bearer token.
timeout              Query took too long — needs simplification.
limit_exceeded       Result set too large — add/lower LIMIT.
type_mismatch        CAST error or type incompatibility.
empty_result         Query succeeded but returned zero rows.
unknown              No specific pattern matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SqlErrorClassification:
    """Structured diagnosis of a SQL execution error."""

    error_type: str
    """Short machine-readable category (see module docstring taxonomy)."""

    summary: str
    """One-line human-readable summary of what went wrong."""

    correction_hint: str
    """Actionable instruction for the LLM to fix the SQL."""

    retry_allowed: bool = True
    """False only for auth errors and hard limits — agent should not retry."""

    suggested_tools: tuple[str, ...] = field(default_factory=tuple)
    """MCP tools that can help fix this error (in call order)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "summary": self.summary,
            "correction_hint": self.correction_hint,
            "retry_allowed": self.retry_allowed,
            "suggested_tools": list(self.suggested_tools),
        }


# ---------------------------------------------------------------------------
# Pattern registry — ordered most-specific to least-specific
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[re.Pattern, SqlErrorClassification]] = []


def _p(pattern: str, classification: SqlErrorClassification) -> None:
    _PATTERNS.append((re.compile(pattern, re.IGNORECASE | re.DOTALL), classification))


# Auth errors — no retry
_p(
    r"\b(401|403)\b|unauthorized|forbidden|token.*expired|auth.*fail",
    SqlErrorClassification(
        error_type="auth_error",
        summary="Authentication failed — bearer token expired.",
        correction_hint=(
            "Do NOT retry the SQL. Call pingfed_playwright_token(cluster_lb=...) "
            "to get a fresh token, then call connect_o2(..., bearer_token=<new_token>), "
            "then retry the original SQL."
        ),
        retry_allowed=False,
        suggested_tools=("pingfed_playwright_token", "connect_o2"),
    ),
)

# Unknown column
_p(
    r"column[s]?\s+['\"]?(\w+)['\"]?\s+(does not exist|not found|unknown)"
    r"|no field named ['\"]?(\w+)['\"]?"
    r"|field ['\"]?(\w+)['\"]? (does not exist|not found)",
    SqlErrorClassification(
        error_type="unknown_column",
        summary="A column referenced in the SQL does not exist in the stream schema.",
        correction_hint=(
            "Call get_stream_schema() to get the actual field list. "
            "Replace the unknown column with a valid field from defined_schema_fields. "
            "If the field exists in _raw (not in schema), use spath(_raw, 'field_name') instead."
        ),
        retry_allowed=True,
        suggested_tools=("get_stream_schema", "validate_sql_functions"),
    ),
)

# Unknown / unsupported function
_p(
    r"function\s+['\"]?(\w+)['\"]?\s+(does not exist|not found|unknown|not supported)"
    r"|no function named ['\"]?(\w+)['\"]?"
    r"|unknown function[:\s]+['\"]?(\w+)['\"]?",
    SqlErrorClassification(
        error_type="unknown_function",
        summary="A SQL function used in the query is not available in DataFusion/OpenObserve.",
        correction_hint=(
            "Call validate_sql_functions(sql) to identify all invalid function names. "
            "Then call check_sql_function(name) for each invalid one to get the correct "
            "DataFusion/O2 equivalent. Common replacements: "
            "extract_json→spath, json_get_str→spath, strftime→date_trunc, "
            "contains→str_match_ignore_case, string_to_array→cast_to_arr."
        ),
        retry_allowed=True,
        suggested_tools=("validate_sql_functions", "check_sql_function"),
    ),
)

# _timestamp in WHERE — policy violation
_p(
    r"_timestamp.*where|where.*_timestamp"
    r"|timestamp.*predicate|predicate.*timestamp",
    SqlErrorClassification(
        error_type="policy_violation",
        summary="Query has _timestamp in WHERE clause — forbidden by ADL rules.",
        correction_hint=(
            "REMOVE the _timestamp filter from the WHERE clause entirely. "
            "OpenObserve applies the time range automatically from start_time/end_time params. "
            "Pass start_time and end_time as execute_sql parameters instead of SQL predicates."
        ),
        retry_allowed=True,
        suggested_tools=("validate_sql_policy",),
    ),
)

# SELECT * — policy violation
_p(
    r"select \*|select\s+\*|no_select_star",
    SqlErrorClassification(
        error_type="policy_violation",
        summary="Query uses SELECT * — forbidden by ADL rules.",
        correction_hint=(
            "Replace SELECT * with explicit column names. "
            "Call get_stream_schema() to see available fields, "
            "then list only the fields relevant to the user's question."
        ),
        retry_allowed=True,
        suggested_tools=("get_stream_schema",),
    ),
)

# count(*) — wrong aggregate
_p(
    r"count\(\s*\*\s*\)|no_count_star|count\(\*\)",
    SqlErrorClassification(
        error_type="policy_violation",
        summary="Query uses count(*) — OpenObserve requires count(_timestamp).",
        correction_hint=(
            "Replace count(*) with count(_timestamp). "
            "OpenObserve does not support count(*) in DataFusion mode."
        ),
        retry_allowed=True,
        suggested_tools=("validate_sql_policy",),
    ),
)

# Stream / table not found
_p(
    r"table\s+['\"]?(\w+)['\"]?\s+(not found|does not exist)"
    r"|stream\s+['\"]?(\w+)['\"]?\s+(not found|does not exist)"
    r"|no such (table|stream)",
    SqlErrorClassification(
        error_type="stream_not_found",
        summary="The stream/table referenced in FROM clause was not found.",
        correction_hint=(
            "Call list_streams() to get all available streams in the organization. "
            "Use the exact stream name from the list, quoted with double quotes: "
            'FROM "stream_name".'
        ),
        retry_allowed=True,
        suggested_tools=("list_streams",),
    ),
)

# Type mismatch / cast error
_p(
    r"type.*(mismatch|error|incompatib)"
    r"|cannot cast|invalid cast|cast.*fail"
    r"|expected.*type|type.*expected",
    SqlErrorClassification(
        error_type="type_mismatch",
        summary="Type mismatch — CAST failed or incompatible types in expression.",
        correction_hint=(
            "Add explicit CAST: CAST(field AS INT), CAST(field AS VARCHAR), etc. "
            "For status codes stored as strings: CAST(status_code AS INT) >= 500. "
            "For timestamps: values are already BIGINT microseconds — do not cast to timestamp type."
        ),
        retry_allowed=True,
        suggested_tools=(),
    ),
)

# Timeout
_p(
    r"timeout|timed out|query.*too long|execution.*exceeded",
    SqlErrorClassification(
        error_type="timeout",
        summary="Query timed out — too much data scanned or query too complex.",
        correction_hint=(
            "Simplify the query: "
            "1. Add partition key filters in WHERE to reduce scan size. "
            "2. Reduce the time_range (e.g. '15m' instead of '24h'). "
            "3. Lower the LIMIT. "
            "4. Remove expensive operations like unnest/array_agg on large datasets. "
            "Call get_stream_schema() to identify partition_keys."
        ),
        retry_allowed=True,
        suggested_tools=("get_stream_schema",),
    ),
)

# Limit / result too large
_p(
    r"result.*too large|too many rows|limit.*exceeded|max.*rows",
    SqlErrorClassification(
        error_type="limit_exceeded",
        summary="Result set is too large — query returned more rows than allowed.",
        correction_hint=(
            "Add or lower the LIMIT clause (e.g. LIMIT 100). "
            "Also consider narrowing the WHERE clause or reducing time_range."
        ),
        retry_allowed=True,
        suggested_tools=(),
    ),
)

# Generic syntax error
_p(
    r"syntax error|parse error|unexpected token|expected.*got"
    r"|invalid sql|malformed|unexpected end",
    SqlErrorClassification(
        error_type="syntax_error",
        summary="SQL syntax error — the query could not be parsed by DataFusion.",
        correction_hint=(
            "Fix the SQL syntax. Key DataFusion rules: "
            "1. Stream names must be double-quoted: FROM \"stream_name\". "
            "2. Use DataFusion syntax only — no PostgreSQL/MySQL extensions. "
            "3. String literals use single quotes: WHERE level = 'error'. "
            "4. CTEs: WITH name AS (SELECT ...) SELECT ... FROM name. "
            "Call validate_sql(sql) after fixing to confirm syntax before execute_sql."
        ),
        retry_allowed=True,
        suggested_tools=("validate_sql", "validate_sql_policy"),
    ),
)

# Empty result — not an error but useful signal
_p(
    r"empty result|no (rows|results|data)|0 (rows|results|hits)",
    SqlErrorClassification(
        error_type="empty_result",
        summary="Query succeeded but returned zero rows.",
        correction_hint=(
            "The query ran but found nothing. Try: "
            "1. Broaden time_range (e.g. '24h' instead of '1h'). "
            "2. Check default_filter — it may be too restrictive. "
            "3. Call get_field_values(field) to see what values actually exist. "
            "4. Verify stream name with list_streams()."
        ),
        retry_allowed=True,
        suggested_tools=("get_field_values", "list_streams"),
    ),
)

# Fallback
_FALLBACK = SqlErrorClassification(
    error_type="unknown",
    summary="Unknown error — no specific pattern matched.",
    correction_hint=(
        "Review the raw error message. Common fixes: "
        "1. Call validate_sql_policy(sql) to check for ADL rule violations. "
        "2. Call validate_sql(sql) for live syntax check against O2. "
        "3. Call get_stream_schema() to verify column names. "
        "4. Call get_o2_rules('sql') for full DataFusion rule reference."
    ),
    retry_allowed=True,
    suggested_tools=("validate_sql_policy", "validate_sql", "get_stream_schema"),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_sql_error(error_message: str) -> SqlErrorClassification:
    """Classify a SQL execution error into a structured correction payload.

    Tries each pattern in priority order. Returns FALLBACK if nothing matches.

    Args:
        error_message: Raw error string from execute_sql or O2 API.

    Returns:
        SqlErrorClassification with error_type, correction_hint, retry_allowed.
    """
    if not error_message:
        return _FALLBACK

    for pattern, classification in _PATTERNS:
        if pattern.search(error_message):
            return classification

    return _FALLBACK


def enrich_error_response(
    response: dict,
    attempt: int = 1,
    max_retries: int = 5,
) -> dict:
    """Add classification fields to a failed execute_sql response dict.

    Mutates and returns the response dict in-place.

    Args:
        response:    execute_sql response with success=False.
        attempt:     Current attempt number (1-based).
        max_retries: Configured maximum retries.

    Returns:
        Enriched response dict.
    """
    error_msg = response.get("error", "")
    classification = classify_sql_error(error_msg)

    response["sql_error_type"]   = classification.error_type
    response["correction_hint"]  = classification.correction_hint
    response["retry_allowed"]    = (
        classification.retry_allowed and attempt < max_retries
    )
    response["attempt"]          = attempt
    response["max_retries"]      = max_retries
    response["retries_remaining"] = max(0, max_retries - attempt)
    response["suggested_tools"]  = list(classification.suggested_tools)

    if response["retry_allowed"]:
        response["retry_instructions"] = (
            f"Attempt {attempt}/{max_retries} failed. "
            f"Read correction_hint and suggested_tools, fix the SQL, "
            f"then call execute_sql again. "
            f"{max_retries - attempt} retries remaining."
        )
    else:
        response["retry_instructions"] = (
            f"Retry not recommended for error type '{classification.error_type}'. "
            f"Follow correction_hint to resolve the root cause first."
        )

    return response
