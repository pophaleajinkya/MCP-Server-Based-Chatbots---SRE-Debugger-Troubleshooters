"""Tests for src/tools/sql_error_classifier.py

Focus: negative cases, boundary conditions, pattern edge cases.
"""
import pytest
from src.tools.sql_error_classifier import (
    SqlErrorClassification,
    classify_sql_error,
    enrich_error_response,
)


# ---------------------------------------------------------------------------
# classify_sql_error — happy path
# ---------------------------------------------------------------------------

class TestClassifySqlError:

    def test_empty_string_returns_unknown(self):
        result = classify_sql_error("")
        assert result.error_type == "unknown"
        assert result.retry_allowed is True

    def test_none_equivalent_empty_string(self):
        # Function signature accepts str — test whitespace-only
        result = classify_sql_error("   ")
        # Whitespace doesn't match any pattern → fallback
        assert result.error_type == "unknown"

    # ── Auth errors ─────────────────────────────────────────────────────────

    def test_auth_401_no_retry(self):
        result = classify_sql_error("401 unauthorized")
        assert result.error_type == "auth_error"
        assert result.retry_allowed is False

    def test_auth_403_no_retry(self):
        result = classify_sql_error("403 forbidden access denied")
        assert result.error_type == "auth_error"
        assert result.retry_allowed is False

    def test_auth_token_expired(self):
        result = classify_sql_error("token expired please re-authenticate")
        assert result.error_type == "auth_error"
        assert result.retry_allowed is False

    def test_auth_fail_case_insensitive(self):
        result = classify_sql_error("AUTH FAIL: 401 Unauthorized")
        assert result.error_type == "auth_error"

    # ── Unknown column ───────────────────────────────────────────────────────

    def test_column_does_not_exist(self):
        result = classify_sql_error("column 'level' does not exist")
        assert result.error_type == "unknown_column"
        assert result.retry_allowed is True
        assert "get_stream_schema" in result.suggested_tools

    def test_column_not_found(self):
        result = classify_sql_error("column xyz not found in relation")
        assert result.error_type == "unknown_column"

    def test_no_field_named(self):
        result = classify_sql_error("no field named 'event_status'")
        assert result.error_type == "unknown_column"

    def test_field_does_not_exist(self):
        result = classify_sql_error("field 'status_code' does not exist")
        assert result.error_type == "unknown_column"

    def test_unknown_column_hint_mentions_schema(self):
        result = classify_sql_error("column foo does not exist")
        assert "schema" in result.correction_hint.lower() or "get_stream_schema" in result.correction_hint

    # ── Unknown function ─────────────────────────────────────────────────────

    def test_function_not_found(self):
        result = classify_sql_error("function 'extract_json' does not exist")
        assert result.error_type == "unknown_function"
        assert result.retry_allowed is True

    def test_no_function_named(self):
        result = classify_sql_error("no function named json_get_str")
        assert result.error_type == "unknown_function"

    def test_unknown_function_keyword(self):
        result = classify_sql_error("unknown function: strftime")
        assert result.error_type == "unknown_function"
        assert "validate_sql_functions" in result.suggested_tools

    # ── Syntax errors ────────────────────────────────────────────────────────

    def test_syntax_error(self):
        result = classify_sql_error("syntax error at or near 'FROM'")
        assert result.error_type == "syntax_error"
        assert result.retry_allowed is True

    def test_parse_error(self):
        result = classify_sql_error("parse error: unexpected token )")
        assert result.error_type == "syntax_error"

    def test_unexpected_token(self):
        result = classify_sql_error("unexpected token SELEC")
        assert result.error_type == "syntax_error"

    def test_invalid_sql(self):
        result = classify_sql_error("invalid sql: expected SELECT")
        assert result.error_type == "syntax_error"

    def test_syntax_error_suggests_validate_sql(self):
        result = classify_sql_error("syntax error near GROUP")
        assert "validate_sql" in result.suggested_tools

    # ── Policy violations ────────────────────────────────────────────────────

    def test_timestamp_predicate_message(self):
        result = classify_sql_error("no_timestamp_predicate violation detected")
        assert result.error_type == "policy_violation"

    def test_select_star_message(self):
        result = classify_sql_error("no_select_star: query uses SELECT *")
        assert result.error_type == "policy_violation"

    def test_count_star_message(self):
        result = classify_sql_error("count(*) not allowed, use count(_timestamp)")
        assert result.error_type == "policy_violation"

    # ── Stream not found ─────────────────────────────────────────────────────

    def test_table_not_found(self):
        result = classify_sql_error("table 'k8s_logs' not found")
        assert result.error_type == "stream_not_found"
        assert "list_streams" in result.suggested_tools

    def test_stream_not_found(self):
        result = classify_sql_error("stream 'wcnp_orders' does not exist")
        assert result.error_type == "stream_not_found"

    def test_no_such_table(self):
        result = classify_sql_error("no such table: my_stream")
        assert result.error_type == "stream_not_found"

    # ── Type mismatch ────────────────────────────────────────────────────────

    def test_type_mismatch(self):
        result = classify_sql_error("type mismatch: expected Int32 but got Utf8")
        assert result.error_type == "type_mismatch"
        assert result.retry_allowed is True

    def test_cannot_cast(self):
        result = classify_sql_error("cannot cast varchar to integer")
        assert result.error_type == "type_mismatch"

    def test_invalid_cast(self):
        result = classify_sql_error("invalid cast from Utf8 to Int64")
        assert result.error_type == "type_mismatch"

    # ── Timeout ──────────────────────────────────────────────────────────────

    def test_timeout(self):
        result = classify_sql_error("query timed out after 30 seconds")
        assert result.error_type == "timeout"
        assert "partition key" in result.correction_hint.lower() or "partition" in result.correction_hint

    def test_timed_out(self):
        result = classify_sql_error("execution timed out")
        assert result.error_type == "timeout"

    # ── Limit exceeded ───────────────────────────────────────────────────────

    def test_result_too_large(self):
        result = classify_sql_error("result is too large: 50000 rows")
        assert result.error_type == "limit_exceeded"

    def test_too_many_rows(self):
        result = classify_sql_error("too many rows returned")
        assert result.error_type == "limit_exceeded"

    # ── Empty result ─────────────────────────────────────────────────────────

    def test_empty_result(self):
        result = classify_sql_error("empty result: 0 rows returned")
        assert result.error_type == "empty_result"
        assert result.retry_allowed is True

    def test_no_results(self):
        result = classify_sql_error("no results found")
        assert result.error_type == "empty_result"

    # ── Fallback / unknown ───────────────────────────────────────────────────

    def test_unknown_error_falls_back(self):
        result = classify_sql_error("some completely unrecognized error message xyz123")
        assert result.error_type == "unknown"
        assert result.retry_allowed is True

    def test_unknown_suggests_validate_policy(self):
        result = classify_sql_error("obscure cluster error code 9999")
        assert "validate_sql_policy" in result.suggested_tools or "validate_sql" in result.suggested_tools

    # ── to_dict ──────────────────────────────────────────────────────────────

    def test_to_dict_has_required_keys(self):
        result = classify_sql_error("syntax error")
        d = result.to_dict()
        assert "error_type" in d
        assert "summary" in d
        assert "correction_hint" in d
        assert "retry_allowed" in d
        assert "suggested_tools" in d

    def test_to_dict_suggested_tools_is_list(self):
        result = classify_sql_error("syntax error")
        d = result.to_dict()
        assert isinstance(d["suggested_tools"], list)

    # ── Case insensitivity ───────────────────────────────────────────────────

    def test_uppercase_errors_match(self):
        result = classify_sql_error("COLUMN 'FOO' DOES NOT EXIST")
        assert result.error_type == "unknown_column"

    def test_mixed_case_auth(self):
        result = classify_sql_error("Token Expired: 401")
        assert result.error_type == "auth_error"

    # ── Priority — more specific before less specific ─────────────────────────

    def test_auth_wins_over_syntax_when_both_present(self):
        # Auth pattern checked first
        result = classify_sql_error("401 unauthorized: syntax error in token")
        assert result.error_type == "auth_error"


