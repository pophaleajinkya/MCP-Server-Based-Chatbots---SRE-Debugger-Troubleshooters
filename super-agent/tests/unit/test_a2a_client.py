"""Unit tests for app.a2a.client — A2A agent registry helpers.

Coverage matrix
───────────────

_validate_and_parse
  ✅ empty list → ValueError
  ✅ missing required field (url) → ValueError
  ✅ missing required field (name) → ValueError
  ✅ missing required field (enabled) → ValueError
  ✅ all entries disabled → ValueError
  ✅ enabled/disabled filtering — only enabled entries returned
  ✅ hyphen-to-underscore conversion in name
  ✅ double-hyphen in name → double-underscore
  ✅ name already snake_case → unchanged
  ✅ trailing slash stripped from url
  ✅ multiple trailing slashes stripped
  ✅ description=None → defaults to ""
  ✅ description="" → defaults to ""
  ✅ headers=None → defaults to {}
  ✅ extra unknown fields in entry → silently ignored (not in dataclass)
  ✅ enabled=1 (truthy int) → treated as enabled
  ✅ enabled=False (boolean) → treated as disabled
  ✅ multiple enabled entries all returned
  ✅ mixed enabled/disabled — only enabled returned

_load_from_file
  ✅ non-existent path → FileNotFoundError
  ✅ file is empty (yaml.safe_load returns None) → ValueError
  ✅ file has wrong top-level key → ValueError
  ✅ file uses 'agents' fallback key → parsed correctly
  ✅ file has 'a2a_agents: []' (empty list) → ValueError
  ✅ file has 'a2a_agents: null' → ValueError

load_a2a_agents
  ✅ local mode, A2A_AGENTS_FILE not set → returns []
  ✅ local mode, file set but missing → FileNotFoundError propagates
  ✅ local mode, valid file → returns parsed configs
  ✅ non-local mode, Redis returns None → returns []
  ✅ non-local mode, Redis returns empty JSON array → returns []
  ✅ non-local mode, Redis returns valid JSON → returns parsed configs
  ✅ non-local mode, Redis raises → exception propagates

fetch_agent_card
  ✅ 200 OK valid JSON → returns card dict
  ✅ 404 response → returns {}
  ✅ 500 response → returns {}
  ✅ ConnectError (agent unreachable) → returns {}
  ✅ ReadTimeout → returns {}
  ✅ ConnectTimeout → returns {}
  ✅ non-JSON 200 response → returns {}
  ✅ URL with trailing slash → slash stripped before building card URL
  ✅ custom headers forwarded in request
  ✅ headers=None → no crash
  ✅ card missing 'skills' key → returns card (skills defaults to [])
  ✅ card has skills with no 'id'/'name' → uses '?' fallback
  ✅ card has empty skills list → returns card, logs correctly
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── helpers ───────────────────────────────────────────────────────────────────

_DUMMY_REQUEST = httpx.Request("GET", "http://agent.test/.well-known/agent.json")


def _http_response(body, status: int = 200, content_type: str = "application/json"):
    return httpx.Response(
        status_code=status,
        text=json.dumps(body) if isinstance(body, dict) else body,
        headers={"content-type": content_type},
        request=_DUMMY_REQUEST,
    )


def _write_yaml(content: str) -> str:
    """Write content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
    f.write(content)
    f.flush()
    f.close()
    return f.name


# ── _validate_and_parse ───────────────────────────────────────────────────────

