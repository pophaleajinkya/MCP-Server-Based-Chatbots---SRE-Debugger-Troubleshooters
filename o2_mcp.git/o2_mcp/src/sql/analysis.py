"""SQL facts extraction via AST traversal (RFC-06).

Ported from o2-ai-agent/src/sql/analysis.py.

Provides analyze_sql which parses SQL and walks the AST to produce a
backend-agnostic SqlFacts object.

The analysis is best-effort: when parsing fails we return a result
with ok=False so callers can fall back to regex heuristics.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.sql.ast_parser import parse_sql
from src.sql.models import SqlAnalysisResult, SqlFacts, SqlParseResult

if TYPE_CHECKING:
    from sqlglot import expressions as exp

logger = logging.getLogger(__name__)

_TIMESTAMP_COL = "_timestamp"

# SQL syntax constructs that sqlglot models as exp.Func subclasses.
# These are valid SQL keywords/expressions — NOT callable functions.
# Defined at module level to avoid re-creating the frozenset on every walk.
_SYNTAX_EXPRESSION_TYPES: frozenset[type] | None = None


def _get_syntax_expression_types() -> frozenset[type]:
    """Return the frozenset of sqlglot Func subclasses that are syntax, not functions.

    Lazily initialised once so sqlglot is only imported when actually needed.
    """
    global _SYNTAX_EXPRESSION_TYPES
    if _SYNTAX_EXPRESSION_TYPES is None:
        from sqlglot import expressions as exp
        _SYNTAX_EXPRESSION_TYPES = frozenset({
            exp.Case,     # CASE WHEN … END
            exp.Cast,     # CAST(x AS type)
            exp.TryCast,  # TRY_CAST(x AS type)
            exp.Extract,  # EXTRACT(part FROM ts)
            exp.Exists,   # EXISTS(subquery)
        })
    return _SYNTAX_EXPRESSION_TYPES


def analyze_sql(sql: str) -> SqlAnalysisResult:
    """Parse *sql* and extract structured SqlFacts.

    This is the primary public API for the src.sql package.
    It is safe to call on any string — it never raises.

    Args:
        sql: Raw SQL string.

    Returns:
        A SqlAnalysisResult with ok=True when both parsing and fact
        extraction succeeded, ok=False otherwise.
    """
    parse_result = parse_sql(sql)

    if parse_result.ast is None:
        return SqlAnalysisResult(
            ok=False,
            errors=parse_result.errors,
            backend=parse_result.backend,
        )

    return _extract_facts(parse_result)


# ------------------------------------------------------------------
# Internal extraction helpers
# ------------------------------------------------------------------


def _extract_facts(parse_result: SqlParseResult) -> SqlAnalysisResult:
    """Walk the AST(s) and build SqlFacts."""
    if parse_result.ast is None:
        return SqlAnalysisResult(
            ok=False,
            errors=(*parse_result.errors, "ast is None"),
            backend=parse_result.backend,
        )

    try:
        from sqlglot import expressions as exp

        statements: list[exp.Expression] = parse_result.ast  # type: ignore[assignment]

        streams: set[str] = set()
        columns: set[str] = set()
        functions: set[str] = set()
        timestamp_predicates: list[str] = []
        group_by_exprs: list[str] = []
        order_by_exprs: list[str] = []
        has_select_star = False
        has_group_by = False
        has_order_by = False
        has_subquery = False
        has_subquery_in_select = False
        limit_val: int | None = None
        join_count = 0

        for stmt in statements:
            cte_names = _collect_cte_names(stmt)
            streams.update(_collect_streams(stmt, cte_names))
            columns.update(_collect_columns(stmt))
            functions.update(_collect_functions(stmt))

            if _has_select_star(stmt):
                has_select_star = True

            ts_preds = _collect_timestamp_predicates(stmt)
            timestamp_predicates.extend(ts_preds)

            gb = _collect_group_by(stmt)
            if gb:
                has_group_by = True
                group_by_exprs.extend(gb)

            ob = _collect_order_by(stmt)
            if ob:
                has_order_by = True
                order_by_exprs.extend(ob)

            lim = _extract_limit(stmt)
            if lim is not None:
                limit_val = lim

            join_count += _count_joins(stmt)

            if _has_subquery(stmt):
                has_subquery = True
            if _has_subquery_in_select(stmt):
                has_subquery_in_select = True

        facts = SqlFacts(
            streams=frozenset(streams),
            columns=frozenset(columns),
            functions=frozenset(functions),
            has_select_star=has_select_star,
            has_timestamp_predicate=len(timestamp_predicates) > 0,
            timestamp_predicates=tuple(timestamp_predicates),
            has_group_by=has_group_by,
            group_by_exprs=tuple(group_by_exprs),
            has_order_by=has_order_by,
            order_by_exprs=tuple(order_by_exprs),
            limit=limit_val,
            join_count=join_count,
            has_subquery=has_subquery,
            has_subquery_in_select=has_subquery_in_select,
        )

        return SqlAnalysisResult(
            ok=parse_result.ok,
            facts=facts,
            errors=parse_result.errors,
            backend=parse_result.backend,
        )
    except Exception as exc:
        logger.warning("AST analysis failed: %s", exc, exc_info=True)
        return SqlAnalysisResult(
            ok=False,
            errors=(*parse_result.errors, f"analysis error: {exc}"),
            backend=parse_result.backend,
        )


# ------------------------------------------------------------------
# Individual fact collectors — all accept opaque sqlglot Expression
# ------------------------------------------------------------------


def _collect_cte_names(stmt: Any) -> set[str]:
    """Return lowercased names of all CTEs defined in *stmt*."""
    from sqlglot import expressions as exp

    names: set[str] = set()
    for cte in stmt.find_all(exp.CTE):
        alias = cte.args.get("alias")
        if alias and hasattr(alias, "name"):
            names.add(alias.name.lower())
    return names


def _collect_streams(stmt: Any, cte_names: set[str]) -> set[str]:
    """Collect FROM/JOIN source table names, excluding CTE aliases."""
    from sqlglot import expressions as exp

    tables: set[str] = set()
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in cte_names:
            tables.add(name)
    return tables


def _collect_columns(stmt: Any) -> set[str]:
    """Collect referenced column identifiers (best-effort, lowercased)."""
    from sqlglot import expressions as exp

    cols: set[str] = set()
    for col in stmt.find_all(exp.Column):
        name = col.name.lower()
        if name:
            cols.add(name)
    return cols


def _is_case_derived_if(node: Any) -> bool:
    """Return True when node is an exp.If produced by a CASE expression.

    sqlglot represents each WHEN branch of a CASE as an exp.If child.
    These are internal AST artefacts, not real IF() function calls.
    Check only the immediate parent — CASE-derived If nodes always have
    a Case as their direct parent.
    """
    from sqlglot import expressions as exp

    return isinstance(node, exp.If) and isinstance(node.parent, exp.Case)


def _collect_functions(stmt: Any) -> set[str]:
    """Collect function call names (lowercased).

    Filters out SQL syntax constructs that sqlglot models as
    exp.Func subclasses (CASE, CAST, TRY_CAST, EXTRACT, EXISTS)
    and CASE-derived exp.If nodes.
    """
    from sqlglot import expressions as exp

    syntax_types = _get_syntax_expression_types()
    funcs: set[str] = set()
    for func in stmt.find_all(exp.Func):
        if type(func) in syntax_types:
            continue
        if _is_case_derived_if(func):
            continue
        if isinstance(func, exp.Anonymous):
            funcs.add(func.name.lower())
        else:
            funcs.add(type(func).sql_name().lower())  # type: ignore[no-untyped-call]
    return funcs


def _has_select_star(stmt: Any) -> bool:
    """Check if query contains SELECT *."""
    from sqlglot import expressions as exp

    select_exprs: list[Any] = stmt.args.get("expressions", [])
    return any(isinstance(e, exp.Star) for e in select_exprs)


def _collect_timestamp_predicates(stmt: Any) -> list[str]:
    """Find predicates referencing _timestamp in WHERE clauses."""
    from sqlglot import expressions as exp

    predicates: list[str] = []
    for where in stmt.find_all(exp.Where):
        for col in where.find_all(exp.Column):
            if col.name.lower() == _TIMESTAMP_COL:
                parent = col.parent
                if parent is not None:
                    predicates.append(parent.sql())
    return predicates


def _collect_group_by(stmt: Any) -> list[str]:
    """Return rendered GROUP BY expressions, empty list if absent."""
    from sqlglot import expressions as exp

    group = stmt.find(exp.Group)
    if group is None:
        return []
    return [e.sql() for e in group.expressions]


def _collect_order_by(stmt: Any) -> list[str]:
    """Return rendered ORDER BY expressions, empty list if absent."""
    from sqlglot import expressions as exp

    order = stmt.find(exp.Order)
    if order is None:
        return []
    return [e.sql() for e in order.expressions]


def _extract_limit(stmt: Any) -> int | None:
    """Extract LIMIT value as an integer, or None."""
    from sqlglot import expressions as exp

    limit = stmt.find(exp.Limit)
    if limit is None:
        return None
    try:
        return int(limit.expression.this)
    except (ValueError, TypeError, AttributeError):
        return None


def _count_joins(stmt: Any) -> int:
    """Count JOIN clauses in the statement."""
    from sqlglot import expressions as exp

    return len(list(stmt.find_all(exp.Join)))


def _has_subquery(stmt: Any) -> bool:
    """Check if the statement contains any subquery."""
    from sqlglot import expressions as exp

    return any(True for _ in stmt.find_all(exp.Subquery))


def _has_subquery_in_select(stmt: Any) -> bool:
    """Check if there is a subquery inside the SELECT expressions.

    Specifically disallowed in OpenObserve.
    """
    from sqlglot import expressions as exp

    select_exprs: list[Any] = stmt.args.get("expressions", [])
    return any(list(expr.find_all(exp.Subquery)) for expr in select_exprs)
