"""AST-based SQL policy preflight checks for OpenObserve (RFC-06).

Ported from o2-ai-agent/src/agent/sql_policy_preflight.py.

Checks SQL for OpenObserve-specific violations BEFORE any remote call:
  - no_timestamp_predicate : _timestamp in WHERE (O2 handles time ranges itself)
  - no_select_star         : SELECT * (performance — pulls large _raw field)
  - no_subquery_in_select  : subquery inside SELECT expressions (not supported by DataFusion)

When sqlglot is available the checks use AST-derived SqlFacts for
deterministic, accurate results.  Falls back to regex heuristics
automatically when sqlglot is not installed or parse fails.

The remote validate_sql (1-second time-window live check) remains the
mandatory final gate and is NOT replaced by this module.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.sql.analysis import analyze_sql

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

@dataclass
class PolicyViolation:
    """A single policy violation with a repair hint."""

    rule: str
    """Machine-readable rule name (e.g. 'no_timestamp_predicate')."""

    message: str
    """Human-readable explanation."""

    hint: str
    """Actionable repair hint suitable for feeding back to the LLM."""


@dataclass
class PolicyResult:
    """Aggregate result of running all policy checks on a SQL string."""

    ok: bool = True
    """True when no violations were detected."""

    violations: list[PolicyViolation] = field(default_factory=list)
    """List of detected violations."""

    used_ast: bool = False
    """True if AST-derived facts were used; False if regex fallback."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "used_ast": self.used_ast,
            "violations": [
                {"rule": v.rule, "message": v.message, "hint": v.hint}
                for v in self.violations
            ],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_policy_preflight(sql: str) -> PolicyResult:
    """Run OpenObserve policy checks against *sql*.

    Tries AST-based checks first (requires sqlglot ≥26).
    Falls back to regex heuristics automatically when sqlglot is
    unavailable or the SQL cannot be parsed.

    Args:
        sql: Raw SQL query string.

    Returns:
        A PolicyResult — always safe to inspect, never raises.
    """
    if not sql or not sql.strip():
        return PolicyResult(ok=False, violations=[
            PolicyViolation(
                rule="empty_sql",
                message="SQL string is empty.",
                hint="Provide a valid SELECT statement.",
            )
        ])

    first_token = sql.strip().split()[0].upper()
    if first_token not in ("SELECT", "WITH"):
        return PolicyResult(ok=False, violations=[
            PolicyViolation(
                rule="non_select_query",
                message=f"Only SELECT queries are allowed. Got: {first_token}",
                hint=(
                    "OpenObserve via o2_mcp only supports SELECT statements "
                    "(including CTEs). DML and DDL statements are not permitted."
                ),
            )
        ])

    analysis = analyze_sql(sql)
    if analysis.ok and analysis.facts is not None:
        return _check_ast(analysis.facts)

    # AST unavailable or parse failed — use regex fallback
    if analysis.errors and analysis.errors != ("sqlglot not installed",):
        logger.debug("AST policy check fell back to regex: %s", analysis.errors)

    return _check_regex(sql)


# ---------------------------------------------------------------------------
# AST-based checks (accurate, deterministic)
# ---------------------------------------------------------------------------

def _check_ast(facts) -> PolicyResult:
    """Run policy checks using AST-derived SqlFacts."""
    violations: list[PolicyViolation] = []

    if facts.has_timestamp_predicate:
        preds = "; ".join(facts.timestamp_predicates) if facts.timestamp_predicates else "detected"
        violations.append(PolicyViolation(
            rule="no_timestamp_predicate",
            message=f"Query contains _timestamp predicate(s): {preds}",
            hint=(
                "Remove _timestamp predicates from the WHERE clause. "
                "OpenObserve applies the time range automatically from "
                "the request context (time_range or start_time/end_time parameters)."
            ),
        ))

    if facts.has_select_star:
        violations.append(PolicyViolation(
            rule="no_select_star",
            message="Query uses SELECT *.",
            hint=(
                "Replace SELECT * with explicit column names. "
                "SELECT * pulls the large _raw field and degrades performance."
            ),
        ))

    if facts.has_subquery_in_select:
        violations.append(PolicyViolation(
            rule="no_subquery_in_select",
            message="Query has a subquery in the SELECT clause.",
            hint=(
                "Subqueries in SELECT are not supported by OpenObserve (DataFusion). "
                "Move the subquery to a CTE (WITH clause) or a FROM subquery."
            ),
        ))

    return PolicyResult(ok=len(violations) == 0, violations=violations, used_ast=True)


# ---------------------------------------------------------------------------
# Regex fallback (used when sqlglot unavailable or parse fails)
# ---------------------------------------------------------------------------

_TIMESTAMP_RE = re.compile(
    r"WHERE.*_timestamp\s*[><=]"
    r"|_timestamp\s+BETWEEN"
    r"|time_range\s*\(",
    re.IGNORECASE,
)
_SELECT_STAR_RE = re.compile(r"SELECT\s+\*", re.IGNORECASE)
# Match subquery in SELECT column list: must appear BEFORE the first FROM/WHERE/GROUP/ORDER.
# Pattern: after SELECT (and before the first FROM), find a nested (SELECT ...).
# We capture the column list by stopping at FROM keyword (non-greedy within select columns).
_SUBQUERY_SELECT_RE = re.compile(
    r"^\s*(?:WITH\s+\w+\s+AS\s*\([^)]+\)\s*)?SELECT\s+(?:(?!FROM\b).)*?\(\s*SELECT\b",
    re.IGNORECASE | re.DOTALL,
)


def _check_regex(sql: str) -> PolicyResult:
    """Regex-based policy checks (fallback when AST unavailable)."""
    violations: list[PolicyViolation] = []

    if _TIMESTAMP_RE.search(sql):
        violations.append(PolicyViolation(
            rule="no_timestamp_predicate",
            message="Query appears to contain a _timestamp filter.",
            hint=(
                "Remove _timestamp predicates; OpenObserve applies "
                "the time range automatically."
            ),
        ))

    if _SELECT_STAR_RE.search(sql):
        violations.append(PolicyViolation(
            rule="no_select_star",
            message="Query uses SELECT *.",
            hint="Replace SELECT * with explicit column names.",
        ))

    if _SUBQUERY_SELECT_RE.search(sql):
        violations.append(PolicyViolation(
            rule="no_subquery_in_select",
            message="Query may have a subquery in the SELECT clause.",
            hint=(
                "Subqueries in SELECT are not supported by OpenObserve. "
                "Use a CTE or FROM subquery instead."
            ),
        ))

    return PolicyResult(ok=len(violations) == 0, violations=violations, used_ast=False)