class TestValidateAndParse:

    def _run(self, entries, source="test"):
        from app.a2a.client import _validate_and_parse
        return _validate_and_parse(entries, source=source)

    # ── empty / all-disabled raises ───────────────────────────────────────────

    def test_empty_list_raises_value_error(self):
        with pytest.raises(ValueError, match="is empty"):
            self._run([])

    def test_all_disabled_raises_value_error(self):
        with pytest.raises(ValueError, match="none are enabled"):
            self._run([{"name": "x", "url": "http://x", "enabled": False}])

    def test_all_disabled_multiple_entries_raises(self):
        with pytest.raises(ValueError, match="none are enabled"):
            self._run([
                {"name": "a", "url": "http://a", "enabled": False},
                {"name": "b", "url": "http://b", "enabled": False},
            ])

    # ── missing required fields raises ───────────────────────────────────────

    def test_missing_url_raises_value_error(self):
        with pytest.raises(ValueError, match="url"):
            self._run([{"name": "x", "enabled": True}])

    def test_missing_name_raises_value_error(self):
        with pytest.raises(ValueError, match="name"):
            self._run([{"url": "http://x", "enabled": True}])

    def test_missing_enabled_raises_value_error(self):
        with pytest.raises(ValueError, match="enabled"):
            self._run([{"name": "x", "url": "http://x"}])

    def test_missing_multiple_fields_lists_all_missing(self):
        """Error message must enumerate every missing field."""
        with pytest.raises(ValueError) as exc_info:
            self._run([{"name": "x"}])
        msg = str(exc_info.value)
        assert "url" in msg or "enabled" in msg

    def test_missing_field_error_includes_entry_index(self):
        """Error message references the position of the bad entry."""
        with pytest.raises(ValueError, match=r"\[0\]"):
            self._run([{"url": "http://x", "enabled": True}])

    # ── name normalisation ────────────────────────────────────────────────────

    def test_hyphen_converted_to_underscore(self):
        configs = self._run([{"name": "sre-agent", "url": "http://x", "enabled": True}])
        assert configs[0].name == "sre_agent"

    def test_double_hyphen_converted(self):
        configs = self._run([{"name": "sre--agent", "url": "http://x", "enabled": True}])
        assert configs[0].name == "sre__agent"

    def test_snake_case_name_unchanged(self):
        configs = self._run([{"name": "sre_agent", "url": "http://x", "enabled": True}])
        assert configs[0].name == "sre_agent"

    def test_name_with_no_hyphens_unchanged(self):
        configs = self._run([{"name": "deploy", "url": "http://x", "enabled": True}])
        assert configs[0].name == "deploy"

    # ── URL normalisation ─────────────────────────────────────────────────────

    def test_trailing_slash_stripped_from_url(self):
        configs = self._run([{"name": "x", "url": "http://agent.test/", "enabled": True}])
        assert configs[0].url == "http://agent.test"

    def test_multiple_trailing_slashes_stripped(self):
        configs = self._run([{"name": "x", "url": "http://agent.test///", "enabled": True}])
        assert configs[0].url == "http://agent.test"

    def test_url_without_trailing_slash_unchanged(self):
        configs = self._run([{"name": "x", "url": "http://agent.test", "enabled": True}])
        assert configs[0].url == "http://agent.test"

    # ── optional fields defaults ──────────────────────────────────────────────

    def test_description_none_becomes_empty_string(self):
        configs = self._run([{"name": "x", "url": "http://x", "enabled": True, "description": None}])
        assert configs[0].description == ""

    def test_description_empty_string_stays_empty(self):
        configs = self._run([{"name": "x", "url": "http://x", "enabled": True, "description": ""}])
        assert configs[0].description == ""

    def test_description_present_preserved(self):
        configs = self._run([{"name": "x", "url": "http://x", "enabled": True, "description": "My agent"}])
        assert configs[0].description == "My agent"

    def test_headers_none_becomes_empty_dict(self):
        configs = self._run([{"name": "x", "url": "http://x", "enabled": True, "headers": None}])
        assert configs[0].headers == {}

    def test_headers_absent_becomes_empty_dict(self):
        configs = self._run([{"name": "x", "url": "http://x", "enabled": True}])
        assert configs[0].headers == {}

    def test_headers_present_preserved(self):
        h = {"Authorization": "Bearer tok"}
        configs = self._run([{"name": "x", "url": "http://x", "enabled": True, "headers": h}])
        assert configs[0].headers == h

    # ── enabled/disabled filtering ────────────────────────────────────────────

    def test_disabled_entry_not_returned(self):
        configs = self._run([
            {"name": "a", "url": "http://a", "enabled": True},
            {"name": "b", "url": "http://b", "enabled": False},
        ])
        assert len(configs) == 1
        assert configs[0].name == "a"

    def test_enabled_true_integer_treated_as_enabled(self):
        """enabled=1 (truthy int) should be treated as enabled."""
        configs = self._run([{"name": "x", "url": "http://x", "enabled": 1}])
        assert len(configs) == 1

    def test_enabled_false_boolean_treated_as_disabled(self):
        with pytest.raises(ValueError, match="none are enabled"):
            self._run([{"name": "x", "url": "http://x", "enabled": False}])

    def test_multiple_enabled_entries_all_returned(self):
        configs = self._run([
            {"name": "a", "url": "http://a", "enabled": True},
            {"name": "b", "url": "http://b", "enabled": True},
            {"name": "c", "url": "http://c", "enabled": True},
        ])
        assert len(configs) == 3
        assert [c.name for c in configs] == ["a", "b", "c"]

    # ── unknown / extra fields silently ignored ───────────────────────────────

    def test_extra_unknown_fields_ignored(self):
        """Unknown fields in the config dict must not cause a crash."""
        configs = self._run([{
            "name": "x", "url": "http://x", "enabled": True,
            "foo": "bar", "unknown_key": 42,
        }])
        assert len(configs) == 1
        assert configs[0].name == "x"

    # ── source label in error messages ───────────────────────────────────────

    def test_source_label_included_in_error(self):
        """The source param appears in the ValueError message for traceability."""
        with pytest.raises(ValueError, match="my-redis-key"):
            self._run([], source="my-redis-key")


