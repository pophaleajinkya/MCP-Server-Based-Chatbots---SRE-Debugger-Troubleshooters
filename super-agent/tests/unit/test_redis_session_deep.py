"""Deep unit tests for app.store.redis_session_service.

Comprehensive coverage of:
  - _redis_retry decorator (exponential backoff, cluster re-init)
  - _extract_state_delta / _merge_state helpers
  - _resolve_owner_id (shared/public session resolution)
  - create_session / get_session / list_sessions / delete_session
  - append_event (state deltas, title caching, TTL refresh)
  - _tcp_keepalive_options (OS-specific constants)

No real Redis connection is required — RedisCluster is fully mocked.
"""

import asyncio
import json
import socket
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Ensure google.adk stubs are in place for environments without the real package.
try:
    import google.adk  # noqa: F401
except ImportError:
    def _ensure_stub(dotted_name: str):
        parts = dotted_name.split(".")
        for depth in range(1, len(parts) + 1):
            name = ".".join(parts[:depth])
            if name not in sys.modules:
                mod = ModuleType(name)
                sys.modules[name] = mod
                if depth > 1:
                    parent_name = ".".join(parts[:depth - 1])
                    setattr(sys.modules[parent_name], parts[depth - 1], mod)

    for _stub in (
        "google", "google.adk", "google.adk.agents",
        "google.adk.agents.invocation_context",
        "google.adk.code_executors", "google.adk.code_executors.code_execution_utils",
        "google.adk.models", "google.adk.models.lite_llm",
        "google.adk.tools", "google.adk.tools.mcp_tool",
        "google.adk.tools.mcp_tool.mcp_toolset",
    ):
        _ensure_stub(_stub)
    sys.modules["google.adk.agents"].Agent = MagicMock
    sys.modules["google.adk.agents.invocation_context"].InvocationContext = MagicMock
    sys.modules["google.adk.code_executors"].UnsafeLocalCodeExecutor = MagicMock
    sys.modules["google.adk.code_executors.code_execution_utils"].CodeExecutionInput = MagicMock
    sys.modules["google.adk.code_executors.code_execution_utils"].CodeExecutionResult = MagicMock
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].MCPToolset = MagicMock
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].SseConnectionParams = MagicMock
    sys.modules["google.adk.tools.mcp_tool.mcp_toolset"].StreamableHTTPConnectionParams = MagicMock

    class _StubLiteLLMClient:
        pass
    sys.modules["google.adk.models.lite_llm"].LiteLlm = MagicMock
    sys.modules["google.adk.models.lite_llm"].LiteLLMClient = _StubLiteLLMClient

from google.adk.sessions.state import State
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.events.event import Event
from google.adk.sessions.session import Session

from redis.exceptions import (
    RedisClusterException,
    TimeoutError as RedisTimeoutError,
    ConnectionError as RedisConnectionError,
)

