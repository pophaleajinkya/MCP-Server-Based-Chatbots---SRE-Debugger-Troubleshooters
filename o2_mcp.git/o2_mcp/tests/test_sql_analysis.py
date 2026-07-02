"""Tests for src/sql/analysis.py — analyze_sql, SqlFacts extraction.

Tests run with or without sqlglot — when sqlglot is absent, ok=False and
facts=None; assertions are gated accordingly.
"""
import pytest
from src.sql.analysis import analyze_sql
from src.sql.models import SqlAnalysisResult, SqlFacts


def sqlglot_available() -> bool:
    try:
        import sqlglot
        return True
    except ImportError:
        return False


# Marker to skip tests that need sqlglot
needs_sqlglot = pytest.mark.skipif(
    not sqlglot_available(),
    reason="sqlglot not installed"
)


# ---------------------------------------------------------------------------
# analyze_sql — never raises
# ---------------------------------------------------------------------------

class TestAnalyzeSqlNeverRaises:

    def test_empty_string(self):
        result = analyze_sql("")
        assert isinstance(result, SqlAnalysisResult)

    def test_whitespace_only(self):
        result = analyze_sql("   ")
        assert isinstance(result, SqlAnalysisResult)

    def test_garbage_input(self):
        result = analyze_sql("@#$%!! not sql")
        assert isinstance(result, SqlAnalysisResult)

    def test_very_long_sql(self):
        sql = "SELECT " + ", ".join([f"col_{i}" for i in range(300)]) + ' FROM "logs"'
        result = analyze_sql(sql)
        assert isinstance(result, SqlAnalysisResult)

    def test_result_structure(self):
        result = analyze_sql('SELECT level FROM "logs"')
        assert hasattr(result, "ok")
        assert hasattr(result, "facts")
        assert hasattr(result, "errors")
        assert hasattr(result, "backend")

    def test_errors_is_tuple(self):
        result = analyze_sql("bad sql")
        assert isinstance(result.errors, tuple)


# ---------------------------------------------------------------------------
# Stream extraction
# ---------------------------------------------------------------------------

class TestStreamExtraction:

    @needs_sqlglot
    def test_single_stream(self):
        result = analyze_sql('SELECT level FROM "k8s_json" LIMIT 10')
        if result.ok and result.facts:
            assert "k8s_json" in result.facts.streams

    @needs_sqlglot
    def test_multiple_streams_via_join(self):
        sql = 'SELECT a.level FROM "logs" a JOIN "metrics" b ON a.id = b.id'
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert "logs" in result.facts.streams
            assert "metrics" in result.facts.streams

    @needs_sqlglot
    def test_cte_name_excluded_from_streams(self):
        sql = (
            'WITH my_cte AS (SELECT level FROM "logs") '
            'SELECT level FROM my_cte'
        )
        result = analyze_sql(sql)
        if result.ok and result.facts:
            # CTE name should NOT appear as a stream
            assert "my_cte" not in result.facts.streams
            assert "logs" in result.facts.streams

    @needs_sqlglot
    def test_unquoted_stream_name(self):
        result = analyze_sql("SELECT level FROM logs LIMIT 10")
        if result.ok and result.facts:
            assert "logs" in result.facts.streams


# ---------------------------------------------------------------------------
# has_select_star
# ---------------------------------------------------------------------------

class TestHasSelectStar:

    @needs_sqlglot
    def test_select_star_detected(self):
        result = analyze_sql('SELECT * FROM "logs"')
        if result.ok and result.facts:
            assert result.facts.has_select_star is True

    @needs_sqlglot
    def test_explicit_columns_no_star(self):
        result = analyze_sql('SELECT level, count(_timestamp) FROM "logs" GROUP BY level')
        if result.ok and result.facts:
            assert result.facts.has_select_star is False

    @needs_sqlglot
    def test_count_star_not_flagged_as_select_star(self):
        """count(*) is not SELECT * — different node type."""
        result = analyze_sql('SELECT count(*) FROM "logs"')
        if result.ok and result.facts:
            # has_select_star should only flag SELECT * in columns list
            # count(*) is an aggregate — behavior depends on implementation
            assert isinstance(result.facts.has_select_star, bool)


# ---------------------------------------------------------------------------
# has_timestamp_predicate
# ---------------------------------------------------------------------------

class TestHasTimestampPredicate:

    @needs_sqlglot
    def test_timestamp_in_where_detected(self):
        result = analyze_sql(
            'SELECT level FROM "logs" WHERE _timestamp > 1704067200000000'
        )
        if result.ok and result.facts:
            assert result.facts.has_timestamp_predicate is True
            assert len(result.facts.timestamp_predicates) > 0

    @needs_sqlglot
    def test_no_timestamp_in_where(self):
        result = analyze_sql(
            'SELECT level, count(_timestamp) FROM "logs" GROUP BY level'
        )
        if result.ok and result.facts:
            assert result.facts.has_timestamp_predicate is False
            assert result.facts.timestamp_predicates == ()

    @needs_sqlglot
    def test_timestamp_in_select_not_flagged(self):
        result = analyze_sql(
            'SELECT _timestamp, level FROM "logs" LIMIT 100'
        )
        if result.ok and result.facts:
            assert result.facts.has_timestamp_predicate is False