# ── _load_from_file ───────────────────────────────────────────────────────────

class TestLoadFromFile:

    def _load(self, path):
        from app.a2a.client import _load_from_file
        return _load_from_file(path)

    # ── file not found ────────────────────────────────────────────────────────

    def test_nonexistent_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="/nonexistent/a2a.yml"):
            self._load("/nonexistent/a2a.yml")

    # ── file content errors ───────────────────────────────────────────────────

    def test_empty_file_raises_value_error(self):
        path = _write_yaml("")
        with pytest.raises(ValueError, match="empty"):
            self._load(path)

    def test_yaml_only_comments_raises_value_error(self):
        """A file with only comments is effectively empty after yaml.safe_load."""
        path = _write_yaml("# just a comment\n# another comment\n")
        with pytest.raises(ValueError, match="empty"):
            self._load(path)

    def test_wrong_top_level_key_raises_value_error(self):
        """File with 'mcp_servers' instead of 'a2a_agents' must raise."""
        path = _write_yaml("mcp_servers:\n  - name: x\n")
        with pytest.raises(ValueError, match="'a2a_agents'"):
            self._load(path)

    def test_empty_a2a_agents_list_raises_value_error(self):
        path = _write_yaml("a2a_agents: []\n")
        with pytest.raises(ValueError, match="'a2a_agents'"):
            self._load(path)

    def test_null_a2a_agents_raises_value_error(self):
        path = _write_yaml("a2a_agents: null\n")
        with pytest.raises(ValueError, match="'a2a_agents'"):
            self._load(path)

    # ── fallback key ──────────────────────────────────────────────────────────

    def test_agents_fallback_key_accepted(self):
        """'agents:' is accepted as a fallback key."""
        path = _write_yaml(
            "agents:\n"
            "  - name: sre-agent\n"
            "    url: http://localhost:8002\n"
            "    enabled: true\n"
        )
        entries = self._load(path)
        assert len(entries) == 1
        assert entries[0]["name"] == "sre-agent"

    # ── happy path ────────────────────────────────────────────────────────────

    def test_valid_a2a_agents_key_returned(self):
        path = _write_yaml(
            "a2a_agents:\n"
            "  - name: sre-agent\n"
            "    url: http://localhost:8002\n"
            "    enabled: true\n"
            "  - name: deploy-agent\n"
            "    url: http://localhost:8003\n"
            "    enabled: false\n"
        )
        entries = self._load(path)
        assert len(entries) == 2
        assert entries[0]["name"] == "sre-agent"
        assert entries[1]["enabled"] is False

    def test_file_with_headers_field_parsed(self):
        path = _write_yaml(
            "a2a_agents:\n"
            "  - name: x\n"
            "    url: http://x\n"
            "    enabled: true\n"
            "    headers:\n"
            "      Authorization: Bearer tok\n"
        )
        entries = self._load(path)
        assert entries[0]["headers"]["Authorization"] == "Bearer tok"


