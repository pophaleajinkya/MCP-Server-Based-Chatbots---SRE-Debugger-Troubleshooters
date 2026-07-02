"""Sqlglot-based SQL parser backend (RFC-06).

Ported from o2-ai-agent/src/sql/ast_parser.py.

Exposes a single public function ``parse_sql`` which wraps *sqlglot*
in a no-throw, best-effort API that returns a typed SqlParseResult.

Dialect strategy
----------------
DataFusion (OpenObserve's SQL engine) is closest to ANSI SQL with a
few Postgres-flavoured extensions.  RFC-06a tested all 127 gold SQL
queries against 15 dialects — all pass at 100% with the ("", "postgres")
chain.  O2-specific functions (match_all, histogram, str_match_ignore_case,
cast_to_arr, approx_percentile_cont) are parsed as Anonymous nodes — safe.

Falls back gracefully when sqlglot is not installed (returns ok=False).
"""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from src.sql.models import SqlParseResult

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Ordered list of dialects to try.  We stop at the first success.
# "" == sqlglot's default (generic / ANSI-ish) dialect.
_DIALECT_CHAIN: tuple[str, ...] = ("", "postgres")

_BACKEND_NAME = "sqlglot"


def parse_sql(sql: str) -> SqlParseResult:
    """Parse a SQL string into an AST (best-effort, no-throw).

    Tries each dialect in _DIALECT_CHAIN and returns the first
    successful parse.  If all dialects fail, returns a result with
    ``ok=False`` and collected error messages.

    Returns ok=False (not raises) when sqlglot is unavailable.

    Args:
        sql: Raw SQL string (may contain a single or multiple statements).

    Returns:
        A SqlParseResult that is always safe to inspect.
    """
    if not sql or not sql.strip():
        return SqlParseResult(
            ok=False,
            errors=("Empty SQL string",),
            backend=_BACKEND_NAME,
        )

    try:
        import sqlglot  # noqa: F401 — presence check
    except ImportError:
        logger.debug("sqlglot not installed — AST parsing unavailable")
        return SqlParseResult(
            ok=False,
            errors=("sqlglot not installed",),
            backend=_BACKEND_NAME,
        )

    collected_errors: list[str] = []
    for dialect in _DIALECT_CHAIN:
        result = _try_parse(sql, dialect)
        if result is not None:
            return result
        collected_errors.append(f"dialect={dialect or 'default'}: parse failed")

    # All dialects failed — try one last best-effort WARN parse.
    return _warn_parse(sql, collected_errors)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _try_parse(sql: str, dialect: str) -> SqlParseResult | None:
    """Attempt a strict parse; return ``None`` on failure."""
    try:
        import sqlglot
        from sqlglot import expressions as exp
        from sqlglot.errors import ErrorLevel

        statements: list[exp.Expression | None] = sqlglot.parse(
            sql,
            dialect=dialect or None,
            error_level=ErrorLevel.RAISE,
        )
        valid: list[exp.Expression] = [s for s in statements if s is not None]
        if not valid:
            return None
        return SqlParseResult(ok=True, ast=valid, backend=_BACKEND_NAME)
    except Exception as exc:
        logger.debug("sqlglot strict parse failed (dialect=%s): %s", dialect or "default", exc)
        return None


def _warn_parse(sql: str, prior_errors: list[str]) -> SqlParseResult:
    """Best-effort parse using WARN error level.

    Returns a result with ``ok=False`` but a potentially usable AST,
    or fully failed if even WARN parse fails.
    """
    try:
        import sqlglot
        from sqlglot import expressions as exp
        from sqlglot.errors import ErrorLevel

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            statements = sqlglot.parse(sql, error_level=ErrorLevel.WARN)
        valid: list[exp.Expression] = [s for s in statements if s is not None]
        warn_msgs = [str(w.message) for w in caught]
        all_errors = tuple(prior_errors + warn_msgs)

        if valid:
            return SqlParseResult(ok=False, ast=valid, errors=all_errors, backend=_BACKEND_NAME)
        return SqlParseResult(ok=False, errors=all_errors, backend=_BACKEND_NAME)
    except Exception as exc:
        logger.warning("sqlglot WARN parse also failed: %s", exc)
        return SqlParseResult(
            ok=False,
            errors=(*prior_errors, f"warn-parse error: {exc}"),
            backend=_BACKEND_NAME,
        )
