"""Tests for src/tools/sql_function_registry.py

Focus: registry loading, function lookup, validation, negative/edge cases.
"""
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.tools.sql_function_registry import (
    check_sql_function,
    get_registry_functions,
    preload_registry,
    validate_sql_functions,
    _load_registry,
    _DEFAULT_REGISTRY_PATH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_registry_cache():
    """Clear module-level cache before each test to ensure isolation."""
    import src.tools.sql_function_registry as reg
    reg._registry_cache = None
    reg._registry_mtime = 0.0
    yield
    reg._registry_cache = None
    reg._registry_mtime = 0.0


@pytest.fixture
def sample_registry_file(tmp_path):
    """Minimal registry JSON for isolated tests."""
    data = {
        "functions": {
            "histogram": {
                "name": "histogram",
                "description": "Time-based histogram buckets.",
                "syntax": "histogram(_timestamp, 'interval')",
                "example": "SELECT histogram(_timestamp, '30 seconds') AS key FROM stream GROUP BY key",
                "category": "aggregate",
                "subcategory": "time_series",
                "source": "openobserve",
                "aliases": [],
                "keywords": ["time bucket", "time series"],
                "return_type": "any",
            },
            "match_all": {
                "name": "match_all",
                "description": "Full text search.",
                "syntax": "match_all('search_term')",
                "example": "",
                "category": "fulltext",
                "subcategory": "match",
                "source": "openobserve",
                "aliases": [],
                "keywords": ["search", "full text search"],
                "return_type": "any",
            },
            "approx_percentile_cont": {
                "name": "approx_percentile_cont",
                "description": "Approximate percentile.",
                "syntax": "approx_percentile_cont(expression, percentile)",
                "example": "SELECT approx_percentile_cont(latency, 0.99) FROM stream",
                "category": "aggregate",
                "subcategory": "approximate",
                "source": "datafusion",
                "aliases": [],
                "keywords": ["percentile", "p99"],
                "return_type": "float64",
            },
        }
    }
    path = tmp_path / "sql_functions.json"
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# _load_registry
# ---------------------------------------------------------------------------

class TestLoadRegistry:

    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        result = _load_registry(missing)
        assert result == {}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ this is not json }")
        result = _load_registry(bad)
        assert result == {}

    def test_returns_empty_dict_on_empty_file(self, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("")
        result = _load_registry(empty)
        assert result == {}

    def test_loads_functions_dict_format(self, sample_registry_file):
        result = _load_registry(sample_registry_file)
        assert "histogram" in result
        assert "match_all" in result
        assert "approx_percentile_cont" in result

    def test_normalizes_keys_to_lowercase(self, tmp_path):
        data = {"functions": {"UPPERCASE_FN": {"name": "UPPERCASE_FN"}}}
        path = tmp_path / "r.json"
        path.write_text(json.dumps(data))
        result = _load_registry(path)
        assert "uppercase_fn" in result
        assert "UPPERCASE_FN" not in result

    def test_caches_on_second_call(self, sample_registry_file):
        r1 = _load_registry(sample_registry_file)
        r2 = _load_registry(sample_registry_file)
        assert r1 is r2  # same cached object

    def test_reloads_on_mtime_change(self, tmp_path):
        data = {"functions": {"fn1": {"name": "fn1"}}}
        path = tmp_path / "r.json"
        path.write_text(json.dumps(data))

        r1 = _load_registry(path)
        assert "fn1" in r1

        import time
        time.sleep(0.01)
        data2 = {"functions": {"fn1": {"name": "fn1"}, "fn2": {"name": "fn2"}}}
        path.write_text(json.dumps(data2))
        # Force different mtime by touching
        path.touch()

        import src.tools.sql_function_registry as reg
        reg._registry_mtime = 0.0  # invalidate cache

        r2 = _load_registry(path)
        assert "fn2" in r2

    def test_handles_list_format(self, tmp_path):
        """Registry can also be a list of function dicts."""
        data = [{"name": "list_fn", "description": "test"}]
        path = tmp_path / "r.json"
        path.write_text(json.dumps(data))
        result = _load_registry(path)
        assert "list_fn" in result

    def test_skips_list_entries_without_name(self, tmp_path):
        data = [{"description": "no name here"}]
        path = tmp_path / "r.json"
        path.write_text(json.dumps(data))
        result = _load_registry(path)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# get_registry_functions
# ---------------------------------------------------------------------------

class TestGetRegistryFunctions:

    def test_returns_frozenset(self):
        result = get_registry_functions()
        assert isinstance(result, frozenset)

    def test_returns_lowercase_names(self):
        fns = get_registry_functions()
        for name in fns:
            assert name == name.lower(), f"Expected lowercase but got: {name}"

    def test_default_registry_has_functions(self):
        """Default sql_functions.json should be present and non-empty."""
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        fns = get_registry_functions()
        assert len(fns) > 0

    def test_known_o2_functions_present(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        fns = get_registry_functions()
        for expected in ("histogram", "match_all", "str_match_ignore_case", "cast_to_arr", "spath"):
            assert expected in fns, f"Expected O2 function '{expected}' in registry"


# ---------------------------------------------------------------------------
# check_sql_function
# ---------------------------------------------------------------------------

class TestCheckSqlFunction:

    def test_found_returns_json_with_found_true(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        result = json.loads(check_sql_function("histogram"))
        assert result["found"] is True
        assert result["name"] == "histogram"

    def test_found_returns_syntax(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        result = json.loads(check_sql_function("histogram"))
        assert "syntax" in result
        assert len(result["syntax"]) > 0

    def test_found_returns_examples_list(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        result = json.loads(check_sql_function("histogram"))
        assert "examples" in result
        assert isinstance(result["examples"], list)

    def test_case_insensitive_lookup(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        upper = json.loads(check_sql_function("HISTOGRAM"))
        lower = json.loads(check_sql_function("histogram"))
        assert upper["found"] == lower["found"]

    def test_not_found_returns_found_false(self):
        result = json.loads(check_sql_function("totally_fake_function_xyz"))
        assert result["found"] is False
        assert "message" in result

    def test_not_found_with_similar_suggestions(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        # "hist" should suggest "histogram"
        result = json.loads(check_sql_function("hist"))
        if result["found"] is False:
            assert "similar_functions" in result

    def test_empty_string_returns_error(self):
        result = json.loads(check_sql_function(""))
        assert result["found"] is False
        assert "message" in result

    def test_whitespace_only_returns_error(self):
        result = json.loads(check_sql_function("   "))
        assert result["found"] is False

    def test_returns_valid_json_string(self):
        """Return value must always be parseable JSON."""
        for name in ("histogram", "fake_fn", "", "  ", "COUNT", "spath"):
            result_str = check_sql_function(name)
            try:
                json.loads(result_str)
            except json.JSONDecodeError:
                pytest.fail(f"check_sql_function({name!r}) returned invalid JSON")

    def test_example_key_normalized_to_list(self):
        """Registry uses 'example' (singular) — must be returned as list."""
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        result = json.loads(check_sql_function("histogram"))
        assert isinstance(result.get("examples"), list)

    def test_source_field_returned(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        result = json.loads(check_sql_function("histogram"))
        assert "source" in result
        assert result["source"] in ("openobserve", "datafusion")

    def test_hallucinated_function_not_found(self):
        result = json.loads(check_sql_function("json_get_str"))
        assert result["found"] is False

    def test_another_hallucinated_function(self):
        result = json.loads(check_sql_function("extract_json"))
        assert result["found"] is False


# ---------------------------------------------------------------------------
# validate_sql_functions
# ---------------------------------------------------------------------------

class TestValidateSqlFunctions:

    def test_empty_sql_returns_error(self):
        result = json.loads(validate_sql_functions(""))
        assert result["all_valid"] is False
        assert "error" in result

    def test_whitespace_sql_returns_error(self):
        result = json.loads(validate_sql_functions("   "))
        assert result["all_valid"] is False

    def test_valid_query_with_known_functions(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT histogram(_timestamp, \'minute\'), count(_timestamp) FROM "logs" GROUP BY 1'
        result = json.loads(validate_sql_functions(sql))
        assert result["all_valid"] is True
        assert "invalid" in result
        assert len(result["invalid"]) == 0

    def test_hallucinated_function_flagged(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT extract_json(body, \'$.error\'), count(_timestamp) FROM "logs"'
        result = json.loads(validate_sql_functions(sql))
        assert result["all_valid"] is False
        invalid_names = [i["name"] for i in result["invalid"]]
        assert "extract_json" in invalid_names

    def test_returns_valid_json(self):
        for sql in ("", "SELECT 1", "SELECT fake_fn(x) FROM stream"):
            result_str = validate_sql_functions(sql)
            try:
                json.loads(result_str)
            except json.JSONDecodeError:
                pytest.fail(f"validate_sql_functions returned invalid JSON for: {sql!r}")

    def test_total_functions_checked_key_present(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT count(_timestamp) FROM "logs"'
        result = json.loads(validate_sql_functions(sql))
        assert "total_functions_checked" in result

    def test_standard_agg_functions_not_flagged(self):
        """count, sum, avg, min, max are always valid."""
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT count(_timestamp), sum(bytes), avg(latency), min(status), max(status) FROM "logs"'
        result = json.loads(validate_sql_functions(sql))
        invalid_names = [i["name"] for i in result.get("invalid", [])]
        for fn in ("count", "sum", "avg", "min", "max"):
            assert fn not in invalid_names

    def test_invalid_entry_has_name_and_suggestions(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT fake_xyz_fn(x) FROM "logs"'
        result = json.loads(validate_sql_functions(sql))
        if not result["all_valid"]:
            for invalid in result["invalid"]:
                assert "name" in invalid
                assert "suggestions" in invalid
                assert isinstance(invalid["suggestions"], list)

    def test_multiple_invalid_functions_all_reported(self):
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT fake_a(x), fake_b(y), fake_c(z) FROM "logs"'
        result = json.loads(validate_sql_functions(sql))
        invalid_names = [i["name"] for i in result.get("invalid", [])]
        # At least the three fake functions should appear
        assert len(invalid_names) >= 3

    def test_deduplicates_function_names(self):
        """Same function used twice should only be checked once."""
        if not _DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("sql_functions.json not present")
        sql = 'SELECT fake_fn(x), fake_fn(y) FROM "logs"'
        result = json.loads(validate_sql_functions(sql))
        invalid_names = [i["name"] for i in result.get("invalid", [])]
        assert invalid_names.count("fake_fn") == 1
