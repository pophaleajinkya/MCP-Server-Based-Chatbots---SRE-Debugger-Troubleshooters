"""Tests for src/sql/models.py — SqlFacts, SqlParseResult, SqlAnalysisResult."""
import pytest
from src.sql.models import SqlFacts, SqlParseResult, SqlAnalysisResult


class TestSqlFacts:

    def test_default_values(self):
        f = SqlFacts(streams=frozenset(), columns=frozenset(), functions=frozenset())
        assert f.has_select_star is False
        assert f.has_timestamp_predicate is False
        assert f.has_group_by is False
        assert f.has_order_by is False
        assert f.has_subquery is False
        assert f.has_subquery_in_select is False
        assert f.timestamp_predicates == ()
        assert f.group_by_exprs == ()
        assert f.order_by_exprs == ()
        assert f.limit is None
        assert f.join_count == 0

    def test_frozen_cannot_mutate(self):
        f = SqlFacts(streams=frozenset(), columns=frozenset(), functions=frozenset())
        with pytest.raises((AttributeError, TypeError)):
            f.has_select_star = True  # type: ignore

    def test_equality(self):
        f1 = SqlFacts(streams=frozenset(["logs"]), columns=frozenset(), functions=frozenset())
        f2 = SqlFacts(streams=frozenset(["logs"]), columns=frozenset(), functions=frozenset())
        assert f1 == f2

    def test_inequality_on_streams(self):
        f1 = SqlFacts(streams=frozenset(["logs"]), columns=frozenset(), functions=frozenset())
        f2 = SqlFacts(streams=frozenset(["metrics"]), columns=frozenset(), functions=frozenset())
        assert f1 != f2

    def test_hashable(self):
        f = SqlFacts(streams=frozenset(), columns=frozenset(), functions=frozenset())
        s = {f}  # frozenset requires hashability
        assert f in s

    def test_with_data(self):
        f = SqlFacts(
            streams=frozenset(["logs", "metrics"]),
            columns=frozenset(["level", "_timestamp"]),
            functions=frozenset(["count", "histogram"]),
            has_select_star=False,
            has_timestamp_predicate=True,
            has_group_by=True,
            limit=100,
            join_count=1,
        )
        assert "logs" in f.streams
        assert "histogram" in f.functions
        assert f.limit == 100
        assert f.join_count == 1


class TestSqlParseResult:

    def test_ok_result(self):
        r = SqlParseResult(ok=True, ast=object())
        assert r.ok is True
        assert r.ast is not None
        assert r.errors == ()
        assert r.backend == "sqlglot"

    def test_failed_result(self):
        r = SqlParseResult(ok=False, errors=("parse error",))
        assert r.ok is False
        assert len(r.errors) == 1
        assert "parse error" in r.errors

    def test_frozen(self):
        r = SqlParseResult(ok=True)
        with pytest.raises((AttributeError, TypeError)):
            r.ok = False  # type: ignore

    def test_multiple_errors(self):
        r = SqlParseResult(ok=False, errors=("err1", "err2", "err3"))
        assert len(r.errors) == 3


class TestSqlAnalysisResult:

    def test_ok_result_with_facts(self):
        facts = SqlFacts(streams=frozenset(["logs"]), columns=frozenset(), functions=frozenset())
        r = SqlAnalysisResult(ok=True, facts=facts)
        assert r.ok is True
        assert r.facts is not None
        assert r.errors == ()

    def test_failed_result_no_facts(self):
        r = SqlAnalysisResult(ok=False, errors=("sqlglot not installed",))
        assert r.ok is False
        assert r.facts is None
        assert len(r.errors) == 1

    def test_frozen(self):
        r = SqlAnalysisResult(ok=True)
        with pytest.raises((AttributeError, TypeError)):
            r.ok = False  # type: ignore

    def test_backend_default(self):
        r = SqlAnalysisResult(ok=True)
        assert r.backend == "sqlglot"
