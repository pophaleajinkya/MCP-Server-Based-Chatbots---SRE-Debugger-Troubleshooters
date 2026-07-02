"""Backend-agnostic SQL AST models.

Ported from o2-ai-agent/src/sql/models.py (RFC-06).

These dataclasses represent the facts extracted from a SQL string.
Both the runtime policy checker and the validate_sql_policy tool consume them,
ensuring consistent semantics for function detection, policy checks,
and structural scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SqlFacts:
    """Backend-agnostic facts extracted from a parsed SQL AST.

    Every field is deterministically derived from the SQL structure
    and is safe to compare, hash, or serialise.
    """

    # Sources
    streams: frozenset[str] = field(default_factory=frozenset)
    """FROM / JOIN source tables (normalised to lowercase)."""

    columns: frozenset[str] = field(default_factory=frozenset)
    """Referenced column identifiers (best-effort, lowercase)."""

    functions: frozenset[str] = field(default_factory=frozenset)
    """Function calls found in the query (lowercase)."""

    # Shape flags
    has_select_star: bool = False
    has_timestamp_predicate: bool = False
    has_group_by: bool = False
    has_order_by: bool = False
    has_subquery: bool = False
    has_subquery_in_select: bool = False

    # Rendered detail lists
    timestamp_predicates: tuple[str, ...] = ()
    """Human-readable summaries of _timestamp predicates."""

    group_by_exprs: tuple[str, ...] = ()
    """Rendered GROUP BY expressions."""

    order_by_exprs: tuple[str, ...] = ()
    """Rendered ORDER BY expressions."""

    # Numeric stats
    limit: int | None = None
    join_count: int = 0


@dataclass(frozen=True, slots=True)
class SqlParseResult:
    """Low-level result of attempting to parse a SQL string into an AST.

    Consumers should check ``ok`` before accessing ``ast``.
    The ``ast`` handle is backend-specific and should not leak
    outside the ``src.sql`` package.
    """

    ok: bool
    """True if the SQL was parsed without errors."""

    ast: object | None = None
    """Opaque AST handle (backend-specific).  ``None`` on failure."""

    errors: tuple[str, ...] = ()
    """Parse-level error messages."""

    backend: str = "sqlglot"
    """Name of the parser backend that produced this result."""


@dataclass(frozen=True, slots=True)
class SqlAnalysisResult:
    """High-level analysis result containing extracted SQL facts.

    This is the primary public API surface consumed by the runtime
    policy checker and the MCP tool layer.
    """

    ok: bool
    """True if both parsing and analysis succeeded."""

    facts: SqlFacts | None = None
    """Extracted facts.  ``None`` when ``ok`` is ``False``."""

    errors: tuple[str, ...] = ()
    """Parse or analysis error messages."""

    backend: str = "sqlglot"
    """Name of the parser backend used."""