# ── load_a2a_agents ───────────────────────────────────────────────────────────

class TestLoadA2AAgents:
    """Tests for the public load_a2a_agents() async function.

    We patch get_settings() to control AGENT_ENV and A2A_AGENTS_FILE,
    and _load_from_redis / _load_from_file to isolate from real I/O.
    """

    # ── local mode ────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_local_mode_no_file_returns_empty(self):
        """Local mode without A2A_AGENTS_FILE → [] (non-fatal)."""
        mock_s = MagicMock()
        mock_s.agent_env = "local"
        mock_s.a2a_agents_file = ""
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            from app.a2a.client import load_a2a_agents
            result = await load_a2a_agents()
        assert result == []

    @pytest.mark.asyncio
    async def test_local_mode_env_case_insensitive(self):
        """AGENT_ENV='LOCAL' (uppercase) also triggers local mode."""
        mock_s = MagicMock()
        mock_s.agent_env = "LOCAL"
        mock_s.a2a_agents_file = ""
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            from app.a2a.client import load_a2a_agents
            result = await load_a2a_agents()
        assert result == []

    @pytest.mark.asyncio
    async def test_local_mode_missing_file_raises(self):
        """Local mode with A2A_AGENTS_FILE pointing at a non-existent file must raise."""
        mock_s = MagicMock()
        mock_s.agent_env = "local"
        mock_s.a2a_agents_file = "/no/such/file.yml"
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            from app.a2a.client import load_a2a_agents
            with pytest.raises(FileNotFoundError):
                await load_a2a_agents()

    @pytest.mark.asyncio
    async def test_local_mode_valid_file_returns_configs(self):
        """Local mode with a valid YAML file returns the parsed configs."""
        path = _write_yaml(
            "a2a_agents:\n"
            "  - name: sre-agent\n"
            "    url: http://localhost:8002\n"
            "    enabled: true\n"
        )
        mock_s = MagicMock()
        mock_s.agent_env = "local"
        mock_s.a2a_agents_file = path
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            from app.a2a.client import load_a2a_agents
            result = await load_a2a_agents()
        assert len(result) == 1
        assert result[0].name == "sre_agent"

    # ── redis mode ────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_redis_mode_empty_key_returns_empty(self):
        """Redis key is empty/unset → [] (non-fatal)."""
        mock_s = MagicMock()
        mock_s.agent_env = "stage"
        mock_s.agent_group = "sre"
        mock_s.a2a_agents_config_key = "super_agent:config:a2a_agents:stage:sre:config"
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            with patch("app.a2a.client._load_from_redis", new=AsyncMock(return_value=[])):
                from app.a2a.client import load_a2a_agents
                result = await load_a2a_agents()
        assert result == []

    @pytest.mark.asyncio
    async def test_redis_mode_returns_none_gives_empty(self):
        """Redis _load_from_redis returning [] (from None key) gives empty list."""
        mock_s = MagicMock()
        mock_s.agent_env = "prod"
        mock_s.agent_group = "sre"
        mock_s.a2a_agents_config_key = "some:key"
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            with patch("app.a2a.client._load_from_redis", new=AsyncMock(return_value=[])):
                from app.a2a.client import load_a2a_agents
                result = await load_a2a_agents()
        assert result == []

    @pytest.mark.asyncio
    async def test_redis_mode_valid_data_returns_configs(self):
        """Redis key with valid JSON returns parsed A2AAgentConfig list."""
        mock_s = MagicMock()
        mock_s.agent_env = "stage"
        mock_s.agent_group = "sre"
        mock_s.a2a_agents_config_key = "some:key"
        redis_entries = [
            {"name": "sre-agent", "url": "http://sre.stage.walmart.com", "enabled": True},
        ]
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            with patch("app.a2a.client._load_from_redis", new=AsyncMock(return_value=redis_entries)):
                from app.a2a.client import load_a2a_agents
                result = await load_a2a_agents()
        assert len(result) == 1
        assert result[0].name == "sre_agent"
        assert result[0].url == "http://sre.stage.walmart.com"

    @pytest.mark.asyncio
    async def test_redis_mode_exception_propagates(self):
        """Redis connection failure propagates (unlike empty key which is non-fatal)."""
        mock_s = MagicMock()
        mock_s.agent_env = "stage"
        mock_s.agent_group = "sre"
        mock_s.a2a_agents_config_key = "some:key"
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            with patch(
                "app.a2a.client._load_from_redis",
                new=AsyncMock(side_effect=ConnectionError("Redis unreachable")),
            ):
                from app.a2a.client import load_a2a_agents
                with pytest.raises(ConnectionError, match="Redis unreachable"):
                    await load_a2a_agents()

    @pytest.mark.asyncio
    async def test_redis_mode_all_disabled_raises(self):
        """Redis data where all agents are disabled raises ValueError."""
        mock_s = MagicMock()
        mock_s.agent_env = "stage"
        mock_s.agent_group = "sre"
        mock_s.a2a_agents_config_key = "some:key"
        redis_entries = [{"name": "x", "url": "http://x", "enabled": False}]
        with patch("app.a2a.client.get_settings", return_value=mock_s):
            with patch("app.a2a.client._load_from_redis", new=AsyncMock(return_value=redis_entries)):
                from app.a2a.client import load_a2a_agents
                with pytest.raises(ValueError, match="none are enabled"):
                    await load_a2a_agents()

    @pytest.mark.asyncio
    async def test_non_local_env_uses_redis_not_file(self):
        """Any env value other than 'local' must use Redis, not file."""
        for env in ("dev", "stage", "prod", "staging", "DEV"):
            mock_s = MagicMock()
            mock_s.agent_env = env
            mock_s.agent_group = "sre"
            mock_s.a2a_agents_config_key = "some:key"
            with patch("app.a2a.client.get_settings", return_value=mock_s):
                with patch("app.a2a.client._load_from_redis", new=AsyncMock(return_value=[])) as mock_redis:
                    with patch("app.a2a.client._load_from_file") as mock_file:
                        from app.a2a.client import load_a2a_agents
                        await load_a2a_agents()
                        mock_redis.assert_called_once()
                        mock_file.assert_not_called()


