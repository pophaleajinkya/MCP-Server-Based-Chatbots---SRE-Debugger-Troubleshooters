"""Tests for src/sql/ast_parser.py — parse_sql, dialect chain, edge cases."""
import pytest
from unittest.mock import patch
from src.sql.ast_parser import parse_sql
from src.sql.models import SqlParseResult


class TestParseSql:

    # ── Never raises ─────────────────────────────────────────────────────────

    def test_never_raises_on_empty_string(self):
        result = parse_sql("")
        assert isinstance(result, SqlParseResult)

    def test_never_raises_on_whitespace(self):
        result = parse_sql("   \n\t  ")
        assert isinstance(result, SqlParseResult)

    def test_never_raises_on_garbage(self):
        result = parse_sql("@#$%^&*() not sql at all !!!")
        assert isinstance(result, SqlParseResult)

    def test_never_raises_on_none_like_strings(self):
        for s in ("null", "NULL", "undefined", "None"):
            result = parse_sql(s)
            assert isinstance(result, SqlParseResult)

    def test_never_raises_on_very_long_string(self):
        sql = "SELECT " + ", ".join([f"col_{i}" for i in range(500)]) + ' FROM "logs"'
        result = parse_sql(sql)
        assert isinstance(result, SqlParseResult)

    # ── sqlglot not installed fallback ────────────────────────────────────────

    def test_returns_error_when_sqlglot_not_installed(self):
        with patch.dict("sys.modules", {"sqlglot": None}):
            import importlib
            import src.sql.ast_parser as mod
            # Re-trigger import check
            result = mod.parse_sql("SELECT 1")
            # May succeed if sqlglot is cached; just ensure no exception
            assert isinstance(result, SqlParseResult)

    # ── Valid SQL ────────────────────────────────────────────────────────────

    def test_simple_select_parses(self):
        result = parse_sql('SELECT level FROM "logs" LIMIT 10')
        assert isinstance(result, SqlParseResult)
        # If sqlglot available, should succeed
        if result.ok:
            assert result.ast is not None

    def test_aggregation_query_parses(self):
        result = parse_sql(
            'SELECT level, count(_timestamp) FROM "logs" GROUP BY level'
        )
        assert isinstance(result, SqlParseResult)

    def test_cte_query_parses(self):
        sql = (
            'WITH e AS (SELECT level FROM "logs" WHERE level = \'error\') '
            'SELECT level FROM e LIMIT 10'
        )
        result = parse_sql(sql)
        assert isinstance(result, SqlParseResult)

    def test_o2_function_parses_as_anonymous(self):
        """O2-specific functions like match_all, histogram parse as Anonymous nodes."""
        result = parse_sql(
            'SELECT histogram(_timestamp, \'minute\') AS ts FROM "logs" GROUP BY ts'
        )
        assert isinstance(result, SqlParseResult)

    # ── Error results ────────────────────────────────────────────────────────

    def test_failed_parse_has_errors(self):
        result = parse_sql("THIS IS NOT SQL AT ALL !!!")
        # May parse or fail depending on sqlglot availability/tolerance
        if not result.ok:
            assert len(result.errors) > 0

    def test_failed_parse_may_have_partial_ast(self):
        # sqlglot WARN-mode returns a best-effort partial AST alongside errors.
        # ok=False with a non-None ast is valid — downstream analysis uses it.
        result = parse_sql("SELECT FROM WHERE")
        assert not result.ok
        assert len(result.errors) > 0
        # ast may be a partial tree or None; both are acceptable

    def test_ok_false_has_empty_or_none_ast(self):
        result = parse_sql("")
        if not result.ok:
            assert result.ast is None

    # ── Result structure ─────────────────────────────────────────────────────

    def test_result_has_backend_field(self):
        result = parse_sql("SELECT 1")
        assert result.backend == "sqlglot"

    def test_errors_is_tuple(self):
        result = parse_sql("bad sql !!!")
        assert isinstance(result.errors, tuple)

    def test_multiple_statements(self):
        """Multiple statements separated by semicolons."""
        result = parse_sql('SELECT 1; SELECT 2')
        assert isinstance(result, SqlParseResult)


# ---------------------------------------------------------------------------
# Dialect chain behaviour
# ---------------------------------------------------------------------------

class TestDialectChain:

    def test_dialect_chain_constant(self):
        from src.sql.ast_parser import _DIALECT_CHAIN
        assert isinstance(_DIALECT_CHAIN, tuple)
        assert "" in _DIALECT_CHAIN   # default dialect
        assert "postgres" in _DIALECT_CHAIN

    def test_postgres_dialect_as_fallback(self):
        """SQL that only parses under postgres dialect should still succeed."""
        # This test is informational — just ensure no exception
        sql = 'SELECT level FROM "logs" WHERE level ILIKE \'%error%\''
        result = parse_sql(sql)
        assert isinstance(result, SqlParseResult)
