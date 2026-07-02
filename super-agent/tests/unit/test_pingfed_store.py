"""Unit tests for app.pingfed.store — distributed bearer token store backed by Redis."""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakeSettings:
    """Minimal stand-in for app.config.Settings with auth-related fields."""

    redis_host = "redis.example.com"
    redis_port = 6379
    redis_password = "secret"
    redis_username = "user"
    redis_ssl = True
    redis_socket_timeout = 5
    redis_socket_connect_timeout = 5
    redis_max_connections = 10
    sso_username = "svc_user"
    sso_password = "svc_pass"
    auth_lock_ttl = 30
    auth_token_ttl = 3600
    auth_token_refresh_at = 1800


class _FakePipeline:
    """Collects pipeline commands and returns preset results on execute()."""

    def __init__(self, results):
        self._results = results

    def hget(self, key, field):
        pass

    def hset(self, key, mapping=None):
        pass

    def expire(self, key, ttl):
        pass

    def lpush(self, key, value):
        pass

    async def execute(self):
        return self._results


class _FakeRedis:
    """Async Redis mock with controllable pipeline results and key/value store."""

    def __init__(self, pipeline_results=None, get_value=None, set_result=True,
                 blpop_result=None):
        self._pipeline_results_queue = list(pipeline_results or [])
        self._get_value = get_value
        self._set_result = set_result
        self._blpop_result = blpop_result
        self.deleted_keys = []
        self.closed = False

    def pipeline(self):
        if self._pipeline_results_queue:
            return _FakePipeline(self._pipeline_results_queue.pop(0))
        return _FakePipeline([None, None, None])

    async def set(self, key, value, nx=False, ex=None):
        return self._set_result

    async def get(self, key):
        return self._get_value

    async def delete(self, key):
        self.deleted_keys.append(key)

    async def blpop(self, keys, timeout=0):
        return self._blpop_result

    async def aclose(self):
        self.closed = True


# ── _bare_host ────────────────────────────────────────────────────────────────


