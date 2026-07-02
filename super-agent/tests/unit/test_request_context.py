"""Tests for app.request_context — per-request LLM Gateway header propagation."""

import asyncio

import pytest
from starlette.requests import Request

from app.request_context import (
    LLM_HEADER_KEYS,
    extract_llm_headers,
    set_llm_headers,
    get_llm_headers,
    clear_llm_headers,
    _normalize_user_type,
)


# ── extract_llm_headers ──────────────────────────────────────────────────────


class TestExtractLLMHeaders:
    """Test header extraction from Starlette Request objects."""

    @staticmethod
    def _make_request(headers: dict[str, str]) -> Request:
        """Build a minimal Starlette Request with the given headers."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/a2a",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        return Request(scope)

    def test_extracts_all_present_headers(self):
        req = self._make_request({
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "jdoe@walmart.com",
            "wm_llm_gw.user_agent": "Mozilla/5.0",
            "wm_llm_gw.user_ip": "10.0.0.1",
        })
        result = extract_llm_headers(req)
        assert result == {
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "jdoe@walmart.com",
            "wm_llm_gw.user_agent": "Mozilla/5.0",
            "wm_llm_gw.user_ip": "10.0.0.1",
        }

    def test_extracts_partial_headers(self):
        req = self._make_request({
            "wm_llm_gw.user_type": "VENDOR",
            "wm_llm_gw.user_name": "vendor@acme.com",
        })
        result = extract_llm_headers(req)
        assert result == {
            "wm_llm_gw.user_type": "VENDOR",
            "wm_llm_gw.user_name": "vendor@acme.com",
        }
        assert "wm_llm_gw.user_agent" not in result
        assert "wm_llm_gw.user_ip" not in result

    def test_defaults_user_type_when_no_llm_headers(self):
        """Even with no LLM headers, user_type should default to ASSOCIATE."""
        req = self._make_request({
            "Content-Type": "application/json",
            "Authorization": "Bearer token123",
        })
        result = extract_llm_headers(req)
        assert result == {"wm_llm_gw.user_type": "ASSOCIATE"}

    def test_ignores_unrelated_headers(self):
        req = self._make_request({
            "wm_llm_gw.user_type": "ASSOCIATE",
            "X-Custom-Header": "should-not-appear",
        })
        result = extract_llm_headers(req)
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"
        assert "X-Custom-Header" not in result

    def test_normalizes_legacy_user_type_S(self):
        """Old frontend sending 'S' (salaried) should be normalized to ASSOCIATE."""
        req = self._make_request({
            "wm_llm_gw.user_type": "S",
            "wm_llm_gw.user_name": "jdoe@walmart.com",
        })
        result = extract_llm_headers(req)
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"

    def test_normalizes_legacy_user_type_H(self):
        """Old frontend sending 'H' (hourly) should be normalized to ASSOCIATE."""
        req = self._make_request({
            "wm_llm_gw.user_type": "H",
            "wm_llm_gw.user_name": "jdoe@walmart.com",
        })
        result = extract_llm_headers(req)
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"

    def test_normalizes_legacy_user_type_standard(self):
        """Old frontend sending 'standard' should be normalized to ASSOCIATE."""
        req = self._make_request({
            "wm_llm_gw.user_type": "standard",
            "wm_llm_gw.user_name": "jdoe@walmart.com",
        })
        result = extract_llm_headers(req)
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"

    def test_falls_back_user_name_to_loginid(self):
        """If wm_llm_gw.user_name missing, falls back to loginId header."""
        req = self._make_request({
            "wm_llm_gw.user_type": "ASSOCIATE",
            "loginId": "jdoe@walmart.com",
        })
        result = extract_llm_headers(req)
        assert result["wm_llm_gw.user_name"] == "jdoe@walmart.com"

    def test_unknown_user_type_defaults_to_associate(self):
        """Totally unknown user_type should default to ASSOCIATE."""
        req = self._make_request({
            "wm_llm_gw.user_type": "FOOBAR",
            "wm_llm_gw.user_name": "jdoe@walmart.com",
        })
        result = extract_llm_headers(req)
        assert result["wm_llm_gw.user_type"] == "ASSOCIATE"


# ── set_llm_headers / get_llm_headers / clear_llm_headers ────────────────────


class TestContextVarOps:
    """Test context variable operations."""

    def test_set_and_get_roundtrip(self):
        headers = {"wm_llm_gw.user_type": "ASSOCIATE", "wm_llm_gw.user_name": "alice"}
        set_llm_headers(headers)
        assert get_llm_headers() == headers

    def test_clear_resets_to_empty(self):
        set_llm_headers({"wm_llm_gw.user_type": "ASSOCIATE"})
        clear_llm_headers()
        assert get_llm_headers() == {}

    def test_default_is_empty_dict(self):
        """New async tasks should start with empty headers (ContextVar default)."""
        clear_llm_headers()
        assert get_llm_headers() == {}

    def test_overwrite_replaces_previous(self):
        set_llm_headers({"wm_llm_gw.user_type": "ASSOCIATE"})
        set_llm_headers({"wm_llm_gw.user_type": "VENDOR"})
        assert get_llm_headers() == {"wm_llm_gw.user_type": "VENDOR"}


class TestContextVarIsolation:
    """Test that contextvars are isolated between async tasks."""

    @pytest.mark.asyncio
    async def test_headers_do_not_leak_between_tasks(self):
        """Two concurrent async tasks should not see each other's headers."""
        results: dict[str, dict] = {}

        async def task_a():
            set_llm_headers({"wm_llm_gw.user_name": "task-a-user"})
            await asyncio.sleep(0.01)  # yield to event loop
            results["a"] = get_llm_headers()

        async def task_b():
            set_llm_headers({"wm_llm_gw.user_name": "task-b-user"})
            await asyncio.sleep(0.01)
            results["b"] = get_llm_headers()

        await asyncio.gather(
            asyncio.create_task(task_a()),
            asyncio.create_task(task_b()),
        )

        assert results["a"] == {"wm_llm_gw.user_name": "task-a-user"}
        assert results["b"] == {"wm_llm_gw.user_name": "task-b-user"}