# ---------------------------------------------------------------------------
# enrich_error_response
# ---------------------------------------------------------------------------

class TestEnrichErrorResponse:

    def _base_response(self, error="column 'x' does not exist"):
        return {"success": False, "error": error, "sql": "SELECT x FROM logs"}

    def test_adds_classification_fields(self):
        resp = self._base_response()
        enriched = enrich_error_response(resp)
        assert "sql_error_type" in enriched
        assert "correction_hint" in enriched
        assert "retry_allowed" in enriched
        assert "suggested_tools" in enriched

    def test_adds_attempt_tracking(self):
        resp = self._base_response()
        enriched = enrich_error_response(resp, attempt=2, max_retries=5)
        assert enriched["attempt"] == 2
        assert enriched["max_retries"] == 5
        assert enriched["retries_remaining"] == 3

    def test_retry_allowed_false_at_last_attempt(self):
        resp = self._base_response("syntax error")
        enriched = enrich_error_response(resp, attempt=5, max_retries=5)
        assert enriched["retry_allowed"] is False
        assert enriched["retries_remaining"] == 0

    def test_retry_allowed_false_for_auth_error(self):
        resp = self._base_response("401 unauthorized")
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert enriched["retry_allowed"] is False

    def test_retry_allowed_false_for_auth_at_any_attempt(self):
        resp = self._base_response("403 forbidden")
        # Even on attempt 1 auth should not retry
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert enriched["retry_allowed"] is False

    def test_retry_instructions_present(self):
        resp = self._base_response()
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert "retry_instructions" in enriched
        assert len(enriched["retry_instructions"]) > 0

    def test_retry_instructions_include_attempt_number(self):
        resp = self._base_response()
        enriched = enrich_error_response(resp, attempt=3, max_retries=5)
        assert "3" in enriched["retry_instructions"]

    def test_mutates_input_dict(self):
        """enrich_error_response modifies in place and returns same dict."""
        resp = self._base_response()
        result = enrich_error_response(resp)
        assert result is resp  # same object

    def test_empty_error_message_uses_unknown(self):
        resp = {"success": False, "error": ""}
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert enriched["sql_error_type"] == "unknown"

    def test_retries_remaining_never_negative(self):
        resp = self._base_response()
        # attempt > max_retries edge case
        enriched = enrich_error_response(resp, attempt=10, max_retries=5)
        assert enriched["retries_remaining"] == 0

    def test_suggested_tools_is_list(self):
        resp = self._base_response()
        enriched = enrich_error_response(resp)
        assert isinstance(enriched["suggested_tools"], list)

    def test_attempt_1_has_correct_remaining(self):
        resp = self._base_response()
        enriched = enrich_error_response(resp, attempt=1, max_retries=5)
        assert enriched["retries_remaining"] == 4

    def test_preserves_existing_response_fields(self):
        resp = {"success": False, "error": "syntax error", "sql": "bad sql", "took_ms": 12.5}
        enriched = enrich_error_response(resp)
        assert enriched["sql"] == "bad sql"
        assert enriched["took_ms"] == 12.5
        assert enriched["success"] is False
