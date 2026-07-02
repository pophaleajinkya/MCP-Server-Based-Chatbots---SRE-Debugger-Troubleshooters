"""Unit tests for app.store.redis_session_service.

Covers the pure-function helpers (_extract_state_delta, _merge_state,
_event_to_dict, _dict_to_event, _tcp_keepalive_options), the _redis_retry
decorator, and the async RedisSessionService CRUD methods.

No real Redis connection is required — RedisCluster is mocked throughout.
"""

import asyncio
import json
import sys
import socket
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Ensure google.adk stubs are in place for environments without the real package.
# Use _ensure_stub() (same pattern as conftest.py) instead of setdefault with
# MagicMock() — setdefault can still insert MagicMock objects for sub-modules
# that didn't exist yet, which corrupts isinstance() checks in other test files.
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
        "google",
        "google.adk",
        "google.adk.events",
        "google.adk.events.event",
        "google.adk.sessions",
        "google.adk.sessions.base_session_service",
        "google.adk.sessions.session",
        "google.adk.sessions.state",
    ):
        _ensure_stub(_stub)


# ---------------------------------------------------------------------------
# Import helpers under test (module-level functions — no Redis needed)
# ---------------------------------------------------------------------------
from google.adk.sessions.state import State

from app.store.redis_session_service import (
    _extract_state_delta,
    _merge_state,
    _event_to_dict,
    _dict_to_event,
    _tcp_keepalive_options,
    _redis_retry,
    _RETRYABLE_ERRORS,
)


# ===========================================================================
# _extract_state_delta
# ===========================================================================

class TestExtractStateDelta:

    def test_empty_state_returns_three_empty_dicts(self):
        app, user, sess = _extract_state_delta({})
        assert app == {} and user == {} and sess == {}

    def test_none_state_returns_three_empty_dicts(self):
        """Falsy input (empty dict) still yields three empty dicts."""
        app, user, sess = _extract_state_delta({})
        assert (app, user, sess) == ({}, {}, {})

    def test_app_prefix_populates_app_delta(self):
        state = {f"{State.APP_PREFIX}theme": "dark"}
        app, user, sess = _extract_state_delta(state)
        assert app == {"theme": "dark"}
        assert user == {} and sess == {}

    def test_user_prefix_populates_user_delta(self):
        state = {f"{State.USER_PREFIX}lang": "en"}
        app, user, sess = _extract_state_delta(state)
        assert user == {"lang": "en"}
        assert app == {} and sess == {}

    def test_temp_prefix_excluded_from_all(self):
        state = {f"{State.TEMP_PREFIX}scratch": 42}
        app, user, sess = _extract_state_delta(state)
        assert app == {} and user == {} and sess == {}

    def test_session_key_goes_to_session_delta(self):
        state = {"active_context": "health"}
        app, user, sess = _extract_state_delta(state)
        assert sess == {"active_context": "health"}
        assert app == {} and user == {}

    def test_mixed_state_splits_correctly(self):
        state = {
            f"{State.APP_PREFIX}version": "2.0",
            f"{State.USER_PREFIX}name": "alice",
            f"{State.TEMP_PREFIX}cache": "tmp",
            "turn_count": 5,
        }
        app, user, sess = _extract_state_delta(state)
        assert app == {"version": "2.0"}
        assert user == {"name": "alice"}
        assert sess == {"turn_count": 5}


# ===========================================================================
# _merge_state
# ===========================================================================

class TestMergeState:

    def test_empty_states_produce_empty_result(self):
        assert _merge_state({}, {}, {}) == {}

    def test_app_state_prefixed(self):
        merged = _merge_state({"theme": "dark"}, {}, {})
        assert merged == {f"{State.APP_PREFIX}theme": "dark"}

    def test_user_state_prefixed(self):
        merged = _merge_state({}, {"lang": "en"}, {})
        assert merged == {f"{State.USER_PREFIX}lang": "en"}

    def test_session_state_no_prefix(self):
        merged = _merge_state({}, {}, {"turn": 1})
        assert merged == {"turn": 1}

    def test_all_scopes_merged(self):
        merged = _merge_state({"a": 1}, {"b": 2}, {"c": 3})
        assert merged == {
            f"{State.APP_PREFIX}a": 1,
            f"{State.USER_PREFIX}b": 2,
            "c": 3,
        }

    def test_merge_does_not_mutate_session_state(self):
        sess = {"x": 10}
        _merge_state({"a": 1}, {}, sess)
        assert sess == {"x": 10}, "original session_state must not be mutated"