# ── LLM_HEADER_KEYS ──────────────────────────────────────────────────────────


class TestHeaderKeyConstants:
    """Verify the header key constants match the LLM Gateway spec."""

    def test_all_mandatory_keys_present(self):
        assert "wm_llm_gw.user_type" in LLM_HEADER_KEYS
        assert "wm_llm_gw.user_name" in LLM_HEADER_KEYS
        assert "wm_llm_gw.user_agent" in LLM_HEADER_KEYS
        assert "wm_llm_gw.user_ip" in LLM_HEADER_KEYS

    def test_exactly_four_keys(self):
        assert len(LLM_HEADER_KEYS) == 4


# ── _normalize_user_type ─────────────────────────────────────────────────────


class TestNormalizeUserType:
    """Test user_type validation and normalization."""

    @pytest.mark.parametrize("value,expected", [
        ("ASSOCIATE", "ASSOCIATE"),
        ("RETAIL_CUSTOMER", "RETAIL_CUSTOMER"),
        ("VENDOR", "VENDOR"),
        ("TECH_DEVELOPMENT", "TECH_DEVELOPMENT"),
        ("NO_END_USER", "NO_END_USER"),
        ("associate", "ASSOCIATE"),        # case-insensitive
        ("vendor", "VENDOR"),              # case-insensitive
        ("S", "ASSOCIATE"),                # legacy salaried
        ("H", "ASSOCIATE"),                # legacy hourly
        ("s", "ASSOCIATE"),                # lowercase legacy
        ("h", "ASSOCIATE"),                # lowercase legacy
        ("SALARIED", "ASSOCIATE"),         # long-form legacy
        ("HOURLY", "ASSOCIATE"),           # long-form legacy
        ("standard", "ASSOCIATE"),         # old frontend default
        ("STANDARD", "ASSOCIATE"),         # old frontend default caps
        ("FOOBAR", "ASSOCIATE"),           # unknown → default
        ("  ASSOCIATE  ", "ASSOCIATE"),    # whitespace trimmed
    ])
    def test_normalization(self, value, expected):
        assert _normalize_user_type(value) == expected


# ── _HeaderInjectingClient ───────────────────────────────────────────────────


class TestHeaderInjectingClient:
    """Test that _HeaderInjectingClient merges contextvars headers into kwargs."""

    def _make_client(self):
        """Import and instantiate the header-injecting LiteLLM client wrapper."""
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient()

    def test_merge_adds_llm_headers_to_empty_kwargs(self):
        client = self._make_client()
        set_llm_headers({
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "alice@walmart.com",
        })
        kwargs: dict = {}
        result = client._merge_llm_headers(kwargs)
        assert result["extra_headers"] == {
            "wm_llm_gw.user_type": "ASSOCIATE",
            "wm_llm_gw.user_name": "alice@walmart.com",
        }

    def test_merge_preserves_existing_extra_headers(self):
        client = self._make_client()
        set_llm_headers({"wm_llm_gw.user_type": "VENDOR"})
        kwargs = {"extra_headers": {"anthropic-version": "2024-01-01"}}
        result = client._merge_llm_headers(kwargs)
        assert result["extra_headers"] == {
            "anthropic-version": "2024-01-01",
            "wm_llm_gw.user_type": "VENDOR",
        }

    def test_merge_noop_when_no_llm_headers(self):
        client = self._make_client()
        clear_llm_headers()
        kwargs = {"extra_headers": {"anthropic-version": "2024-01-01"}}
        result = client._merge_llm_headers(kwargs)
        # Original extra_headers untouched
        assert result["extra_headers"] == {"anthropic-version": "2024-01-01"}

    def test_merge_noop_when_context_empty_and_no_existing(self):
        client = self._make_client()
        clear_llm_headers()
        kwargs: dict = {}
        result = client._merge_llm_headers(kwargs)
        assert "extra_headers" not in result

    def test_llm_headers_override_same_key_in_existing(self):
        """Per-request headers should override any same-named static header."""
        client = self._make_client()
        set_llm_headers({"wm_llm_gw.user_type": "VENDOR"})
        kwargs = {"extra_headers": {"wm_llm_gw.user_type": "STALE_VALUE"}}
        result = client._merge_llm_headers(kwargs)
        assert result["extra_headers"]["wm_llm_gw.user_type"] == "VENDOR"
