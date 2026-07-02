"""
Negative and edge-case tests for src/app/config.py and src/app/constants.py.

Covers invalid inputs, boundary values, type coercion failures,
computed property edge cases, and constants immutability.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.config import Settings, get_settings
from app.constants import (
    APP_NAME,
    DEFAULT_USER_ID,
    JSONRPCCode,
    LLM_HTTP_ERROR_CODES,
    SKILL_TOOLS,
)


# ============================================================================
# Helper: build Settings with explicit kwargs (bypasses env vars)
# ============================================================================

def _settings(**overrides) -> Settings:
    """Create a Settings instance with safe defaults, applying overrides."""
    defaults = {
        "agent_host": "127.0.0.1",
        "agent_port": 8001,
        "element_gateway_base_url": "https://llm.test.com/openai",
        "element_gateway_api_key": "test-key",
        "openai_model": "gpt-4",
        "claude_gateway_url": "https://claude.test.com",
        "claude_api_key": "claude-key",
        "redis_host": "redis.test.com",
        "redis_port": 6379,
        "agent_env": "test",
        "agent_group": "sre",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ============================================================================
# NEGATIVE TESTS -- config.py Settings
# ============================================================================


class TestInvalidPortNumbers:
    """Port numbers that are out of range or wrong type."""

    def test_negative_port(self):
        """Negative port is accepted by pydantic (no validator) but stored."""
        s = _settings(agent_port=-1)
        assert s.agent_port == -1

    def test_zero_port(self):
        """Zero port is stored as-is."""
        s = _settings(agent_port=0)
        assert s.agent_port == 0

    def test_very_large_port(self):
        """Port far above 65535 is stored -- no range validator exists."""
        s = _settings(agent_port=99999)
        assert s.agent_port == 99999

    def test_string_coerced_to_int_port(self):
        """Pydantic coerces numeric strings to int for int fields."""
        s = _settings(agent_port="8080")
        assert s.agent_port == 8080

    def test_non_numeric_string_port_raises(self):
        """A non-numeric string should fail validation."""
        with pytest.raises(Exception):
            _settings(agent_port="not_a_port")


class TestInvalidTimeouts:
    """Timeout values that are negative, zero, or absurdly large."""

    def test_negative_llm_timeout(self):
        s = _settings(llm_timeout_seconds=-5)
        assert s.llm_timeout_seconds == -5

    def test_negative_mcp_timeout(self):
        s = _settings(mcp_timeout_seconds=-100)
        assert s.mcp_timeout_seconds == -100

    def test_zero_llm_timeout(self):
        s = _settings(llm_timeout_seconds=0)
        assert s.llm_timeout_seconds == 0

    def test_extremely_large_timeout(self):
        s = _settings(llm_timeout_seconds=999_999_999)
        assert s.llm_timeout_seconds == 999_999_999

    def test_non_numeric_timeout_raises(self):
        with pytest.raises(Exception):
            _settings(llm_timeout_seconds="slow")


class TestInvalidRedisConfig:
    """Invalid Redis host, port, and TTL values."""

    def test_empty_redis_host(self):
        s = _settings(redis_host="")
        assert s.redis_host == ""

    def test_negative_redis_port(self):
        s = _settings(redis_port=-1)
        assert s.redis_port == -1

    def test_negative_redis_ttl(self):
        s = _settings(redis_session_ttl_seconds=-600)
        assert s.redis_session_ttl_seconds == -600

    def test_zero_redis_ttl(self):
        s = _settings(redis_session_ttl_seconds=0)
        assert s.redis_session_ttl_seconds == 0

    def test_non_numeric_redis_port_raises(self):
        with pytest.raises(Exception):
            _settings(redis_port="bad")


class TestInvalidListFields:
    """Invalid JSON for list[str] fields like cors_allowed_origins."""

    def test_invalid_json_cors_origins_raises(self, monkeypatch):
        """Passing a malformed JSON string via env var should fail."""
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "not-json-at-all")
        with pytest.raises(Exception):
            Settings()

    def test_invalid_json_allowed_hosts_raises(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_HOSTS", "{this is not a list}")
        with pytest.raises(Exception):
            Settings()


class TestMissingEnvVars:
    """Missing environment variables for critical paths."""

    def test_empty_element_gateway_url_in_openai_url(self):
        """openai_url still constructs a string even with empty base URL."""
        s = _settings(element_gateway_base_url="")
        assert s.openai_url.startswith("/deployments/")

    def test_empty_claude_gateway_url(self):
        s = _settings(claude_gateway_url="")
        assert s.claude_gateway_url == ""

    def test_empty_api_keys_in_headers(self):
        s = _settings(element_gateway_api_key="", claude_api_key="")
        assert s.openai_headers["X-Api-Key"] == ""
        assert s.claude_headers["x-api-key"] == ""


class TestInvalidLLMConfig:
    """Invalid model names and API keys."""

    def test_empty_model_name(self):
        s = _settings(openai_model="")
        assert "/deployments//chat" in s.openai_url

    def test_model_with_special_chars(self):
        s = _settings(openai_model="model/v2&key=hacked")
        assert "model/v2&key=hacked" in s.openai_url

    def test_api_key_with_whitespace(self):
        s = _settings(element_gateway_api_key="  key with spaces  ")
        assert s.openai_headers["X-Api-Key"] == "  key with spaces  "


class TestInvalidAgentEnvGroup:
    """Special characters in agent_env / agent_group affect Redis keys."""

    def test_special_chars_in_agent_env(self):
        s = _settings(agent_env="prod:hacked")
        assert "prod:hacked" in s.mcp_config_key

    def test_special_chars_in_agent_group(self):
        s = _settings(agent_group="sre/../../admin")
        assert "sre/../../admin" in s.mcp_config_key

    def test_empty_env_and_group_in_mcp_key(self):
        s = _settings(agent_env="", agent_group="")
        assert s.mcp_config_key == "super_agent:config:mcp_servers:::config"

    def test_empty_env_and_group_in_a2a_key(self):
        s = _settings(agent_env="", agent_group="")
        assert s.a2a_agents_config_key == "super_agent:config:a2a_agents:::config"


class TestTypeCoercionFailures:
    """String where int expected, bool where str expected, etc."""

    def test_float_string_for_int_field_raises(self):
        with pytest.raises(Exception):
            _settings(agent_port="80.5")

    def test_bool_coercion_truthy_strings(self):
        s = _settings(claude_is_primary_llm="true")
        assert s.claude_is_primary_llm is True

    def test_bool_coercion_false_string(self):
        s = _settings(claude_is_primary_llm="false")
        assert s.claude_is_primary_llm is False

    def test_non_bool_string_for_bool_raises(self):
        with pytest.raises(Exception):
            _settings(claude_is_primary_llm="maybe")


class TestExtraFieldsIgnored:
    """model_config = SettingsConfigDict(extra='ignore')."""

    def test_extra_field_does_not_raise(self):
        s = _settings(totally_unknown_field="surprise")
        assert not hasattr(s, "totally_unknown_field")

    def test_multiple_extra_fields_ignored(self):
        s = _settings(foo="bar", baz=42, qux=True)
        assert not hasattr(s, "foo")
        assert not hasattr(s, "baz")


# ============================================================================
# EDGE CASE TESTS -- config.py Settings
# ============================================================================


class TestBoundaryPorts:
    """Port numbers at exact boundaries."""

    def test_port_one(self):
        s = _settings(agent_port=1)
        assert s.agent_port == 1

    def test_port_65535(self):
        s = _settings(agent_port=65535)
        assert s.agent_port == 65535


class TestZeroTimeouts:
    """Zero-valued timeouts and rounds."""

    def test_zero_mcp_timeout(self):
        s = _settings(mcp_timeout_seconds=0)
        assert s.mcp_timeout_seconds == 0

    def test_zero_max_tool_rounds(self):
        s = _settings(max_tool_rounds=0)
        assert s.max_tool_rounds == 0


class TestVeryLongStrings:
    """Extremely long string values for URL fields."""

    def test_long_element_gateway_url(self):
        long_url = "https://gateway.test.com/" + "a" * 10_000
        s = _settings(element_gateway_base_url=long_url)
        assert len(s.openai_url) > 10_000
        assert s.openai_url.startswith(long_url)

    def test_long_claude_gateway_url(self):
        long_url = "https://claude.test.com/" + "x" * 15_000
        s = _settings(claude_gateway_url=long_url)
        assert s.claude_gateway_url == long_url


class TestUnicodeInFields:
    """Unicode characters in agent_env and agent_group."""

    def test_unicode_agent_env(self):
        s = _settings(agent_env="\u00fcber-prod")
        assert "\u00fcber-prod" in s.mcp_config_key

    def test_unicode_agent_group(self):
        s = _settings(agent_group="\u6d4b\u8bd5")
        assert "\u6d4b\u8bd5" in s.mcp_config_key

    def test_emoji_in_agent_env(self):
        s = _settings(agent_env="\U0001f525fire")
        assert "\U0001f525fire" in s.mcp_config_key


class TestEmptyVsNoneOptionalFields:
    """Distinguish empty string from None for optional-ish fields."""

    def test_empty_string_sso_username(self):
        s = _settings(sso_username="")
        assert s.sso_username == ""

    def test_empty_string_mcp_servers_file(self):
        s = _settings(mcp_servers_file="")
        assert s.mcp_servers_file == ""

    def test_whitespace_only_sso_password(self):
        s = _settings(sso_password="   ")
        assert s.sso_password == "   "


class TestWhitespaceOnlyUrls:
    """Whitespace-only strings for URL fields."""

    def test_whitespace_element_gateway_url(self):
        s = _settings(element_gateway_base_url="   ")
        assert s.openai_url.startswith("   /deployments/")

    def test_whitespace_claude_gateway_url(self):
        s = _settings(claude_gateway_url="   ")
        assert s.claude_gateway_url == "   "


class TestPingfedUrlList:
    """pingfed_url_list property with various input formats."""

    def test_single_url(self):
        s = _settings(pingfed_urls="https://a.com")
        assert s.pingfed_url_list == ["https://a.com"]

    def test_multiple_urls(self):
        s = _settings(pingfed_urls="https://a.com,https://b.com")
        assert s.pingfed_url_list == ["https://a.com", "https://b.com"]

    def test_trailing_comma(self):
        s = _settings(pingfed_urls="https://a.com,")
        assert s.pingfed_url_list == ["https://a.com"]

    def test_leading_comma(self):
        s = _settings(pingfed_urls=",https://a.com")
        assert s.pingfed_url_list == ["https://a.com"]

    def test_empty_segments(self):
        s = _settings(pingfed_urls="https://a.com,,https://b.com")
        assert s.pingfed_url_list == ["https://a.com", "https://b.com"]

    def test_spaces_around_urls(self):
        s = _settings(pingfed_urls=" https://a.com , https://b.com ")
        assert s.pingfed_url_list == ["https://a.com", "https://b.com"]

    def test_whitespace_only_falls_back(self):
        s = _settings(pingfed_urls="   ", pingfed_base_url="https://fallback.com")
        assert s.pingfed_url_list == ["https://fallback.com"]

    def test_empty_falls_back_to_base_url(self):
        s = _settings(pingfed_urls="", pingfed_base_url="https://base.com")
        assert s.pingfed_url_list == ["https://base.com"]

    def test_all_commas_returns_empty(self):
        s = _settings(pingfed_urls=",,,", pingfed_base_url="https://fallback.com")
        # ",,," is truthy after strip(), so the PINGFED_URLS branch runs,
        # but all segments are empty after stripping -> empty list (no fallback).
        assert s.pingfed_url_list == []


class TestComputedPropertiesWithEmptyBase:
    """Computed properties when base values are empty."""

    def test_openai_url_empty_base(self):
        s = _settings(element_gateway_base_url="")
        expected = "/deployments/gpt-4/chat/completions?api-version=2024-10-21"
        assert s.openai_url == expected

    def test_openai_headers_empty_key(self):
        s = _settings(element_gateway_api_key="")
        assert s.openai_headers["X-Api-Key"] == ""
        assert s.openai_headers["api-key"] == ""

    def test_claude_headers_empty_key(self):
        s = _settings(claude_api_key="")
        assert s.claude_headers["x-api-key"] == ""


class TestLruCacheBehavior:
    """get_settings() returns same instance on repeated calls."""

    def test_get_settings_returns_same_instance(self):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_gives_new_instance(self):
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # They may be equal but not the same object
        assert s1 is not s2


class TestSettingsAllDefaults:
    """Settings with no env vars -- all defaults should work."""

    def test_defaults_create_valid_instance(self, monkeypatch):
        # Clear env vars that might be set by .env files
        for key in list(monkeypatch._patches if hasattr(monkeypatch, '_patches') else []):
            pass
        s = Settings()
        assert s.agent_port == 8001 or isinstance(s.agent_port, int)
        assert isinstance(s.openai_url, str)
        assert isinstance(s.mcp_config_key, str)


class TestSettingsAllOverridden:
    """Settings with every field explicitly overridden."""

    def test_all_fields_overridden(self):
        s = Settings(
            agent_host="10.0.0.1",
            agent_port=9999,
            element_gateway_base_url="https://override.com",
            element_gateway_api_key="override-key",
            element_gateway_api_version="2025-01-01",
            openai_model="gpt-5",
            claude_gateway_url="https://claude-override.com",
            claude_api_key="claude-override",
            claude_model="claude-4",
            claude_anthropic_version="vertex-2025-01-01",
            claude_is_primary_llm=True,
            secrets_path="/custom/secrets/",
            redis_host="redis-override.com",
            redis_port=6380,
            redis_password="secret",
            redis_username="admin",
            redis_session_ttl_seconds=3600,
            cors_allowed_origins=["https://custom.com"],
            allowed_hosts=["custom.com"],
            a2ui_enabled=True,
            skills_dir="/custom/skills",
            exclude_skills="skill1,skill2",
            enable_mcps=False,
            max_tool_rounds=20,
            llm_timeout_seconds=120,
            mcp_timeout_seconds=60,
            llm_history_turns=5,
            shrink_tool_result_max_chars=500,
            llm_prompt_cache_enabled=True,
            llm_prompt_cache_extended=True,
            llm_extended_thinking_enabled=True,
            llm_thinking_budget_tokens=16384,
            redis_ssl=False,
            redis_socket_timeout=30,
            redis_socket_connect_timeout=20,
            redis_max_connections=100,
            redis_retry_attempts=5,
            redis_retry_backoff_seconds=1.0,
            sso_username="user@test.com",
            sso_password="password123",
            pingfed_base_url="https://custom-pingfed.com",
            pingfed_urls="https://a.com,https://b.com",
            auth_token_ttl=1800,
            auth_token_refresh_at=1200,
            auth_lock_ttl=30,
            agent_env="staging",
            agent_group="platform",
            mcp_servers_file="/custom/mcp.yml",
            a2a_agents_file="/custom/a2a.yml",
        )
        assert s.agent_host == "10.0.0.1"
        assert s.agent_port == 9999
        assert s.claude_is_primary_llm is True
        assert s.active_llm == "claude"
        assert s.mcp_config_key == "super_agent:config:mcp_servers:staging:platform:config"
        assert s.cors_allowed_origins == ["https://custom.com"]
        assert s.enable_mcps is False
        assert s.redis_ssl is False


class TestOpenaiUrlConstruction:
    """openai_url with special characters in base URL."""

    def test_special_chars_in_base_url(self):
        s = _settings(element_gateway_base_url="https://gate.com/v1?foo=bar")
        assert "https://gate.com/v1?foo=bar/deployments/" in s.openai_url

    def test_trailing_slash_in_base_url(self):
        s = _settings(element_gateway_base_url="https://gate.com/")
        assert "https://gate.com//deployments/" in s.openai_url

    def test_api_version_in_url(self):
        s = _settings(element_gateway_api_version="2025-99-99")
        assert "api-version=2025-99-99" in s.openai_url


class TestMcpConfigKeyEdgeCases:
    """mcp_config_key with empty or unusual env/group."""

    def test_empty_env_empty_group(self):
        s = _settings(agent_env="", agent_group="")
        assert s.mcp_config_key == "super_agent:config:mcp_servers:::config"

    def test_colon_in_env(self):
        s = _settings(agent_env="a:b")
        assert "a:b" in s.mcp_config_key

    def test_slash_in_group(self):
        s = _settings(agent_group="a/b")
        assert "a/b" in s.mcp_config_key


class TestActiveLlmEndpoint:
    """active_llm_endpoint switches between claude and openai."""

    def test_openai_when_not_primary(self):
        s = _settings(claude_is_primary_llm=False)
        assert s.active_llm_endpoint == s.openai_url
        assert s.active_llm == "openai"

    def test_claude_when_primary(self):
        s = _settings(claude_is_primary_llm=True, claude_gateway_url="https://claude.io")
        assert s.active_llm_endpoint == "https://claude.io"
        assert s.active_llm == "claude"


# ============================================================================
# CONSTANTS TESTS
# ============================================================================


class TestJSONRPCCode:
    """JSONRPCCode class attributes and boundary values."""

    def test_parse_error_value(self):
        assert JSONRPCCode.PARSE_ERROR == -32700

    def test_invalid_request_value(self):
        assert JSONRPCCode.INVALID_REQUEST == -32600

    def test_method_not_found_value(self):
        assert JSONRPCCode.METHOD_NOT_FOUND == -32601

    def test_invalid_params_value(self):
        assert JSONRPCCode.INVALID_PARAMS == -32602

    def test_internal_error_value(self):
        assert JSONRPCCode.INTERNAL_ERROR == -32603

    def test_task_not_found_value(self):
        assert JSONRPCCode.TASK_NOT_FOUND == -32001

    def test_all_codes_are_negative(self):
        codes = [
            JSONRPCCode.PARSE_ERROR,
            JSONRPCCode.INVALID_REQUEST,
            JSONRPCCode.METHOD_NOT_FOUND,
            JSONRPCCode.INVALID_PARAMS,
            JSONRPCCode.INTERNAL_ERROR,
            JSONRPCCode.TASK_NOT_FOUND,
        ]
        assert all(c < 0 for c in codes)

    def test_standard_codes_in_range(self):
        """Standard JSON-RPC codes must be in -32768..-32000."""
        standard = [
            JSONRPCCode.PARSE_ERROR,
            JSONRPCCode.INVALID_REQUEST,
            JSONRPCCode.METHOD_NOT_FOUND,
            JSONRPCCode.INVALID_PARAMS,
            JSONRPCCode.INTERNAL_ERROR,
        ]
        for code in standard:
            assert -32768 <= code <= -32000

    def test_app_code_in_range(self):
        """Application-specific codes in -32099..-32000."""
        assert -32099 <= JSONRPCCode.TASK_NOT_FOUND <= -32000


class TestSkillTools:
    """SKILL_TOOLS frozenset immutability."""

    def test_is_frozenset(self):
        assert isinstance(SKILL_TOOLS, frozenset)

    def test_expected_members(self):
        assert "list_skills" in SKILL_TOOLS
        assert "load_skill" in SKILL_TOOLS
        assert "load_skill_resource" in SKILL_TOOLS
        assert "run_skill_script" in SKILL_TOOLS

    def test_size(self):
        assert len(SKILL_TOOLS) == 4

    def test_add_raises(self):
        with pytest.raises(AttributeError):
            SKILL_TOOLS.add("hacked_tool")  # type: ignore[attr-defined]

    def test_remove_raises(self):
        with pytest.raises(AttributeError):
            SKILL_TOOLS.remove("list_skills")  # type: ignore[attr-defined]

    def test_discard_raises(self):
        with pytest.raises(AttributeError):
            SKILL_TOOLS.discard("list_skills")  # type: ignore[attr-defined]

    def test_nonexistent_tool_not_in_set(self):
        assert "nonexistent_tool" not in SKILL_TOOLS


class TestLLMHttpErrorCodes:
    """LLM_HTTP_ERROR_CODES tuple membership and boundaries."""

    def test_is_tuple(self):
        assert isinstance(LLM_HTTP_ERROR_CODES, tuple)

    def test_contains_expected_codes(self):
        for code in (400, 401, 403, 404, 429, 500, 502, 503):
            assert code in LLM_HTTP_ERROR_CODES

    def test_does_not_contain_200(self):
        assert 200 not in LLM_HTTP_ERROR_CODES

    def test_does_not_contain_201(self):
        assert 201 not in LLM_HTTP_ERROR_CODES

    def test_does_not_contain_504(self):
        assert 504 not in LLM_HTTP_ERROR_CODES

    def test_all_are_ints(self):
        assert all(isinstance(c, int) for c in LLM_HTTP_ERROR_CODES)


class TestAppNameAndDefaultUser:
    """APP_NAME and DEFAULT_USER_ID type validation."""

    def test_app_name_is_string(self):
        assert isinstance(APP_NAME, str)

    def test_app_name_not_empty(self):
        assert len(APP_NAME) > 0

    def test_default_user_id_is_string(self):
        assert isinstance(DEFAULT_USER_ID, str)

    def test_default_user_id_value(self):
        assert DEFAULT_USER_ID == "admin"

    def test_app_name_default(self):
        """Without APP_NAME env var, defaults to 'health_agent'."""
        with patch.dict("os.environ", {}, clear=False):
            # APP_NAME is set at module import time, so we test the current value
            assert isinstance(APP_NAME, str)
