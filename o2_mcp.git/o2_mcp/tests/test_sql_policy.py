"""Tests for src/tools/sql_policy.py

Focus: PolicyResult, PolicyViolation, AST path, regex fallback, negative cases.
"""
import pytest
from src.tools.sql_policy import (
    PolicyResult,
    PolicyViolation,
    run_policy_preflight,
)


# ---------------------------------------------------------------------------
# PolicyViolation
# ---------------------------------------------------------------------------

class TestPolicyViolation:

    def test_fields_accessible(self):
        v = PolicyViolation(rule="no_select_star", message="SELECT * used", hint="Use explicit columns")
        assert v.rule == "no_select_star"
        assert v.message == "SELECT * used"
        assert v.hint == "Use explicit columns"


# ---------------------------------------------------------------------------
# PolicyResult
# ---------------------------------------------------------------------------

class TestPolicyResult:

    def test_default_is_ok(self):
        r = PolicyResult()
        assert r.ok is True
        assert r.violations == []

    def test_to_dict_ok_case(self):
        r = PolicyResult(ok=True, violations=[])
        d = r.to_dict()
        assert d["ok"] is True
        assert d["violations"] == []

    def test_to_dict_violation_case(self):
        v = PolicyViolation(rule="no_select_star", message="msg", hint="hint")
        r = PolicyResult(ok=False, violations=[v])
        d = r.to_dict()
        assert d["ok"] is False
        assert len(d["violations"]) == 1
        assert d["violations"][0]["rule"] == "no_select_star"

    def test_to_dict_includes_used_ast(self):
        r = PolicyResult(ok=True, used_ast=True)
        d = r.to_dict()
        assert "used_ast" in d


# ---------------------------------------------------------------------------
# run_policy_preflight — empty / null inputs
# ---------------------------------------------------------------------------

class TestPolicyPreflightEmpty:

    def test_empty_string_fails(self):
        result = run_policy_preflight("")
        assert result.ok is False

    def test_whitespace_only_fails(self):
        result = run_policy_preflight("   ")
        assert result.ok is False

    def test_none_equivalent_empty(self):
        result = run_policy_preflight("")
        assert isinstance(result, PolicyResult)


# ---------------------------------------------------------------------------
# run_policy_preflight — SELECT * violations
# ---------------------------------------------------------------------------

class TestPolicySelectStar:

    def test_select_star_fails(self):
        result = run_policy_preflight('SELECT * FROM "logs"')
        assert result.ok is False
        rules = [v.rule for v in result.violations]
        assert "no_select_star" in rules

    def test_select_star_with_where_fails(self):
        result = run_policy_preflight('SELECT * FROM "logs" WHERE level = \'error\'')
        assert result.ok is False

    def test_select_star_mixed_case_fails(self):
        result = run_policy_preflight('select * from "logs"')
        assert result.ok is False

    def test_explicit_columns_passes(self):
        result = run_policy_preflight(
            'SELECT level, count(_timestamp) FROM "logs" GROUP BY level'
        )
        rules = [v.rule for v in result.violations]
        assert "no_select_star" not in rules


# ---------------------------------------------------------------------------
# run_policy_preflight — _timestamp in WHERE
# ---------------------------------------------------------------------------

class TestPolicyTimestampPredicate:

    def test_timestamp_in_where_fails(self):
        result = run_policy_preflight(
            'SELECT level FROM "logs" WHERE _timestamp > 1704067200000000'
        )
        assert result.ok is False
        rules = [v.rule for v in result.violations]
        assert "no_timestamp_predicate" in rules

    def test_timestamp_equality_in_where_fails(self):
        result = run_policy_preflight(
            'SELECT level FROM "logs" WHERE _timestamp = 1704067200000000'
        )
        assert result.ok is False

    def test_timestamp_between_in_where_fails(self):
        result = run_policy_preflight(
            'SELECT level FROM "logs" WHERE _timestamp BETWEEN 100 AND 200'
        )
        assert result.ok is False

    def test_no_timestamp_in_where_passes(self):
        result = run_policy_preflight(
            'SELECT level, count(_timestamp) FROM "logs" GROUP BY level LIMIT 100'
        )
        rules = [v.rule for v in result.violations]
        assert "no_timestamp_predicate" not in rules

    def test_timestamp_in_select_is_ok(self):
        """_timestamp in SELECT clause is allowed."""
        result = run_policy_preflight(
            'SELECT _timestamp, level FROM "logs" LIMIT 100'
        )
        rules = [v.rule for v in result.violations]
        assert "no_timestamp_predicate" not in rules

    def test_timestamp_in_group_by_is_ok(self):
        result = run_policy_preflight(
            'SELECT histogram(_timestamp, \'minute\') AS ts, count(_timestamp) FROM "logs" GROUP BY ts'
        )
        rules = [v.rule for v in result.violations]
        assert "no_timestamp_predicate" not in rules