class TestBareHost:

    def test_bare_hostname(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("intl.logs.prod.walmart.com") == "intl.logs.prod.walmart.com"

    def test_with_scheme(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("https://intl.logs.prod.walmart.com") == "intl.logs.prod.walmart.com"

    def test_with_path(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("https://intl.logs.prod.walmart.com/api/v1") == "intl.logs.prod.walmart.com"

    def test_with_port(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("intl.logs.prod.walmart.com:443") == "intl.logs.prod.walmart.com"

    def test_with_scheme_and_port(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("https://intl.logs.prod.walmart.com:443/path") == "intl.logs.prod.walmart.com"

    def test_lowercases_hostname(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("INTL.LOGS.PROD.WALMART.COM") == "intl.logs.prod.walmart.com"

    def test_empty_raises_value_error(self):
        from app.pingfed.store import _bare_host
        with pytest.raises(ValueError, match="must not be empty"):
            _bare_host("")

    def test_whitespace_only_raises_value_error(self):
        from app.pingfed.store import _bare_host
        with pytest.raises(ValueError, match="must not be empty"):
            _bare_host("   ")

    def test_strips_whitespace(self):
        from app.pingfed.store import _bare_host
        assert _bare_host("  intl.logs.prod.walmart.com  ") == "intl.logs.prod.walmart.com"


# ── _keys ─────────────────────────────────────────────────────────────────────


class TestKeys:

    def test_correct_key_format(self):
        from app.pingfed.store import _keys
        token_key, lock_key, notify_key = _keys("intl.logs.prod.walmart.com")
        assert token_key == "agent:{auth:intl.logs.prod.walmart.com}:token"
        assert lock_key == "agent:{auth:intl.logs.prod.walmart.com}:lock"
        assert notify_key == "agent:{auth:intl.logs.prod.walmart.com}:notify"

    def test_hash_tags_present(self):
        from app.pingfed.store import _keys
        token_key, lock_key, notify_key = _keys("host.example.com")
        # All three keys share the same hash tag for Redis Cluster slot affinity
        for key in (token_key, lock_key, notify_key):
            assert "{auth:host.example.com}" in key

    def test_normalizes_url_input(self):
        from app.pingfed.store import _keys
        keys_bare = _keys("host.example.com")
        keys_url = _keys("https://host.example.com/api")
        assert keys_bare == keys_url

    def test_different_hosts_produce_different_keys(self):
        from app.pingfed.store import _keys
        assert _keys("host-a.example.com") != _keys("host-b.example.com")


# ── get_token ─────────────────────────────────────────────────────────────────


class TestGetToken:

    @pytest.mark.asyncio
    async def test_hot_path_returns_cached_token(self):
        """When a valid, non-stale token exists in Redis, return it immediately."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                ["valid-token", str(now + 3600), str(now + 1800)],
            ]
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()):
            token = await store.get_token("intl.logs.prod.walmart.com")

        assert token == "valid-token"

    @pytest.mark.asyncio
    async def test_stale_path_returns_token_and_triggers_background_refresh(self):
        """When token is past refresh_at but not expired, return it and kick off background refresh."""
        from app.pingfed import store

        now = time.time()
        # Token valid (expires in future) but stale (refresh_at in the past)
        fake_redis = _FakeRedis(
            pipeline_results=[
                ["stale-token", str(now + 600), str(now - 100)],
            ]
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "_background_refresh", AsyncMock()) as mock_refresh, \
             patch("asyncio.create_task") as mock_create_task:
            token = await store.get_token("intl.logs.prod.walmart.com")

        assert token == "stale-token"
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_cold_path_acquires_lock_and_logs_in(self):
        """When no token exists and this pod wins the lock, perform login."""
        from app.pingfed import store

        now = time.time()
        new_tokens = {
            "access_token": "fresh-token",
            "refresh_token": "fresh-refresh",
        }
        fake_redis = _FakeRedis(
            pipeline_results=[
                # First read: no token
                [None, "0", "0"],
                # Double-check after lock: still no token
                [None, "0", "0"],
                # _store_token pipeline
                [None, None, None, None],
            ],
            set_result=True,  # lock acquired
            get_value=store._pod_id,  # release_lock check
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "_do_login", AsyncMock(return_value=new_tokens)):
            token = await store.get_token("intl.logs.prod.walmart.com")

        assert token == "fresh-token"

    @pytest.mark.asyncio
    async def test_wait_path_blocks_until_notified(self):
        """When another pod holds the lock, this pod waits via BLPOP."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                # First read: no token
                [None, "0", "0"],
                # After BLPOP notification, read token fields
                ["peer-token", str(now + 3600), str(now + 1800)],
            ],
            set_result=False,  # lock NOT acquired (another pod has it)
            blpop_result=("notify_key", "1"),
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()):
            token = await store.get_token("intl.logs.prod.walmart.com")

        assert token == "peer-token"

    @pytest.mark.asyncio
    async def test_wait_path_timeout_raises_runtime_error(self):
        """When BLPOP times out and no token appears, raise RuntimeError."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                # First read: no token
                [None, "0", "0"],
                # After timeout: still no token
                [None, "0", "0"],
            ],
            set_result=False,  # lock not acquired
            blpop_result=None,  # BLPOP timeout
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()):
            with pytest.raises(RuntimeError, match="timed out"):
                await store.get_token("intl.logs.prod.walmart.com")

    @pytest.mark.asyncio
    async def test_cold_path_login_failure_raises(self):
        """When login returns no token, raise RuntimeError."""
        from app.pingfed import store

        fake_redis = _FakeRedis(
            pipeline_results=[
                [None, "0", "0"],
                [None, "0", "0"],
            ],
            set_result=True,
            get_value=store._pod_id,
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "_do_login", AsyncMock(return_value=None)):
            with pytest.raises(RuntimeError, match="SSO login returned no token"):
                await store.get_token("intl.logs.prod.walmart.com")


# ── get_full_tokens ───────────────────────────────────────────────────────────


class TestGetFullTokens:

    @pytest.mark.asyncio
    async def test_cached_tokens_returned(self):
        """When valid tokens exist in Redis, return both access and refresh."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                ["access-tok", "refresh-tok", str(now + 3600), str(now + 1800)],
            ]
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()):
            result = await store.get_full_tokens("intl.logs.prod.walmart.com")

        assert result == {"access_token": "access-tok", "refresh_token": "refresh-tok"}

    @pytest.mark.asyncio
    async def test_triggers_login_when_expired(self):
        """When no valid token, calls get_token() then re-reads full fields."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                # First _read_full_token_fields: expired
                [None, None, "0", "0"],
                # get_token -> _read_token_fields (no token)
                [None, "0", "0"],
                # get_token -> double-check after lock
                [None, "0", "0"],
                # _store_token pipeline
                [None, None, None, None],
                # Re-read full fields after login
                ["new-access", "new-refresh", str(now + 3600), str(now + 1800)],
            ],
            set_result=True,
            get_value=store._pod_id,
        )
        new_tokens = {"access_token": "new-access", "refresh_token": "new-refresh"}

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "_do_login", AsyncMock(return_value=new_tokens)):
            result = await store.get_full_tokens("intl.logs.prod.walmart.com")

        assert result == {"access_token": "new-access", "refresh_token": "new-refresh"}

    @pytest.mark.asyncio
    async def test_stale_triggers_background_refresh(self):
        """When token is stale but valid, return immediately and trigger refresh."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                # Stale but valid
                ["access-s", "refresh-s", str(now + 600), str(now - 100)],
            ]
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "_background_refresh", AsyncMock()), \
             patch("asyncio.create_task"):
            result = await store.get_full_tokens("intl.logs.prod.walmart.com")

        assert result == {"access_token": "access-s", "refresh_token": "refresh-s"}