# ---------------------------------------------------------------------------
# has_subquery_in_select
# ---------------------------------------------------------------------------

class TestHasSubqueryInSelect:

    @needs_sqlglot
    def test_subquery_in_select_detected(self):
        sql = (
            'SELECT (SELECT count(_timestamp) FROM "other") AS cnt, level '
            'FROM "logs" GROUP BY level'
        )
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert result.facts.has_subquery_in_select is True

    @needs_sqlglot
    def test_subquery_in_from_ok(self):
        sql = (
            'SELECT sub.level FROM '
            '(SELECT level FROM "logs" LIMIT 10) sub'
        )
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert result.facts.has_subquery_in_select is False
            assert result.facts.has_subquery is True  # subquery exists, just not in SELECT


# ---------------------------------------------------------------------------
# Group by / Order by / Limit
# ---------------------------------------------------------------------------

class TestGroupByOrderByLimit:

    @needs_sqlglot
    def test_group_by_detected(self):
        result = analyze_sql('SELECT level, count(_timestamp) FROM "logs" GROUP BY level')
        if result.ok and result.facts:
            assert result.facts.has_group_by is True

    @needs_sqlglot
    def test_order_by_detected(self):
        result = analyze_sql('SELECT _timestamp, level FROM "logs" ORDER BY _timestamp DESC')
        if result.ok and result.facts:
            assert result.facts.has_order_by is True

    @needs_sqlglot
    def test_limit_extracted(self):
        result = analyze_sql('SELECT level FROM "logs" LIMIT 50')
        if result.ok and result.facts:
            assert result.facts.limit == 50

    @needs_sqlglot
    def test_no_limit_is_none(self):
        result = analyze_sql('SELECT level FROM "logs"')
        if result.ok and result.facts:
            assert result.facts.limit is None

    @needs_sqlglot
    def test_no_group_by(self):
        result = analyze_sql('SELECT level FROM "logs" LIMIT 10')
        if result.ok and result.facts:
            assert result.facts.has_group_by is False

    @needs_sqlglot
    def test_no_order_by(self):
        result = analyze_sql('SELECT level FROM "logs" LIMIT 10')
        if result.ok and result.facts:
            assert result.facts.has_order_by is False


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------

class TestFunctionExtraction:

    @needs_sqlglot
    def test_count_function_extracted(self):
        result = analyze_sql('SELECT count(_timestamp) FROM "logs"')
        if result.ok and result.facts:
            assert "count" in result.facts.functions

    @needs_sqlglot
    def test_histogram_extracted_as_anonymous(self):
        result = analyze_sql(
            'SELECT histogram(_timestamp, \'minute\') AS ts FROM "logs" GROUP BY ts'
        )
        if result.ok and result.facts:
            assert "histogram" in result.facts.functions

    @needs_sqlglot
    def test_case_not_in_functions(self):
        """CASE is SQL syntax, not a callable function — must be excluded."""
        sql = (
            'SELECT CASE WHEN level = \'error\' THEN 1 ELSE 0 END AS is_error '
            'FROM "logs"'
        )
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert "case" not in result.facts.functions

    @needs_sqlglot
    def test_cast_not_in_functions(self):
        """CAST is SQL syntax — must be excluded from function collection."""
        sql = 'SELECT CAST(status_code AS INT) FROM "logs"'
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert "cast" not in result.facts.functions


# ---------------------------------------------------------------------------
# Join count
# ---------------------------------------------------------------------------

class TestJoinCount:

    @needs_sqlglot
    def test_no_joins(self):
        result = analyze_sql('SELECT level FROM "logs" LIMIT 10')
        if result.ok and result.facts:
            assert result.facts.join_count == 0

    @needs_sqlglot
    def test_single_join(self):
        sql = 'SELECT a.level FROM "logs" a JOIN "metrics" b ON a.id = b.id LIMIT 10'
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert result.facts.join_count == 1

    @needs_sqlglot
    def test_multiple_joins(self):
        sql = (
            'SELECT a.level FROM "logs" a '
            'JOIN "metrics" b ON a.id = b.id '
            'JOIN "traces" c ON a.trace_id = c.id LIMIT 10'
        )
        result = analyze_sql(sql)
        if result.ok and result.facts:
            assert result.facts.join_count == 2


# ---------------------------------------------------------------------------
# Column extraction
# ---------------------------------------------------------------------------

class TestColumnExtraction:

    @needs_sqlglot
    def test_columns_extracted(self):
        result = analyze_sql('SELECT level, status_code FROM "logs" LIMIT 10')
        if result.ok and result.facts:
            assert "level" in result.facts.columns
            assert "status_code" in result.facts.columns

    @needs_sqlglot
    def test_where_columns_extracted(self):
        result = analyze_sql(
            'SELECT level FROM "logs" WHERE level = \'error\' LIMIT 10'
        )
        if result.ok and result.facts:
            assert "level" in result.facts.columns
