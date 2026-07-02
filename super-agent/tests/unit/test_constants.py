"""Unit tests for app/constants.py.

Covers:
  - APP_NAME string identity
  - DEFAULT_USER_ID string identity
  - LLM_HTTP_ERROR_CODES tuple contents
  - JSONRPCCode standard and application-specific codes
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── APP_NAME ──────────────────────────────────────────────────────────────────

class TestAppName:
    def test_app_name_is_string(self):
        from app.constants import APP_NAME
        assert isinstance(APP_NAME, str)

    def test_app_name_value(self):
        from app.constants import APP_NAME
        assert APP_NAME == "health_agent"

    def test_app_name_non_empty(self):
        from app.constants import APP_NAME
        assert len(APP_NAME) > 0


# ── DEFAULT_USER_ID ───────────────────────────────────────────────────────────

class TestDefaultUserId:
    def test_default_user_id_is_string(self):
        from app.constants import DEFAULT_USER_ID
        assert isinstance(DEFAULT_USER_ID, str)

    def test_default_user_id_value(self):
        from app.constants import DEFAULT_USER_ID
        assert DEFAULT_USER_ID == "admin"

    def test_default_user_id_non_empty(self):
        from app.constants import DEFAULT_USER_ID
        assert len(DEFAULT_USER_ID) > 0


# ── LLM_HTTP_ERROR_CODES ──────────────────────────────────────────────────────

class TestLLMHttpErrorCodes:
    def test_is_tuple(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert isinstance(LLM_HTTP_ERROR_CODES, tuple)

    def test_contains_400(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 400 in LLM_HTTP_ERROR_CODES

    def test_contains_401(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 401 in LLM_HTTP_ERROR_CODES

    def test_contains_403(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 403 in LLM_HTTP_ERROR_CODES

    def test_contains_404(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 404 in LLM_HTTP_ERROR_CODES

    def test_contains_429(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 429 in LLM_HTTP_ERROR_CODES

    def test_contains_500(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 500 in LLM_HTTP_ERROR_CODES

    def test_contains_502(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 502 in LLM_HTTP_ERROR_CODES

    def test_contains_503(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert 503 in LLM_HTTP_ERROR_CODES

    def test_all_elements_are_ints(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert all(isinstance(c, int) for c in LLM_HTTP_ERROR_CODES)

    def test_all_codes_are_4xx_or_5xx(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        for code in LLM_HTTP_ERROR_CODES:
            assert 400 <= code < 600, f"Unexpected status code {code}"

    def test_no_duplicate_codes(self):
        from app.constants import LLM_HTTP_ERROR_CODES
        assert len(LLM_HTTP_ERROR_CODES) == len(set(LLM_HTTP_ERROR_CODES))


# ── JSONRPCCode ───────────────────────────────────────────────────────────────

class TestJSONRPCCodeStandard:
    """Standard JSON-RPC 2.0 error codes."""

    def test_parse_error(self):
        from app.constants import JSONRPCCode
        assert JSONRPCCode.PARSE_ERROR == -32700

    def test_invalid_request(self):
        from app.constants import JSONRPCCode
        assert JSONRPCCode.INVALID_REQUEST == -32600

    def test_method_not_found(self):
        from app.constants import JSONRPCCode
        assert JSONRPCCode.METHOD_NOT_FOUND == -32601

    def test_invalid_params(self):
        from app.constants import JSONRPCCode
        assert JSONRPCCode.INVALID_PARAMS == -32602

    def test_internal_error(self):
        from app.constants import JSONRPCCode
        assert JSONRPCCode.INTERNAL_ERROR == -32603

    def test_all_standard_codes_are_int(self):
        from app.constants import JSONRPCCode
        for attr in ("PARSE_ERROR", "INVALID_REQUEST", "METHOD_NOT_FOUND",
                     "INVALID_PARAMS", "INTERNAL_ERROR"):
            assert isinstance(getattr(JSONRPCCode, attr), int)

    def test_standard_codes_are_in_reserved_range(self):
        """Standard codes must be in the -32768 to -32000 reserved range."""
        from app.constants import JSONRPCCode
        for attr in ("PARSE_ERROR", "INVALID_REQUEST", "METHOD_NOT_FOUND",
                     "INVALID_PARAMS", "INTERNAL_ERROR"):
            code = getattr(JSONRPCCode, attr)
            assert -32768 <= code <= -32000, (
                f"{attr}={code} is outside the JSON-RPC reserved range"
            )


class TestJSONRPCCodeApplicationSpecific:
    """Application-specific codes (start at -32000 per spec)."""

    def test_task_not_found(self):
        from app.constants import JSONRPCCode
        assert JSONRPCCode.TASK_NOT_FOUND == -32001

    def test_task_not_found_is_int(self):
        from app.constants import JSONRPCCode
        assert isinstance(JSONRPCCode.TASK_NOT_FOUND, int)

    def test_application_codes_start_at_minus_32000(self):
        """Application codes must be -32000 or below per spec."""
        from app.constants import JSONRPCCode
        assert JSONRPCCode.TASK_NOT_FOUND <= -32000


class TestJSONRPCCodeUniqueness:
    """All defined codes must be distinct."""

    def test_all_codes_unique(self):
        from app.constants import JSONRPCCode
        codes = [
            JSONRPCCode.PARSE_ERROR,
            JSONRPCCode.INVALID_REQUEST,
            JSONRPCCode.METHOD_NOT_FOUND,
            JSONRPCCode.INVALID_PARAMS,
            JSONRPCCode.INTERNAL_ERROR,
            JSONRPCCode.TASK_NOT_FOUND,
        ]
        assert len(codes) == len(set(codes)), "Duplicate JSON-RPC error codes detected"