# ── invalidate ────────────────────────────────────────────────────────────────


class TestInvalidate:

    @pytest.mark.asyncio
    async def test_deletes_token_key(self):
        from app.pingfed import store

        fake_redis = _FakeRedis()

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()):
            await store.invalidate("intl.logs.prod.walmart.com")

        expected_key = "agent:{auth:intl.logs.prod.walmart.com}:token"
        assert expected_key in fake_redis.deleted_keys

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        """invalidate() should not raise even if Redis fails."""
        from app.pingfed import store

        async def _failing_redis():
            raise ConnectionError("Redis down")

        with patch.object(store, "_get_redis", _failing_redis):
            # Should not raise
            await store.invalidate("intl.logs.prod.walmart.com")


# ── warm ──────────────────────────────────────────────────────────────────────


class TestWarm:

    @pytest.mark.asyncio
    async def test_no_op_when_token_exists(self):
        """When a valid token already exists, warm() does not call get_token()."""
        from app.pingfed import store

        now = time.time()
        fake_redis = _FakeRedis(
            pipeline_results=[
                ["warm-token", str(now + 3600), str(now + 1800)],
            ]
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "get_token", AsyncMock()) as mock_get:
            await store.warm("intl.logs.prod.walmart.com")

        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_get_token_when_missing(self):
        """When no valid token exists, warm() calls get_token() to acquire one."""
        from app.pingfed import store

        fake_redis = _FakeRedis(
            pipeline_results=[
                [None, "0", "0"],
            ]
        )

        with patch.object(store, "_get_redis", AsyncMock(return_value=fake_redis)), \
             patch.object(store, "get_settings", return_value=_FakeSettings()), \
             patch.object(store, "get_token", AsyncMock(return_value="new-tok")) as mock_get:
            await store.warm("intl.logs.prod.walmart.com")

        mock_get.assert_called_once_with("intl.logs.prod.walmart.com")


# ── close ─────────────────────────────────────────────────────────────────────


class TestClose:

    @pytest.mark.asyncio
    async def test_closes_redis_connection(self):
        from app.pingfed import store

        fake_redis = _FakeRedis()
        original = store._redis

        try:
            store._redis = fake_redis
            await store.close()
            assert fake_redis.closed is True
            assert store._redis is None
        finally:
            store._redis = original

    @pytest.mark.asyncio
    async def test_close_noop_when_no_redis(self):
        from app.pingfed import store

        original = store._redis
        try:
            store._redis = None
            # Should not raise
            await store.close()
            assert store._redis is None
        finally:
            store._redis = original

    @pytest.mark.asyncio
    async def test_close_swallows_exceptions(self):
        """close() should not raise even if aclose() fails."""
        from app.pingfed import store

        class _FailingRedis:
            async def aclose(self):
                raise ConnectionError("already closed")

        original = store._redis
        try:
            store._redis = _FailingRedis()
            # Should not raise
            await store.close()
            assert store._redis is None
        finally:
            store._redis = original