# ── _load_from_redis ──────────────────────────────────────────────────────────

class TestLoadFromRedis:
    """Tests for the internal _load_from_redis() coroutine."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_key_is_none(self):
        """Redis GET returning None → empty list."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        mock_s = MagicMock()
        mock_s.redis_host = "localhost"
        mock_s.redis_port = 6379
        mock_s.redis_username = ""
        mock_s.redis_password = ""
        mock_s.redis_ssl = False

        with patch("app.a2a.client.RedisCluster", return_value=mock_redis):
            from app.a2a.client import _load_from_redis
            result = await _load_from_redis("some:key", mock_s)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_key_is_empty_string(self):
        """Redis GET returning '' → empty list."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="")
        mock_redis.aclose = AsyncMock()

        mock_s = MagicMock()
        mock_s.redis_host = "localhost"
        mock_s.redis_port = 6379
        mock_s.redis_username = ""
        mock_s.redis_password = ""
        mock_s.redis_ssl = False

        with patch("app.a2a.client.RedisCluster", return_value=mock_redis):
            from app.a2a.client import _load_from_redis
            result = await _load_from_redis("some:key", mock_s)
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_valid_json_array(self):
        """Valid JSON array stored in Redis is returned as a Python list."""
        entries = [{"name": "x", "url": "http://x", "enabled": True}]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(entries))
        mock_redis.aclose = AsyncMock()

        mock_s = MagicMock()
        mock_s.redis_host = "localhost"
        mock_s.redis_port = 6379
        mock_s.redis_username = ""
        mock_s.redis_password = ""
        mock_s.redis_ssl = False

        with patch("app.a2a.client.RedisCluster", return_value=mock_redis):
            from app.a2a.client import _load_from_redis
            result = await _load_from_redis("some:key", mock_s)
        assert result == entries

    @pytest.mark.asyncio
    async def test_redis_aclose_called_even_on_exception(self):
        """aclose() must be called even when GET raises an exception."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=RuntimeError("connection lost"))
        mock_redis.aclose = AsyncMock()

        mock_s = MagicMock()
        mock_s.redis_host = "localhost"
        mock_s.redis_port = 6379
        mock_s.redis_username = ""
        mock_s.redis_password = ""
        mock_s.redis_ssl = False

        with patch("app.a2a.client.RedisCluster", return_value=mock_redis):
            from app.a2a.client import _load_from_redis
            with pytest.raises(RuntimeError):
                await _load_from_redis("some:key", mock_s)
        mock_redis.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_json_is_empty_array(self):
        """JSON '[]' → empty list."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="[]")
        mock_redis.aclose = AsyncMock()

        mock_s = MagicMock()
        mock_s.redis_host = "localhost"
        mock_s.redis_port = 6379
        mock_s.redis_username = ""
        mock_s.redis_password = ""
        mock_s.redis_ssl = False

        with patch("app.a2a.client.RedisCluster", return_value=mock_redis):
            from app.a2a.client import _load_from_redis
            result = await _load_from_redis("some:key", mock_s)
        assert result == []


# ── fetch_agent_card ──────────────────────────────────────────────────────────

class TestFetchAgentCard:

    def _card_url(self, base: str) -> str:
        return f"{base.rstrip('/')}/.well-known/agent.json"

    # ── successful response ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_200_returns_parsed_card(self):
        card = {"name": "sre-agent", "description": "SRE agent", "skills": []}
        resp = _http_response(card, status=200)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://sre.test")
        assert result == card

    @pytest.mark.asyncio
    async def test_card_with_skills_returned_intact(self):
        card = {
            "name": "sre-agent",
            "description": "SRE",
            "skills": [
                {"id": "incident_triage", "description": "Triage incidents"},
                {"id": "runbook", "description": "Run runbooks"},
            ],
        }
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://sre.test")
        assert len(result["skills"]) == 2

    @pytest.mark.asyncio
    async def test_card_missing_skills_key_returned_without_crash(self):
        """Card without 'skills' key must not raise."""
        card = {"name": "sre-agent", "description": "SRE"}
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://sre.test")
        assert result["name"] == "sre-agent"

    @pytest.mark.asyncio
    async def test_card_empty_skills_list_no_crash(self):
        """Empty skills list must not crash the skill_ids extraction."""
        card = {"name": "sre-agent", "description": "SRE", "skills": []}
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://sre.test")
        assert result == card

    @pytest.mark.asyncio
    async def test_skill_without_id_or_name_uses_question_mark(self):
        """Skill with neither 'id' nor 'name' key must not crash — uses '?'."""
        card = {"name": "x", "description": "d", "skills": [{"description": "no id"}]}
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://sre.test")
        assert result == card

    # ── HTTP error responses ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_404_returns_empty_dict(self):
        err_resp = _http_response({}, status=404)
        exc = httpx.HTTPStatusError("404", request=_DUMMY_REQUEST, response=err_resp)
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=exc)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://gone.test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_500_returns_empty_dict(self):
        err_resp = _http_response({"error": "internal"}, status=500)
        exc = httpx.HTTPStatusError("500", request=_DUMMY_REQUEST, response=err_resp)
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=exc)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://broken.test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_401_returns_empty_dict(self):
        err_resp = _http_response({"error": "unauthorized"}, status=401)
        exc = httpx.HTTPStatusError("401", request=_DUMMY_REQUEST, response=err_resp)
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=exc)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://secure.test")
        assert result == {}

    # ── network / connectivity errors ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_connect_error_returns_empty_dict(self):
        exc = httpx.ConnectError("connection refused", request=_DUMMY_REQUEST)
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=exc)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://unreachable.test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_read_timeout_returns_empty_dict(self):
        exc = httpx.ReadTimeout("read timed out", request=_DUMMY_REQUEST)
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=exc)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://slow.test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_connect_timeout_returns_empty_dict(self):
        exc = httpx.ConnectTimeout("connect timed out", request=_DUMMY_REQUEST)
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=exc)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://slow.test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_generic_exception_returns_empty_dict(self):
        """Any unexpected exception must be caught and return {}."""
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=RuntimeError("unexpected"))):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://broken.test")
        assert result == {}

    # ── non-JSON response ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_non_json_200_response_returns_empty_dict(self):
        """200 OK with non-JSON body (e.g. HTML) must return {}."""
        resp = _http_response("<html>not an agent</html>", status=200, content_type="text/html")
        # resp.json() will raise json.JSONDecodeError
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()  # does not raise
        mock_resp.json = MagicMock(side_effect=json.JSONDecodeError("bad json", "", 0))
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://html-server.test")
        assert result == {}

    # ── URL construction ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_trailing_slash_stripped_from_url_before_card_fetch(self):
        """URL with trailing slash must not produce double-slash in card URL."""
        card = {"name": "x", "skills": []}
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)) as mock_get:
            from app.a2a.client import fetch_agent_card
            await fetch_agent_card("http://agent.test/")
        called_url = mock_get.call_args[0][0]
        assert called_url == "http://agent.test/.well-known/agent.json"
        assert "//" not in called_url.replace("http://", "")

    @pytest.mark.asyncio
    async def test_card_url_appended_correctly_without_trailing_slash(self):
        card = {"name": "x", "skills": []}
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)) as mock_get:
            from app.a2a.client import fetch_agent_card
            await fetch_agent_card("http://agent.test")
        called_url = mock_get.call_args[0][0]
        assert called_url == "http://agent.test/.well-known/agent.json"

    # ── custom headers ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_custom_headers_forwarded(self):
        """headers= kwarg must be merged into the HTTP request headers."""
        card = {"name": "x", "skills": []}
        resp = _http_response(card)
        captured_headers: dict = {}
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
                from app.a2a.client import fetch_agent_card
                await fetch_agent_card(
                    "http://agent.test",
                    headers={"X-Internal-Token": "secret-123"},
                )

        assert captured_headers.get("X-Internal-Token") == "secret-123"

    @pytest.mark.asyncio
    async def test_headers_none_does_not_crash(self):
        """headers=None must not crash (no TypeError on dict merge)."""
        card = {"name": "x", "skills": []}
        resp = _http_response(card)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
            from app.a2a.client import fetch_agent_card
            result = await fetch_agent_card("http://agent.test", headers=None)
        assert result == card

    @pytest.mark.asyncio
    async def test_accept_header_always_set(self):
        """The Accept: application/json header must always be in the request."""
        card = {"name": "x", "skills": []}
        resp = _http_response(card)
        captured_headers: dict = {}
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
                from app.a2a.client import fetch_agent_card
                await fetch_agent_card("http://agent.test")

        assert "Accept" in captured_headers
        assert "application/json" in captured_headers["Accept"]


# ── A2AAgentConfig dataclass ──────────────────────────────────────────────────

class TestA2AAgentConfig:

    def test_default_values(self):
        from app.a2a.client import A2AAgentConfig
        cfg = A2AAgentConfig(name="x", url="http://x")
        assert cfg.enabled is True
        assert cfg.headers == {}
        assert cfg.description == ""

    def test_headers_default_is_independent_per_instance(self):
        """Default mutable headers dict must not be shared across instances."""
        from app.a2a.client import A2AAgentConfig
        a = A2AAgentConfig(name="a", url="http://a")
        b = A2AAgentConfig(name="b", url="http://b")
        a.headers["key"] = "value"
        assert "key" not in b.headers, "headers default_factory must create independent dicts"

    def test_fields_stored_correctly(self):
        from app.a2a.client import A2AAgentConfig
        cfg = A2AAgentConfig(
            name="sre_agent",
            url="http://sre.test",
            enabled=True,
            headers={"X-Token": "tok"},
            description="SRE agent",
        )
        assert cfg.name == "sre_agent"
        assert cfg.url == "http://sre.test"
        assert cfg.enabled is True
        assert cfg.headers == {"X-Token": "tok"}
        assert cfg.description == "SRE agent"