# ===========================================================================
# _event_to_dict / _dict_to_event
# ===========================================================================

class TestEventSerialization:

    def test_event_to_dict_calls_model_dump(self):
        mock_event = MagicMock()
        mock_event.model_dump.return_value = {"id": "evt-1", "author": "agent"}
        result = _event_to_dict(mock_event)
        mock_event.model_dump.assert_called_once_with(mode="json", exclude_none=True)
        assert result == {"id": "evt-1", "author": "agent"}

    def test_dict_to_event_calls_model_validate(self):
        data = {"id": "evt-2", "author": "user"}
        with patch("app.store.redis_session_service.Event") as MockEvent:
            MockEvent.model_validate.return_value = "parsed_event"
            result = _dict_to_event(data)
            MockEvent.model_validate.assert_called_once_with(data)
            assert result == "parsed_event"


# ===========================================================================
# _tcp_keepalive_options
# ===========================================================================

class TestTcpKeepaliveOptions:

    def test_returns_dict(self):
        opts = _tcp_keepalive_options()
        assert isinstance(opts, dict)

    def test_keys_are_integers(self):
        opts = _tcp_keepalive_options()
        for k in opts:
            assert isinstance(k, int), f"key {k} should be an integer socket constant"

    def test_keepintvl_present(self):
        opts = _tcp_keepalive_options()
        if hasattr(socket, "TCP_KEEPINTVL"):
            assert socket.TCP_KEEPINTVL in opts
            assert opts[socket.TCP_KEEPINTVL] == 10

    def test_keepcnt_present(self):
        opts = _tcp_keepalive_options()
        if hasattr(socket, "TCP_KEEPCNT"):
            assert socket.TCP_KEEPCNT in opts
            assert opts[socket.TCP_KEEPCNT] == 3


# ===========================================================================
# _redis_retry
# ===========================================================================