# ---------------------------------------------------------------------------
# run_policy_preflight — subquery in SELECT
# ---------------------------------------------------------------------------

class TestPolicySubqueryInSelect:

    def test_subquery_in_select_fails(self):
        sql = (
            'SELECT (SELECT count(_timestamp) FROM "other") AS cnt, level '
            'FROM "logs" GROUP BY level'
        )
        result = run_policy_preflight(sql)
        rules = [v.rule for v in result.violations]
        assert "no_subquery_in_select" in rules

    def test_subquery_in_from_is_ok(self):
        sql = (
            'SELECT sub.level, sub.cnt FROM '
            '(SELECT level, count(_timestamp) AS cnt FROM "logs" GROUP BY level) sub'
        )
        result = run_policy_preflight(sql)
        rules = [v.rule for v in result.violations]
        assert "no_subquery_in_select" not in rules

    def test_cte_is_ok(self):
        sql = (
            'WITH counts AS (SELECT level, count(_timestamp) AS cnt FROM "logs" GROUP BY level) '
            'SELECT level, cnt FROM counts ORDER BY cnt DESC LIMIT 10'
        )
        result = run_policy_preflight(sql)
        rules = [v.rule for v in result.violations]
        assert "no_subquery_in_select" not in rules


# ---------------------------------------------------------------------------
# run_policy_preflight — multiple violations
# ---------------------------------------------------------------------------

class TestPolicyMultipleViolations:

    def test_select_star_and_timestamp_both_reported(self):
        sql = 'SELECT * FROM "logs" WHERE _timestamp > 100'
        result = run_policy_preflight(sql)
        assert result.ok is False
        rules = [v.rule for v in result.violations]
        assert "no_select_star" in rules
        assert "no_timestamp_predicate" in rules

    def test_violation_count_matches(self):
        sql = 'SELECT * FROM "logs" WHERE _timestamp > 100'
        result = run_policy_preflight(sql)
        assert len(result.violations) >= 2


# ---------------------------------------------------------------------------
# run_policy_preflight — clean queries
# ---------------------------------------------------------------------------

class TestPolicyCleanQueries:

    def test_simple_aggregation_passes(self):
        sql = (
            'SELECT level, count(_timestamp) AS cnt '
            'FROM "logs" '
            'GROUP BY level '
            'ORDER BY cnt DESC LIMIT 20'
        )
        result = run_policy_preflight(sql)
        assert result.ok is True
        assert result.violations == []

    def test_histogram_query_passes(self):
        sql = (
            'SELECT histogram(_timestamp, \'minute\') AS ts, '
            'count(_timestamp) AS cnt '
            'FROM "logs" '
            'GROUP BY ts ORDER BY ts'
        )
        result = run_policy_preflight(sql)
        assert result.ok is True

    def test_cte_query_passes(self):
        sql = (
            'WITH errors AS ('
            '  SELECT level, count(_timestamp) AS cnt '
            '  FROM "logs" WHERE level = \'error\' GROUP BY level'
            ') SELECT level, cnt FROM errors LIMIT 10'
        )
        result = run_policy_preflight(sql)
        assert result.ok is True

    def test_window_function_passes(self):
        sql = (
            'SELECT level, count(_timestamp) AS cnt, '
            'rank() OVER (ORDER BY count(_timestamp) DESC) AS rnk '
            'FROM "logs" GROUP BY level LIMIT 10'
        )
        result = run_policy_preflight(sql)
        # Window function is valid — should not trigger any policy violation
        rules = [v.rule for v in result.violations]
        assert "no_select_star" not in rules
        assert "no_timestamp_predicate" not in rules

    def test_filter_where_clause_passes(self):
        sql = (
            'SELECT count(_timestamp) FILTER (WHERE level = \'error\') AS errors, '
            'count(_timestamp) AS total FROM "logs"'
        )
        result = run_policy_preflight(sql)
        rules = [v.rule for v in result.violations]
        assert "no_timestamp_predicate" not in rules

    def test_non_select_query_fails(self):
        """Only SELECT (and WITH/CTE) queries are allowed."""
        for sql in ("DROP TABLE logs", "DELETE FROM logs", "INSERT INTO logs VALUES (1)"):
            result = run_policy_preflight(sql)
            assert result.ok is False, f"Expected {sql!r} to fail policy"
            rules = [v.rule for v in result.violations]
            assert "non_select_query" in rules

    def test_always_returns_policy_result(self):
        """run_policy_preflight must never raise — always returns PolicyResult."""
        for sql in ("", "   ", "garbage input @#$", "SELECT * FROM x WHERE _timestamp > 0"):
            result = run_policy_preflight(sql)
            assert isinstance(result, PolicyResult)
