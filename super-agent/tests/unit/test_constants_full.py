"""
Comprehensive unit tests for app.constants — all constants and codes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.constants import (
    APP_NAME,
    DEFAULT_USER_ID,
    JSONRPCCode,
    LLM_HTTP_ERROR_CODES,
    SKILL_TOOLS,
)


class TestAppName:

    def test_value(self):
        assert APP_NAME == "health_agent"

    def test_type(self):
        assert isinstance(APP_NAME, str)

    def test_not_empty(self):
        assert len(APP_NAME) > 0


class TestDefaultUserId:

    def test_value(self):
        assert DEFAULT_USER_ID == "admin"

    def test_type(self):
        assert isinstance(DEFAULT_USER_ID, str)


class TestLlmHttpErrorCodes:

    def test_is_tuple(self):
        assert isinstance(LLM_HTTP_ERROR_CODES, tuple)

    def test_contains_common_error_codes(self):
        for code in (400, 401, 403, 404, 429, 500, 502, 503):
            assert code in LLM_HTTP_ERROR_CODES

    def test_all_are_4xx_or_5xx(self):
        for code in LLM_HTTP_ERROR_CODES:
            assert 400 <= code <= 599, f"Unexpected code: {code}"

    def test_no_duplicates(self):
        assert len(LLM_HTTP_ERROR_CODES) == len(set(LLM_HTTP_ERROR_CODES))

    def test_all_are_integers(self):
        assert all(isinstance(c, int) for c in LLM_HTTP_ERROR_CODES)


class TestSkillTools:

    def test_is_frozenset(self):
        assert isinstance(SKILL_TOOLS, frozenset)

    def test_contains_expected_tools(self):
        expected = {"list_skills", "load_skill", "load_skill_resource", "run_skill_script"}
        assert expected.issubset(SKILL_TOOLS)

    def test_immutable(self):
        with pytest.raises(AttributeError):
            SKILL_TOOLS.add("new_tool")

    def test_membership_check(self):
        assert "list_skills" in SKILL_TOOLS
        assert "nonexistent_tool" not in SKILL_TOOLS


class TestJSONRPCCode:

    def test_parse_error(self):
        assert JSONRPCCode.PARSE_ERROR == -32700

    def test_invalid_request(self):
        assert JSONRPCCode.INVALID_REQUEST == -32600

    def test_method_not_found(self):
        assert JSONRPCCode.METHOD_NOT_FOUND == -32601

    def test_invalid_params(self):
        assert JSONRPCCode.INVALID_PARAMS == -32602

    def test_internal_error(self):
        assert JSONRPCCode.INTERNAL_ERROR == -32603

    def test_task_not_found(self):
        assert JSONRPCCode.TASK_NOT_FOUND == -32001

    def test_all_codes_are_negative(self):
        for attr in dir(JSONRPCCode):
            if attr.isupper() and not attr.startswith("_"):
                val = getattr(JSONRPCCode, attr)
                if isinstance(val, int):
                    assert val < 0, f"{attr} should be negative"

    def test_standard_codes_in_spec_range(self):
        """JSON-RPC spec reserves -32768 to -32000 for standard errors."""
        assert -32768 <= JSONRPCCode.PARSE_ERROR <= -32000
        assert -32768 <= JSONRPCCode.INVALID_REQUEST <= -32000
        assert -32768 <= JSONRPCCode.METHOD_NOT_FOUND <= -32000
        assert -32768 <= JSONRPCCode.INVALID_PARAMS <= -32000
        assert -32768 <= JSONRPCCode.INTERNAL_ERROR <= -32000


# Need pytest import for pytest.raises
import pytest