from app.store.redis_session_service import (
    _extract_state_delta,
    _merge_state,
    _event_to_dict,
    _dict_to_event,
    _tcp_keepalive_options,
    _redis_retry,
    RedisSessionService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "app.store.redis_session_service"


def _fake_settings(**overrides):
    """Build a MagicMock Settings with sensible defaults for tests."""
    defaults = dict(
        redis_host="127.0.0.1",
        redis_port=6379,
        redis_password="pass",
        redis_username="appuser",
        redis_ssl=False,
        redis_socket_connect_timeout=5,
        redis_socket_timeout=5,
        redis_max_connections=10,
        redis_session_ttl_seconds=3600,
        redis_retry_attempts=3,
        redis_retry_backoff_seconds=0.5,
    )
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _make_service(mock_redis=None, ttl=None, settings_overrides=None):
    """Instantiate RedisSessionService with a mocked RedisCluster."""
    fs = _fake_settings(**(settings_overrides or {}))
    mock_r = mock_redis if mock_redis is not None else AsyncMock()
    with patch(f"{MODULE}.RedisCluster", return_value=mock_r) as _mc, \
         patch(f"{MODULE}.ClusterNode"), \
         patch(f"{MODULE}.get_settings", return_value=fs):
        svc = RedisSessionService(ttl_seconds=ttl)
    return svc, mock_r, fs


def _make_event(role="model", text="hello", partial=False, state_delta=None):
    """Create a minimal Event using model_validate to get a real Event object."""
    parts = [{"text": text}] if text else []
    data = {
        "invocation_id": "inv-1",
        "author": role,
        "content": {"role": role, "parts": parts} if parts else None,
        "partial": partial,
    }
    if state_delta:
        data["actions"] = {"state_delta": state_delta}
    return Event.model_validate(data)


# ═══════════════════════════════════════════════════════════════════════════════
# _redis_retry decorator
# ═══════════════════════════════════════════════════════════════════════════════

class TestRedisRetry:
    """Tests for the _redis_retry exponential-backoff decorator."""

    @pytest.mark.asyncio
    async def test_01_succeeds_on_first_try(self):
        """Function returns immediately when no error occurs."""

        class Svc:
            _redis = AsyncMock()

            @_redis_retry
            async def do_work(self):
                return "ok"

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            result = await Svc().do_work()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_02_fails_once_succeeds_on_retry(self):
        call_count = 0

        class Svc:
            _redis = AsyncMock()

            @_redis_retry
            async def do_work(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RedisTimeoutError("timeout")
                return "ok"

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()), \
             patch(f"{MODULE}.asyncio.sleep", new_callable=AsyncMock):
            result = await Svc().do_work()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_03_fails_all_attempts_cluster_reinit_attempted(self):
        mock_redis = AsyncMock()
        mock_redis.initialize = AsyncMock(side_effect=Exception("reinit failed"))

        class Svc:
            _redis = mock_redis

            @_redis_retry
            async def do_work(self):
                raise RedisClusterException("cluster down")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings(redis_retry_attempts=2)), \
             patch(f"{MODULE}.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RedisClusterException):
                await Svc().do_work()
        mock_redis.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_04_cluster_reinit_succeeds_one_more_try(self):
        """After exhausting retries, re-init succeeds and the fn is tried once more."""
        call_count = 0
        mock_redis = AsyncMock()
        mock_redis.initialize = AsyncMock()

        class Svc:
            _redis = mock_redis

            @_redis_retry
            async def do_work(self):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise RedisConnectionError("gone")
                return "recovered"

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings(redis_retry_attempts=2)), \
             patch(f"{MODULE}.asyncio.sleep", new_callable=AsyncMock):
            result = await Svc().do_work()
        assert result == "recovered"
        # 2 normal attempts + 1 after reinit = 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_05_cluster_reinit_fails_original_error_raised(self):
        mock_redis = AsyncMock()
        mock_redis.initialize = AsyncMock(side_effect=Exception("reinit boom"))

        class Svc:
            _redis = mock_redis

            @_redis_retry
            async def do_work(self):
                raise RedisTimeoutError("the original")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings(redis_retry_attempts=1)), \
             patch(f"{MODULE}.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RedisTimeoutError, match="the original"):
                await Svc().do_work()

    @pytest.mark.asyncio
    async def test_06_non_retryable_error_raised_immediately(self):
        call_count = 0

        class Svc:
            _redis = AsyncMock()

            @_redis_retry
            async def do_work(self):
                nonlocal call_count
                call_count += 1
                raise ValueError("not retryable")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            with pytest.raises(ValueError, match="not retryable"):
                await Svc().do_work()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_07_exponential_backoff_timing(self):
        """Delay doubles on each retry."""
        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        call_count = 0

        class Svc:
            _redis = AsyncMock()
            _redis.initialize = AsyncMock()

            @_redis_retry
            async def do_work(self):
                nonlocal call_count
                call_count += 1
                if call_count <= 3:
                    raise RedisTimeoutError("boom")
                return "done"

        with patch("app.config.get_settings", return_value=_fake_settings(
            redis_retry_attempts=4, redis_retry_backoff_seconds=1.0
        )), patch(f"{MODULE}.asyncio.sleep", side_effect=fake_sleep):
            await Svc().do_work()
        # Attempts 1,2,3 fail -> sleeps of 1.0, 2.0, 4.0
        assert sleep_calls == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_08_max_attempts_from_settings(self):
        """Retry count comes from settings, not hardcoded."""
        call_count = 0

        class Svc:
            _redis = AsyncMock()
            _redis.initialize = AsyncMock(side_effect=Exception("reinit fail"))

            @_redis_retry
            async def do_work(self):
                nonlocal call_count
                call_count += 1
                raise RedisTimeoutError("boom")

        with patch("app.config.get_settings", return_value=_fake_settings(redis_retry_attempts=5)), \
             patch(f"{MODULE}.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RedisTimeoutError):
                await Svc().do_work()
        # 5 normal attempts; on last attempt reinit fails so fn is NOT retried again
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_09_backoff_from_settings(self):
        """Initial backoff comes from settings."""
        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        call_count = 0

        class Svc:
            _redis = AsyncMock()
            _redis.initialize = AsyncMock()

            @_redis_retry
            async def do_work(self):
                nonlocal call_count
                call_count += 1
                if call_count <= 1:
                    raise RedisTimeoutError("boom")
                return "ok"

        with patch("app.config.get_settings", return_value=_fake_settings(
            redis_retry_attempts=3, redis_retry_backoff_seconds=0.25
        )), patch(f"{MODULE}.asyncio.sleep", side_effect=fake_sleep):
            await Svc().do_work()
        assert sleep_calls[0] == 0.25


# ═══════════════════════════════════════════════════════════════════════════════
# _extract_state_delta
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractStateDelta:

    def test_10_empty_state(self):
        app, user, sess = _extract_state_delta({})
        assert app == {} and user == {} and sess == {}

    def test_11_only_app_keys(self):
        app, user, sess = _extract_state_delta({f"{State.APP_PREFIX}theme": "dark"})
        assert app == {"theme": "dark"}
        assert user == {} and sess == {}

    def test_12_only_user_keys(self):
        app, user, sess = _extract_state_delta({f"{State.USER_PREFIX}lang": "en"})
        assert user == {"lang": "en"}
        assert app == {} and sess == {}

    def test_13_only_session_keys(self):
        app, user, sess = _extract_state_delta({"count": 5})
        assert sess == {"count": 5}
        assert app == {} and user == {}

    def test_14_mixed_keys(self):
        state = {
            f"{State.APP_PREFIX}a": 1,
            f"{State.USER_PREFIX}b": 2,
            "c": 3,
        }
        app, user, sess = _extract_state_delta(state)
        assert app == {"a": 1}
        assert user == {"b": 2}
        assert sess == {"c": 3}

    def test_15_temp_keys_excluded(self):
        state = {f"{State.TEMP_PREFIX}scratch": 42, "keep": 1}
        app, user, sess = _extract_state_delta(state)
        assert sess == {"keep": 1}
        assert app == {} and user == {}

    def test_16_none_state(self):
        app, user, sess = _extract_state_delta(None)
        assert app == {} and user == {} and sess == {}


# ═══════════════════════════════════════════════════════════════════════════════
# _merge_state
# ═══════════════════════════════════════════════════════════════════════════════

class TestMergeState:

    def test_17_all_empty(self):
        assert _merge_state({}, {}, {}) == {}

    def test_18_session_only(self):
        assert _merge_state({}, {}, {"x": 1}) == {"x": 1}

    def test_19_app_state_adds_prefixed_keys(self):
        merged = _merge_state({"theme": "dark"}, {}, {})
        assert merged == {f"{State.APP_PREFIX}theme": "dark"}

    def test_20_user_state_adds_prefixed_keys(self):
        merged = _merge_state({}, {"lang": "en"}, {})
        assert merged == {f"{State.USER_PREFIX}lang": "en"}

    def test_21_overlap_both_present(self):
        # session has "theme", app also contributes "app:theme"
        merged = _merge_state({"theme": "dark"}, {}, {"theme": "light"})
        assert merged["theme"] == "light"
        assert merged[f"{State.APP_PREFIX}theme"] == "dark"


# ═══════════════════════════════════════════════════════════════════════════════
# _resolve_owner_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveOwnerId:

    @pytest.mark.asyncio
    async def test_22_session_exists_under_requested_uid(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value='{"state":{}}')
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_23_shared_owner_found(self):
        svc, mock_r, _ = _make_service()
        # First call: direct lookup returns None; second: shared key; third: visibility
        mock_r.get = AsyncMock(side_effect=[
            None,
            json.dumps({"owner_id": "owner-abc"}),
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "owner-abc"

    @pytest.mark.asyncio
    async def test_24_public_owner_found(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(side_effect=[
            None,  # direct
            None,  # shared
            json.dumps({"public": True, "owner_id": "pub-owner"}),  # visibility
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "pub-owner"

    @pytest.mark.asyncio
    async def test_25_neither_shared_nor_public_fallback(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_26_shared_malformed_json_fallback(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(side_effect=[
            None,              # direct
            "not-valid-json",  # shared (malformed)
            None,              # visibility
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_27_visibility_malformed_json_fallback(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(side_effect=[
            None,
            None,
            "{bad json",  # visibility malformed
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_28_shared_no_owner_id_fallback(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(side_effect=[
            None,
            json.dumps({"permission": "read"}),  # no owner_id
            None,
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_29_public_false_fallback(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(side_effect=[
            None,
            None,
            json.dumps({"public": False, "owner_id": "ignored"}),
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_30_shared_takes_precedence_over_visibility(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(side_effect=[
            None,
            json.dumps({"owner_id": "shared-owner"}),
            # visibility would never be checked
        ])
        result = await svc._resolve_owner_id("app", "user1", "sid1")
        assert result == "shared-owner"


# ═══════════════════════════════════════════════════════════════════════════════
# create_session
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateSession:

    @pytest.mark.asyncio
    async def test_31_auto_generated_session_id(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)  # no existing state
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(app_name="app", user_id="u1")
        assert session.id  # UUID generated
        assert len(session.id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_32_explicit_session_id(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", session_id="my-id"
            )
        assert session.id == "my-id"

    @pytest.mark.asyncio
    async def test_33_whitespace_session_id_stripped(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", session_id="  my-id  "
            )
        assert session.id == "my-id"

    @pytest.mark.asyncio
    async def test_34_empty_session_id_auto_generates(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", session_id="   "
            )
        assert len(session.id) == 36

    @pytest.mark.asyncio
    async def test_35_app_delta_persisted(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        state = {f"{State.APP_PREFIX}theme": "dark"}
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", state=state
            )
        assert session.state[f"{State.APP_PREFIX}theme"] == "dark"

    @pytest.mark.asyncio
    async def test_36_user_delta_persisted(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        state = {f"{State.USER_PREFIX}lang": "fr"}
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", state=state
            )
        assert session.state[f"{State.USER_PREFIX}lang"] == "fr"

    @pytest.mark.asyncio
    async def test_37_session_delta_in_doc(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        state = {"count": 42}
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", state=state
            )
        assert session.state["count"] == 42

    @pytest.mark.asyncio
    async def test_38_no_initial_state(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(app_name="app", user_id="u1")
        assert session.state == {}

    @pytest.mark.asyncio
    async def test_39_semaphore_limits_concurrency(self):
        """Semaphore(10) is used to gate parallel writes."""
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()), \
             patch(f"{MODULE}.asyncio.Semaphore") as mock_sem_cls:
            mock_sem = AsyncMock()
            mock_sem.__aenter__ = AsyncMock()
            mock_sem.__aexit__ = AsyncMock()
            mock_sem_cls.return_value = mock_sem
            await svc.create_session(app_name="app", user_id="u1")
        mock_sem_cls.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_40_index_updated_with_correct_score(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.set = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.sadd = AsyncMock()
        mock_r.zadd = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.create_session(
                app_name="app", user_id="u1", session_id="sid1"
            )
        # SADD called with the session id
        mock_r.sadd.assert_awaited()
        # ZADD called with session id as member
        mock_r.zadd.assert_awaited()
        zadd_args = mock_r.zadd.call_args
        # The dict arg should map session_id to a float timestamp
        mapping = zadd_args[0][1]
        assert "sid1" in mapping
        assert isinstance(mapping["sid1"], float)


# ═══════════════════════════════════════════════════════════════════════════════
# get_session
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSession:

    @pytest.mark.asyncio
    async def test_41_session_found_returns_full_session(self):
        svc, mock_r, _ = _make_service()
        doc = json.dumps({"state": {"count": 1}, "last_update_time": 100.0})
        event_data = json.dumps(_event_to_dict(_make_event(text="hi")))
        # get is called for: _resolve_owner_id(direct), get_session(sk),
        # _get_app_state, _get_user_state
        mock_r.get = AsyncMock(side_effect=[
            doc,   # _resolve_owner_id direct lookup -> found
            doc,   # get_session main get
            None,  # _get_app_state
            None,  # _get_user_state
        ])
        mock_r.lrange = AsyncMock(return_value=[event_data])

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.get_session(
                app_name="app", user_id="u1", session_id="sid1"
            )
        assert session is not None
        assert session.id == "sid1"
        assert len(session.events) == 1
        assert session.state["count"] == 1

    @pytest.mark.asyncio
    async def test_42_session_not_found_returns_none(self):
        svc, mock_r, _ = _make_service()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.lrange = AsyncMock(return_value=[])

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.get_session(
                app_name="app", user_id="u1", session_id="sid1"
            )
        assert session is None

    @pytest.mark.asyncio
    async def test_43_session_with_no_events(self):
        svc, mock_r, _ = _make_service()
        doc = json.dumps({"state": {}, "last_update_time": 50.0})
        mock_r.get = AsyncMock(side_effect=[doc, doc, None, None])
        mock_r.lrange = AsyncMock(return_value=[])

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.get_session(
                app_name="app", user_id="u1", session_id="sid1"
            )
        assert session.events == []

    @pytest.mark.asyncio
    async def test_44_after_timestamp_filter(self):
        svc, mock_r, _ = _make_service()
        doc = json.dumps({"state": {}, "last_update_time": 50.0})
        e1 = _make_event(text="old")
        e1.timestamp = 10.0
        e2 = _make_event(text="new")
        e2.timestamp = 100.0
        mock_r.get = AsyncMock(side_effect=[doc, doc, None, None])
        mock_r.lrange = AsyncMock(return_value=[
            json.dumps(_event_to_dict(e1)),
            json.dumps(_event_to_dict(e2)),
        ])

        config = GetSessionConfig(after_timestamp=50.0)
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.get_session(
                app_name="app", user_id="u1", session_id="sid1", config=config
            )
        assert len(session.events) == 1
        assert session.events[0].timestamp >= 50.0

    @pytest.mark.asyncio
    async def test_45_num_recent_events_filter(self):
        svc, mock_r, _ = _make_service()
        doc = json.dumps({"state": {}, "last_update_time": 50.0})
        events_raw = [
            json.dumps(_event_to_dict(_make_event(text=f"e{i}")))
            for i in range(5)
        ]
        mock_r.get = AsyncMock(side_effect=[doc, doc, None, None])
        mock_r.lrange = AsyncMock(return_value=events_raw)

        config = GetSessionConfig(num_recent_events=2)
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.get_session(
                app_name="app", user_id="u1", session_id="sid1", config=config
            )
        assert len(session.events) == 2

    @pytest.mark.asyncio
    async def test_46_both_config_filters(self):
        svc, mock_r, _ = _make_service()
        doc = json.dumps({"state": {}, "last_update_time": 50.0})
        events = []
        for i in range(5):
            e = _make_event(text=f"e{i}")
            e.timestamp = float(i * 10)
            events.append(e)
        events_raw = [json.dumps(_event_to_dict(e)) for e in events]
        mock_r.get = AsyncMock(side_effect=[doc, doc, None, None])
        mock_r.lrange = AsyncMock(return_value=events_raw)

        # after_timestamp=15 filters to e2(20), e3(30), e4(40); num_recent=2 keeps e3, e4
        config = GetSessionConfig(after_timestamp=15.0, num_recent_events=2)
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            session = await svc.get_session(
                app_name="app", user_id="u1", session_id="sid1", config=config
            )
        assert len(session.events) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# list_sessions
# ═══════════════════════════════════════════════════════════════════════════════

class TestListSessions:

    @pytest.mark.asyncio
    async def test_47_multiple_sessions_returned(self):
        svc, mock_r, _ = _make_service()
        mock_r.smembers = AsyncMock(return_value={"s1", "s2"})
        mock_r.get = AsyncMock(side_effect=[
            json.dumps({"state": {}, "last_update_time": 1.0}),
            json.dumps({"state": {}, "last_update_time": 2.0}),
        ])

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            resp = await svc.list_sessions(app_name="app", user_id="u1")
        assert len(resp.sessions) == 2

    @pytest.mark.asyncio
    async def test_48_empty_index(self):
        svc, mock_r, _ = _make_service()
        mock_r.smembers = AsyncMock(return_value=set())

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            resp = await svc.list_sessions(app_name="app", user_id="u1")
        assert resp.sessions == []

    @pytest.mark.asyncio
    async def test_49_stale_index_entry_skipped(self):
        svc, mock_r, _ = _make_service()
        mock_r.smembers = AsyncMock(return_value={"s1", "s2"})
        mock_r.get = AsyncMock(side_effect=[
            json.dumps({"state": {}, "last_update_time": 1.0}),
            None,  # s2 expired
        ])

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            resp = await svc.list_sessions(app_name="app", user_id="u1")
        assert len(resp.sessions) == 1

    @pytest.mark.asyncio
    async def test_50_no_last_update_time_defaults_to_zero(self):
        svc, mock_r, _ = _make_service()
        mock_r.smembers = AsyncMock(return_value={"s1"})
        mock_r.get = AsyncMock(return_value=json.dumps({"state": {}}))

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            resp = await svc.list_sessions(app_name="app", user_id="u1")
        assert resp.sessions[0].last_update_time == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# delete_session
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteSession:

    @pytest.mark.asyncio
    async def test_51_all_keys_deleted_in_parallel(self):
        svc, mock_r, _ = _make_service()
        mock_r.delete = AsyncMock()
        mock_r.srem = AsyncMock()
        mock_r.zrem = AsyncMock()
        mock_r.hdel = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.delete_session(app_name="app", user_id="u1", session_id="sid1")

        assert mock_r.delete.await_count == 3  # session, events, ui_events

    @pytest.mark.asyncio
    async def test_52_srem_zrem_called_on_index_keys(self):
        svc, mock_r, _ = _make_service()
        mock_r.delete = AsyncMock()
        mock_r.srem = AsyncMock()
        mock_r.zrem = AsyncMock()
        mock_r.hdel = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.delete_session(app_name="app", user_id="u1", session_id="sid1")

        mock_r.srem.assert_awaited_once()
        mock_r.zrem.assert_awaited_once()
        # Verify session_id passed to both
        srem_args = mock_r.srem.call_args[0]
        assert "sid1" in srem_args
        zrem_args = mock_r.zrem.call_args[0]
        assert "sid1" in zrem_args

    @pytest.mark.asyncio
    async def test_53_hdel_called_on_meta_key(self):
        svc, mock_r, _ = _make_service()
        mock_r.delete = AsyncMock()
        mock_r.srem = AsyncMock()
        mock_r.zrem = AsyncMock()
        mock_r.hdel = AsyncMock()

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.delete_session(app_name="app", user_id="u1", session_id="sid1")

        mock_r.hdel.assert_awaited_once()
        hdel_args = mock_r.hdel.call_args[0]
        assert "sid1" in hdel_args


# ═══════════════════════════════════════════════════════════════════════════════
# append_event
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppendEvent:

    def _setup_service(self):
        svc, mock_r, _ = _make_service()
        mock_r.set = AsyncMock()
        mock_r.zadd = AsyncMock()
        mock_r.hset = AsyncMock()
        mock_r.rpush = AsyncMock()
        mock_r.expire = AsyncMock()
        return svc, mock_r

    def _make_session(self, sid="sid1"):
        return Session(
            app_name="app", user_id="u1", id=sid,
            state={}, last_update_time=1.0,
        )

    @pytest.mark.asyncio
    async def test_54_partial_event_skips_persistence(self):
        svc, mock_r = self._setup_service()
        mock_r.get = AsyncMock()  # should not be called
        session = self._make_session()
        event = _make_event(partial=True)

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            result = await svc.append_event(session=session, event=event)
        # Redis get should not have been called for the session doc
        mock_r.rpush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_55_non_partial_persisted(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        event = _make_event(text="real event")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        mock_r.rpush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_56_session_not_found_logs_warning(self):
        svc, mock_r = self._setup_service()
        mock_r.get = AsyncMock(return_value=None)
        session = self._make_session()
        event = _make_event(text="event")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()), \
             patch(f"{MODULE}.log") as mock_log:
            await svc.append_event(session=session, event=event)
        mock_log.warning.assert_called_once()
        mock_r.rpush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_57_state_delta_updates(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {"existing": 1}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(side_effect=[
            doc,   # main get
            None,  # _get_app_state
        ])
        session = self._make_session()
        state_delta = {f"{State.APP_PREFIX}new_key": "val", "sess_key": "v2"}
        event = _make_event(text="delta", state_delta=state_delta)

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        # set should have been called (for app state + session doc)
        assert mock_r.set.await_count >= 2

    @pytest.mark.asyncio
    async def test_58_first_user_message_title_cached(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        event = _make_event(role="user", text="What is the weather?")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        mock_r.hset.assert_awaited_once()
        hset_args = mock_r.hset.call_args[0]
        assert "sid1" in hset_args
        assert "What is the weather?" in hset_args[2]

    @pytest.mark.asyncio
    async def test_59_subsequent_user_message_no_title_overwrite(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({
            "state": {}, "last_update_time": 1.0, "title": "First question"
        })
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        event = _make_event(role="user", text="Second question")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        mock_r.hset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_60_unicode_title_truncated(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        long_text = "\u4e16\u754c" * 50  # 100 chars of unicode
        event = _make_event(role="user", text=long_text)

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        mock_r.hset.assert_awaited_once()
        title = mock_r.hset.call_args[0][2]
        # 60 chars + ellipsis
        assert len(title) == 61  # 60 chars + 1 ellipsis char

    @pytest.mark.asyncio
    async def test_61_zset_score_updated_with_timestamp(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        event = _make_event(text="event")

        before = time.time()
        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        after = time.time()

        mock_r.zadd.assert_awaited()
        zadd_args = mock_r.zadd.call_args[0]
        mapping = zadd_args[1]
        score = mapping["sid1"]
        assert before <= score <= after

    @pytest.mark.asyncio
    async def test_62_meta_hash_updated_when_title_set(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        event = _make_event(role="user", text="My title")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        mock_r.hset.assert_awaited_once()
        # First arg is the meta key, should contain session_meta
        meta_key = mock_r.hset.call_args[0][0]
        assert "session_meta" in meta_key

    @pytest.mark.asyncio
    async def test_63_ttl_refreshed_on_all_keys(self):
        svc, mock_r = self._setup_service()
        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_r.get = AsyncMock(return_value=doc)
        session = self._make_session()
        event = _make_event(text="event")

        with patch(f"{MODULE}.get_settings", return_value=_fake_settings()):
            await svc.append_event(session=session, event=event)
        # _refresh_ttl calls expire on 6 keys
        assert mock_r.expire.await_count == 6


# ═══════════════════════════════════════════════════════════════════════════════
# _tcp_keepalive_options
# ═══════════════════════════════════════════════════════════════════════════════

class TestTcpKeepaliveOptions:

    def test_64_returns_dict_with_available_constants(self):
        opts = _tcp_keepalive_options()
        assert isinstance(opts, dict)
        # TCP_KEEPINTVL and TCP_KEEPCNT should be available everywhere
        assert socket.TCP_KEEPINTVL in opts
        assert socket.TCP_KEEPCNT in opts

    def test_65_missing_tcp_keepidle_omitted(self):
        """When TCP_KEEPIDLE is absent (e.g. macOS), it is silently omitted."""
        has_keepidle = hasattr(socket, "TCP_KEEPIDLE")

        if has_keepidle:
            # Linux: simulate removal by making getattr return None
            import types
            fake_socket = types.ModuleType("socket")
            fake_socket.TCP_KEEPINTVL = socket.TCP_KEEPINTVL
            fake_socket.TCP_KEEPCNT = socket.TCP_KEEPCNT
            # Deliberately omit TCP_KEEPIDLE
            with patch(f"{MODULE}.socket", fake_socket):
                opts = _tcp_keepalive_options()
            # The KEEPIDLE constant value should not be a key
            assert socket.TCP_KEEPIDLE not in opts
        else:
            # macOS: TCP_KEEPIDLE already absent
            opts = _tcp_keepalive_options()
            assert isinstance(opts, dict)
            # Should still have the other two
            assert socket.TCP_KEEPINTVL in opts
            assert socket.TCP_KEEPCNT in opts
