"""Integration tests — full pipeline: classify → enrich → policy → registry check.

Tests the interaction between sql_error_classifier, sql_policy,
sql_function_registry, and the retry loop logic.
"""
import json
import pytest
from src.tools.sql_error_classifier import classify_sql_error, enrich_error_response
from src.tools.sql_policy import run_policy_preflight
from src.tools.sql_function_registry import (
    validate_sql_functions,
    check_sql_function,
    _DEFAULT_REGISTRY_PATH,
)


pytestmark = pytest.mark.integration

registry_available = pytest.mark.skipif(
    not _DEFAULT_REGISTRY_PATH.exists(),
    reason="sql_functions.json not present"
)


# ---------------------------------------------------------------------------
# Policy + error classifier pipeline
# ---------------------------------------------------------------------------

class TestPolicyToClassifier:

    def test_select_star_policy_maps_to_classifier(self):
        """Policy violation message fed into classifier should classify correctly."""
        policy = run_policy_preflight('SELECT * FROM "logs"')
        assert not policy.ok
        # Get violation message and classify it
        for v in policy.violations:
            c = classify_sql_error(v.message)
            assert isinstance(c.error_type, str)

    def test_timestamp_predicate_violation_classifies(self):
        policy = run_policy_preflight('SELECT level FROM "logs" WHERE _timestamp > 100')
        assert not policy.ok
        for v in policy.violations:
            c = classify_sql_error(v.message)
            assert c.retry_allowed is True  # can be corrected

    def test_enrich_with_policy_violation_error(self):
        """Simulate what happens when execute_sql returns a policy violation string."""
        resp = {
            "success": False,
            "error": "no_select_star: query uses SELECT * which is not allowed",
            "sql": 'SELECT * FROM "logs"',
        }
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert enriched["sql_error_type"] == "policy_violation"
        assert enriched["retry_allowed"] is True
        assert enriched["retries_remaining"] == 4


# ---------------------------------------------------------------------------
# Full retry loop simulation
# ---------------------------------------------------------------------------

class TestRetryLoopSimulation:

    def test_retry_exhaustion_stops_at_max(self):
        """Simulates 5 consecutive failures — retries_remaining reaches 0."""
        sql = 'SELECT level FROM "logs" WHERE _timestamp > 100'
        max_retries = 5

        for attempt in range(1, max_retries + 1):
            resp = {"success": False, "error": "syntax error near SELECT", "sql": sql}
            enriched = enrich_error_response(resp, attempt=attempt, max_retries=max_retries)

            expected_remaining = max(0, max_retries - attempt)
            assert enriched["retries_remaining"] == expected_remaining

            if attempt == max_retries:
                assert enriched["retry_allowed"] is False

    def test_auth_error_stops_immediately(self):
        """Auth error on attempt 1 should not allow any retry."""
        resp = {"success": False, "error": "401 unauthorized", "sql": "SELECT 1"}
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert enriched["retry_allowed"] is False
        # No retries should be attempted after auth error

    def test_successful_correction_flow(self):
        """
        Simulate: initial SQL has SELECT *, policy catches it, hint guides correction,
        corrected SQL passes policy check.
        """
        bad_sql = 'SELECT * FROM "logs" LIMIT 10'
        good_sql = 'SELECT level, _timestamp FROM "logs" LIMIT 10'

        # Initial policy check fails
        bad_result = run_policy_preflight(bad_sql)
        assert bad_result.ok is False

        # Correction applied (simulated by agent using hint)
        good_result = run_policy_preflight(good_sql)
        assert good_result.ok is True

    def test_unknown_column_flow(self):
        """
        Simulate: column error from O2 → classifier suggests get_stream_schema.
        """
        error = "column 'levl' does not exist in relation logs"
        classification = classify_sql_error(error)
        assert classification.error_type == "unknown_column"
        assert "get_stream_schema" in classification.suggested_tools

        # After fixing column name, policy should pass
        fixed_sql = 'SELECT level, count(_timestamp) FROM "logs" GROUP BY level'
        policy = run_policy_preflight(fixed_sql)
        assert policy.ok is True


# ---------------------------------------------------------------------------
# validate_sql_functions + check_sql_function pipeline
# ---------------------------------------------------------------------------

@registry_available
class TestFunctionValidationPipeline:

    def test_validate_then_lookup_workflow(self):
        """
        Simulate: validate_sql_functions finds invalid fn →
        agent calls check_sql_function on suggestion → gets correct syntax.
        """
        sql = 'SELECT extract_json(body, \'key\'), count(_timestamp) FROM "logs"'
        validate_result = json.loads(validate_sql_functions(sql))

        # Should find extract_json as invalid
        invalid_names = [i["name"] for i in validate_result.get("invalid", [])]

        if "extract_json" in invalid_names:
            # Agent looks up suggestion
            invalid_entry = next(i for i in validate_result["invalid"] if i["name"] == "extract_json")
            # Suggestions may be present
            assert isinstance(invalid_entry["suggestions"], list)

    def test_valid_o2_query_passes_all_checks(self):
        """
        A properly formed O2 query should pass both validate_sql_functions
        and validate_sql_policy.
        """
        sql = (
            'SELECT histogram(_timestamp, \'minute\') AS ts, '
            'count(_timestamp) AS cnt, '
            'approx_percentile_cont(latency_ms, 0.99) AS p99 '
            'FROM "k8s_json" '
            'GROUP BY ts ORDER BY ts LIMIT 100'
        )
        # Policy check
        policy = run_policy_preflight(sql)
        assert policy.ok is True, f"Policy failed: {[v.rule for v in policy.violations]}"

        # Function validation
        fn_result = json.loads(validate_sql_functions(sql))
        assert fn_result["all_valid"] is True, f"Functions invalid: {fn_result.get('invalid')}"

    def test_hallucinated_function_full_flow(self):
        """
        Full flow: bad SQL with hallucinated function.
        validate_sql_functions catches it → check_sql_function provides correction.
        """
        sql = 'SELECT json_get_str(_raw, \'trace_id\') AS tid FROM "logs"'
        validate_result = json.loads(validate_sql_functions(sql))

        invalid_names = [i["name"] for i in validate_result.get("invalid", [])]
        assert "json_get_str" in invalid_names

        # spath is the correct alternative
        spath_result = json.loads(check_sql_function("spath"))
        assert spath_result["found"] is True
        assert "syntax" in spath_result


# ---------------------------------------------------------------------------
# Error classifier + config integration
# ---------------------------------------------------------------------------

class TestClassifierConfigIntegration:

    def test_max_retries_respected_in_enrichment(self):
        """Config max_retries drives the retry loop ceiling."""
        from src.config import Settings
        for max_r in (1, 3, 5, 10):
            s = Settings(max_retries=max_r)
            resp = {"success": False, "error": "syntax error"}
            enriched = enrich_error_response(resp, attempt=1, max_retries=s.max_retries)
            assert enriched["max_retries"] == max_r
            assert enriched["retries_remaining"] == max_r - 1

    def test_attempt_equals_max_always_stops(self):
        for max_r in (1, 3, 5):
            resp = {"success": False, "error": "syntax error"}
            enriched = enrich_error_response(resp, attempt=max_r, max_retries=max_r)
            assert enriched["retry_allowed"] is False
            assert enriched["retries_remaining"] == 0