class TestRedisRetry:

    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        """When the wrapped function succeeds, the result is returned directly."""

        class FakeService:
            @_redis_retry
            async def do_thing(self):
                return "ok"

        settings = MagicMock()
        settings.redis_retry_attempts = 3
        settings.redis_retry_backoff_seconds = 0.0

        svc = FakeService()
        with patch("app.store.redis_session_service.get_settings", return_value=settings):
            result = await svc.do_thing()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        """Transient failure on first attempt, success on second."""
        from redis.exceptions import TimeoutError as RedisTimeoutError

        call_count = 0

        class FakeService:
            @_redis_retry
            async def do_thing(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RedisTimeoutError("timeout")
                return "recovered"

        settings = MagicMock()
        settings.redis_retry_attempts = 3
        settings.redis_retry_backoff_seconds = 0.0

        svc = FakeService()
        with patch("app.store.redis_session_service.get_settings", return_value=settings):
            result = await svc.do_thing()
        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_all_attempts_then_raises(self):
        """All retry attempts fail — the last error is raised."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        call_count = 0

        class FakeService:
            @_redis_retry
            async def do_thing(self):
                nonlocal call_count
                call_count += 1
                raise RedisConnectionError("down")

        settings = MagicMock()
        settings.redis_retry_attempts = 2
        settings.redis_retry_backoff_seconds = 0.0

        svc = FakeService()
        # Patch both the module-level import and the local import inside the wrapper
        with patch("app.store.redis_session_service.get_settings", return_value=settings), \
             patch("app.config.get_settings", return_value=settings):
            with pytest.raises(RedisConnectionError, match="down"):
                await svc.do_thing()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        """Errors not in _RETRYABLE_ERRORS must not be retried."""
        call_count = 0

        class FakeService:
            @_redis_retry
            async def do_thing(self):
                nonlocal call_count
                call_count += 1
                raise ValueError("bad input")

        settings = MagicMock()
        settings.redis_retry_attempts = 3
        settings.redis_retry_backoff_seconds = 0.0

        svc = FakeService()
        with patch("app.store.redis_session_service.get_settings", return_value=settings):
            with pytest.raises(ValueError, match="bad input"):
                await svc.do_thing()
        assert call_count == 1


# ===========================================================================
# RedisSessionService — constructor + CRUD
# ===========================================================================

def _mock_settings(**overrides):
    """Return a MagicMock that looks like app.config.Settings with Redis attrs."""
    defaults = dict(
        redis_host="localhost",
        redis_port=6379,
        redis_password="secret",
        redis_username="appuser",
        redis_ssl=False,
        redis_session_ttl_seconds=3600,
        redis_socket_connect_timeout=5,
        redis_socket_timeout=5,
        redis_max_connections=10,
        redis_retry_attempts=3,
        redis_retry_backoff_seconds=0.0,
    )
    defaults.update(overrides)
    settings = MagicMock()
    for k, v in defaults.items():
        setattr(settings, k, v)
    return settings


@pytest.fixture
def mock_redis():
    """Fixture returning an AsyncMock that stands in for RedisCluster."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.sadd = AsyncMock()
    redis.srem = AsyncMock()
    redis.zadd = AsyncMock()
    redis.zrem = AsyncMock()
    redis.hdel = AsyncMock()
    redis.hset = AsyncMock()
    redis.rpush = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.expire = AsyncMock()
    redis.smembers = AsyncMock(return_value=set())
    return redis


@pytest.fixture
def service(mock_redis):
    """Construct a RedisSessionService with mocked Redis and settings."""
    settings = _mock_settings()
    with patch("app.store.redis_session_service.get_settings", return_value=settings), \
         patch("app.store.redis_session_service.RedisCluster", return_value=mock_redis), \
         patch("app.store.redis_session_service.ClusterNode"):
        from app.store.redis_session_service import RedisSessionService
        svc = RedisSessionService()
    # Ensure the retry decorator also sees our fast settings
    svc._settings_patch = patch(
        "app.store.redis_session_service.get_settings", return_value=settings
    )
    svc._settings_patch.start()
    # Also patch the local import inside the wrapper function
    svc._config_patch = patch(
        "app.config.get_settings", return_value=settings
    )
    svc._config_patch.start()
    yield svc
    svc._settings_patch.stop()
    svc._config_patch.stop()


class TestRedisSessionServiceCreateSession:

    @pytest.mark.asyncio
    async def test_create_session_returns_session(self, service, mock_redis):
        session = await service.create_session(
            app_name="test_app",
            user_id="user1",
            session_id="sess1",
        )
        assert session.app_name == "test_app"
        assert session.user_id == "user1"
        assert session.id == "sess1"

    @pytest.mark.asyncio
    async def test_create_session_generates_id_when_none(self, service, mock_redis):
        session = await service.create_session(
            app_name="test_app",
            user_id="user1",
        )
        assert session.id  # non-empty UUID
        assert len(session.id) == 36  # uuid4 format

    @pytest.mark.asyncio
    async def test_create_session_persists_to_redis(self, service, mock_redis):
        await service.create_session(
            app_name="app", user_id="u", session_id="s",
        )
        # Verify at least one set call was made for the session doc
        assert mock_redis.set.await_count >= 1

    @pytest.mark.asyncio
    async def test_create_session_with_state_delta(self, service, mock_redis):
        state = {
            f"{State.APP_PREFIX}version": "1",
            "turn": 0,
        }
        session = await service.create_session(
            app_name="app", user_id="u", session_id="s", state=state,
        )
        # Session-scope key should be in the merged state
        assert "turn" in session.state or f"{State.APP_PREFIX}version" in session.state


class TestRedisSessionServiceGetSession:

    @pytest.mark.asyncio
    async def test_get_session_returns_none_when_missing(self, service, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        result = await service.get_session(
            app_name="app", user_id="u", session_id="s",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_returns_session_when_found(self, service, mock_redis):
        doc = json.dumps({"state": {"turn": 1}, "last_update_time": 100.0})
        # Calls to redis.get:
        #   1. _resolve_owner_id → direct key check
        #   2. get_session → session doc
        #   3. _get_app_state → app state (None ok)
        #   4. _get_user_state → user state (None ok)
        mock_redis.get = AsyncMock(side_effect=[doc, doc, None, None])
        session = await service.get_session(
            app_name="app", user_id="u", session_id="s",
        )
        assert session is not None
        assert session.id == "s"

    @pytest.mark.asyncio
    async def test_get_session_loads_events(self, service, mock_redis):
        doc = json.dumps({"state": {}, "last_update_time": 50.0})
        # 1. resolve_owner_id, 2. session doc, 3. app_state, 4. user_state
        mock_redis.get = AsyncMock(side_effect=[doc, doc, None, None])
        event_data = json.dumps({"id": "evt-1", "author": "agent"})
        mock_redis.lrange = AsyncMock(return_value=[event_data])

        with patch("app.store.redis_session_service._dict_to_event") as mock_d2e:
            mock_d2e.return_value = MagicMock()
            session = await service.get_session(
                app_name="app", user_id="u", session_id="s",
            )
            assert session is not None
            mock_d2e.assert_called_once()


class TestRedisSessionServiceDeleteSession:

    @pytest.mark.asyncio
    async def test_delete_session_removes_all_keys(self, service, mock_redis):
        await service.delete_session(
            app_name="app", user_id="u", session_id="s",
        )
        # Should call delete, srem, zrem, hdel
        assert mock_redis.delete.await_count >= 2
        mock_redis.srem.assert_awaited_once()
        mock_redis.zrem.assert_awaited_once()
        mock_redis.hdel.assert_awaited_once()


class TestRedisSessionServiceAppendEvent:

    @pytest.mark.asyncio
    async def test_append_event_partial_skips_persist(self, service, mock_redis):
        """Partial (streaming) events skip Redis persistence."""
        mock_event = MagicMock()
        mock_event.partial = True

        mock_session = MagicMock()
        mock_session.app_name = "app"
        mock_session.user_id = "u"
        mock_session.id = "s"

        with patch(
            "app.store.redis_session_service.BaseSessionService.append_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ):
            result = await service.append_event(mock_session, mock_event)
        assert result is mock_event
        # No redis.rpush for partial events
        mock_redis.rpush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_append_event_persists_non_partial(self, service, mock_redis):
        """Non-partial events are serialized and pushed to Redis."""
        mock_event = MagicMock()
        mock_event.partial = False
        mock_event.actions = None
        mock_event.content = None
        mock_event.model_dump.return_value = {"id": "evt-1"}

        mock_session = MagicMock()
        mock_session.app_name = "app"
        mock_session.user_id = "u"
        mock_session.id = "s"

        doc = json.dumps({"state": {}, "last_update_time": 1.0})
        mock_redis.get = AsyncMock(return_value=doc)

        with patch(
            "app.store.redis_session_service.BaseSessionService.append_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ):
            result = await service.append_event(mock_session, mock_event)
        assert result is mock_event
        mock_redis.rpush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_append_event_handles_missing_session(self, service, mock_redis):
        """If session doc is gone from Redis, append_event still delegates to super()."""
        mock_event = MagicMock()
        mock_event.partial = False
        mock_event.actions = None

        mock_session = MagicMock()
        mock_session.app_name = "app"
        mock_session.user_id = "u"
        mock_session.id = "gone"

        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.store.redis_session_service.BaseSessionService.append_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ):
            result = await service.append_event(mock_session, mock_event)
        assert result is mock_event
        mock_redis.rpush.assert_not_awaited()


# ===========================================================================
# _resolve_owner_id
# ===========================================================================

class TestResolveOwnerId:

    @pytest.mark.asyncio
    async def test_returns_uid_when_session_exists_directly(self, service, mock_redis):
        mock_redis.get = AsyncMock(return_value='{"state":{}}')
        owner = await service._resolve_owner_id("app", "user1", "sess1")
        assert owner == "user1"

    @pytest.mark.asyncio
    async def test_returns_owner_from_shared_key(self, service, mock_redis):
        """If session is not under uid, check shared key for owner."""
        shared_doc = json.dumps({"adk_user_id": "owner_alice"})
        # First get (direct session) → None, second get (shared key) → shared_doc
        mock_redis.get = AsyncMock(side_effect=[None, shared_doc])
        owner = await service._resolve_owner_id("app", "user2", "sess1")
        assert owner == "owner_alice"

    @pytest.mark.asyncio
    async def test_returns_owner_from_public_visibility(self, service, mock_redis):
        """If no shared key, check public visibility."""
        vis_doc = json.dumps({"public": True, "owner_id": "owner_bob"})
        # direct → None, shared → None, visibility → vis_doc
        mock_redis.get = AsyncMock(side_effect=[None, None, vis_doc])
        owner = await service._resolve_owner_id("app", "user3", "sess1")
        assert owner == "owner_bob"

    @pytest.mark.asyncio
    async def test_falls_back_to_uid(self, service, mock_redis):
        """No direct session, no shared, no public → return original uid."""
        mock_redis.get = AsyncMock(return_value=None)
        owner = await service._resolve_owner_id("app", "user4", "sess1")
        assert owner == "user4"
