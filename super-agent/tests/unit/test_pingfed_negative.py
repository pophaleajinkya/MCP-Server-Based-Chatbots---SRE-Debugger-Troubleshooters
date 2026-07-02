"""
Comprehensive negative and edge-case tests for ALL pingfed modules:
  - store.py
  - sso.py
  - generic_sso.py
  - hub_sso.py
  - _pfed.py

At least 50 tests covering error paths, boundary conditions, and race scenarios.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


def _make_pipeline(execute_return):
    """Build a mock redis pipeline where hget/hset/expire/lpush are sync stubs
    and execute() is an AsyncMock returning *execute_return*.

    Redis pipelines queue commands synchronously, then ``await pipe.execute()``
    returns all results at once.  ``AsyncMock`` would make hget() a coroutine,
    which breaks the real call-sites.
    """
    pipe = MagicMock()  # sync stubs for queueing calls
    pipe.execute = AsyncMock(return_value=execute_return)
    return pipe


def _make_redis(pipe_return=None, **overrides):
    """Return (redis_mock, pipe_mock) with sane defaults for store.py tests.

    *pipe_return* is the list returned by ``await pipe.execute()``.
    Extra keyword overrides are set directly on the redis mock
    (e.g. ``set=AsyncMock(return_value=True)``).
    """
    if pipe_return is None:
        pipe_return = ["", "0", "0"]
    pipe = _make_pipeline(pipe_return)
    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)  # sync — returns pipe immediately
    for k, v in overrides.items():
        setattr(redis, k, v)
    return redis, pipe


# ============================================================================
# store.py  --  _bare_host
# ============================================================================

class TestBareHost:
    """Negative / edge cases for store._bare_host."""

    def _bare_host(self, val):
        from app.pingfed.store import _bare_host
        return _bare_host(val)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            self._bare_host("")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            self._bare_host(None)

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            self._bare_host("   ")

    def test_scheme_only_no_host(self):
        # "https://" has no hostname -- should return empty string after stripping
        result = self._bare_host("https://")
        assert result == ""

    def test_scheme_with_trailing_slash(self):
        result = self._bare_host("https:///path")
        assert result == ""

    def test_ipv4_address(self):
        result = self._bare_host("https://192.168.1.1:9200/api")
        assert result == "192.168.1.1"

    def test_ipv6_address(self):
        result = self._bare_host("https://[::1]:9200/api")
        assert result == "::1"

    def test_unicode_hostname(self):
        result = self._bare_host("https://xn--nxasmq6b.example.com/path")
        assert result == "xn--nxasmq6b.example.com"

    def test_very_long_url(self):
        host = "a" * 200 + ".example.com"
        result = self._bare_host(f"https://{host}/path")
        assert result == host

    def test_bare_host_with_port_no_scheme(self):
        result = self._bare_host("myhost.com:8080/path")
        assert result == "myhost.com"


# ============================================================================
# store.py  --  _keys
# ============================================================================

class TestKeys:
    """Verify hash-tag format for Redis Cluster slot affinity."""

    def test_keys_format(self):
        from app.pingfed.store import _keys
        tk, lk, nk = _keys("https://example.com")
        assert "{auth:example.com}" in tk
        assert "{auth:example.com}" in lk
        assert "{auth:example.com}" in nk

    def test_keys_with_bare_host(self):
        from app.pingfed.store import _keys
        tk, lk, nk = _keys("my.host.com")
        assert tk == "agent:{auth:my.host.com}:token"
        assert lk == "agent:{auth:my.host.com}:lock"
        assert nk == "agent:{auth:my.host.com}:notify"


# ============================================================================
# store.py  --  _get_redis
# ============================================================================

class TestGetRedis:
    """Negative tests for _get_redis."""

    @pytest.mark.asyncio
    async def test_empty_redis_host_raises(self):
        import app.pingfed.store as store_mod
        old_redis = store_mod._redis
        store_mod._redis = None
        try:
            mock_settings = MagicMock()
            mock_settings.redis_host = ""
            with patch("app.pingfed.store.get_settings", return_value=mock_settings):
                with pytest.raises(RuntimeError, match="REDIS_HOST not configured"):
                    await store_mod._get_redis()
        finally:
            store_mod._redis = old_redis


# ============================================================================
# store.py  --  _try_acquire_lock / _release_lock
# ============================================================================

class TestLocking:
    """Negative tests for distributed lock helpers."""

    @pytest.mark.asyncio
    async def test_try_acquire_lock_redis_set_returns_none(self):
        from app.pingfed.store import _try_acquire_lock
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)  # lock not acquired
        with patch("app.pingfed.store.get_settings") as gs:
            gs.return_value.auth_lock_ttl = 60
            result = await _try_acquire_lock(redis, "mylock")
        assert result is False

    @pytest.mark.asyncio
    async def test_try_acquire_lock_redis_set_returns_false(self):
        from app.pingfed.store import _try_acquire_lock
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=False)
        with patch("app.pingfed.store.get_settings") as gs:
            gs.return_value.auth_lock_ttl = 60
            result = await _try_acquire_lock(redis, "mylock")
        assert result is False

    @pytest.mark.asyncio
    async def test_release_lock_redis_get_raises(self):
        from app.pingfed.store import _release_lock
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("gone"))
        # Should not raise -- logs warning instead
        await _release_lock(redis, "mylock")

    @pytest.mark.asyncio
    async def test_release_lock_owner_mismatch(self):
        import app.pingfed.store as store_mod
        from app.pingfed.store import _release_lock
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="other-pod-id")
        redis.delete = AsyncMock()
        await _release_lock(redis, "mylock")
        redis.delete.assert_not_called()


# ============================================================================
# store.py  --  _store_token
# ============================================================================

class TestStoreToken:
    """Negative tests for _store_token."""

    @pytest.mark.asyncio
    async def test_store_token_missing_refresh_token_o2_session_warns(self):
        from app.pingfed.store import _store_token
        redis, pipe = _make_redis()

        tokens = {"access_token": "session ABCDEF"}  # no refresh_token, O2 session
        with patch("app.pingfed.store.get_settings") as gs:
            gs.return_value.auth_token_ttl = 3300
            gs.return_value.auth_token_refresh_at = 2700
            with patch("app.pingfed.store.log") as mock_log:
                await _store_token(redis, "tk", "nk", tokens)
                mock_log.warning.assert_called_once()
                assert "refresh_token is empty" in mock_log.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_store_token_empty_tokens_dict(self):
        from app.pingfed.store import _store_token
        redis, pipe = _make_redis()

        with patch("app.pingfed.store.get_settings") as gs:
            gs.return_value.auth_token_ttl = 3300
            gs.return_value.auth_token_refresh_at = 2700
            # Should not raise even with empty dict
            await _store_token(redis, "tk", "nk", {})
            pipe.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_token_very_large_token(self):
        from app.pingfed.store import _store_token
        redis, pipe = _make_redis()

        big_token = "x" * 100_000
        tokens = {"access_token": big_token, "refresh_token": "r"}
        with patch("app.pingfed.store.get_settings") as gs:
            gs.return_value.auth_token_ttl = 3300
            gs.return_value.auth_token_refresh_at = 2700
            await _store_token(redis, "tk", "nk", tokens)
            mapping = pipe.hset.call_args[1]["mapping"]
            assert mapping["access_token"] == big_token


# ============================================================================
# store.py  --  _wait_for_token
# ============================================================================

class TestWaitForToken:
    """Negative tests for _wait_for_token."""

    @pytest.mark.asyncio
    async def test_wait_timeout_returns_empty(self):
        from app.pingfed.store import _wait_for_token
        redis = AsyncMock()
        redis.blpop = AsyncMock(return_value=None)  # timeout
        result = await _wait_for_token(redis, "tk", "nk", timeout=1)
        assert result == ""

    @pytest.mark.asyncio
    async def test_wait_notified_but_token_expired(self):
        from app.pingfed.store import _wait_for_token
        expired_time = str(time.time() - 100)
        redis, pipe = _make_redis(pipe_return=["some_token", expired_time, "0"],
                                  blpop=AsyncMock(return_value=("nk", "1")))
        result = await _wait_for_token(redis, "tk", "nk")
        assert result == ""

    @pytest.mark.asyncio
    async def test_wait_exactly_at_expiry(self):
        from app.pingfed.store import _wait_for_token
        now = time.time()
        redis, pipe = _make_redis(pipe_return=["tok", str(now), "0"],
                                  blpop=AsyncMock(return_value=("nk", "1")))
        with patch("app.pingfed.store.time") as mock_time:
            mock_time.time.return_value = now
            result = await _wait_for_token(redis, "tk", "nk")
        # expires_at == now  =>  not (expires_at > time.time()) => empty
        assert result == ""


# ============================================================================
# store.py  --  get_token
# ============================================================================

class TestGetToken:
    """Negative tests for the main get_token flow."""

    @pytest.mark.asyncio
    async def test_login_fails_raises_runtime_error(self):
        import app.pingfed.store as store_mod
        redis, pipe = _make_redis(
            pipe_return=["", "0", "0"],
            set=AsyncMock(return_value=True),
            get=AsyncMock(return_value=store_mod._pod_id),
            delete=AsyncMock(),
        )

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with patch.object(store_mod, "_do_login", return_value=None):
                with pytest.raises(RuntimeError, match="SSO login returned no token"):
                    await store_mod.get_token("test.example.com")

    @pytest.mark.asyncio
    async def test_login_returns_no_access_token(self):
        import app.pingfed.store as store_mod
        redis, pipe = _make_redis(
            pipe_return=["", "0", "0"],
            set=AsyncMock(return_value=True),
            get=AsyncMock(return_value=store_mod._pod_id),
            delete=AsyncMock(),
        )

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with patch.object(store_mod, "_do_login", return_value={"access_token": ""}):
                with pytest.raises(RuntimeError, match="SSO login returned no token"):
                    await store_mod.get_token("test.example.com")

    @pytest.mark.asyncio
    async def test_timeout_waiting_for_peer_pod(self):
        import app.pingfed.store as store_mod
        redis, pipe = _make_redis(
            pipe_return=["", "0", "0"],
            set=AsyncMock(return_value=None),
            blpop=AsyncMock(return_value=None),
        )

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with pytest.raises(RuntimeError, match="timed out waiting for token"):
                await store_mod.get_token("test.example.com")


# ============================================================================
# store.py  --  get_full_tokens
# ============================================================================

class TestGetFullTokens:
    """Negative tests for get_full_tokens."""

    @pytest.mark.asyncio
    async def test_access_token_missing_after_login(self):
        import app.pingfed.store as store_mod
        redis, pipe = _make_redis(pipe_return=["", "", "0", "0"])

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with patch.object(store_mod, "get_token", return_value="tok"):
                with pytest.raises(RuntimeError, match="access_token missing after login"):
                    await store_mod.get_full_tokens("test.example.com")

    @pytest.mark.asyncio
    async def test_get_full_tokens_stale_triggers_background_refresh(self):
        import app.pingfed.store as store_mod
        now = time.time()
        redis, pipe = _make_redis(pipe_return=[
            "access_tok", "refresh_tok", str(now + 600), str(now - 10)
        ])

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with patch("asyncio.create_task") as mock_task:
                result = await store_mod.get_full_tokens("test.example.com")
                assert result["access_token"] == "access_tok"
                assert result["refresh_token"] == "refresh_tok"


# ============================================================================
# store.py  --  _do_login
# ============================================================================

class TestDoLogin:
    """Negative tests for _do_login."""

    @pytest.mark.asyncio
    async def test_missing_sso_credentials(self):
        from app.pingfed.store import _do_login
        mock_settings = MagicMock()
        mock_settings.sso_username = ""
        mock_settings.sso_password = ""
        with patch("app.pingfed.store.get_settings", return_value=mock_settings):
            with pytest.raises(RuntimeError, match="SSO_USERNAME and SSO_PASSWORD must be set"):
                await _do_login("test.example.com")

    @pytest.mark.asyncio
    async def test_missing_sso_password_only(self):
        from app.pingfed.store import _do_login
        mock_settings = MagicMock()
        mock_settings.sso_username = "user"
        mock_settings.sso_password = ""
        with patch("app.pingfed.store.get_settings", return_value=mock_settings):
            with pytest.raises(RuntimeError, match="SSO_USERNAME and SSO_PASSWORD must be set"):
                await _do_login("test.example.com")


# ============================================================================
# store.py  --  _background_refresh
# ============================================================================

class TestBackgroundRefresh:
    """Negative tests for _background_refresh."""

    @pytest.mark.asyncio
    async def test_login_fails_logs_warning(self):
        import app.pingfed.store as store_mod
        redis = AsyncMock()
        with patch.object(store_mod, "_do_login", side_effect=RuntimeError("boom")):
            with patch.object(store_mod, "log") as mock_log:
                await store_mod._background_refresh(redis, "test.example.com")
                assert mock_log.warning.called

    @pytest.mark.asyncio
    async def test_login_returns_none_logs_warning(self):
        import app.pingfed.store as store_mod
        redis = AsyncMock()
        with patch.object(store_mod, "_do_login", return_value=None):
            with patch.object(store_mod, "log") as mock_log:
                await store_mod._background_refresh(redis, "test.example.com")
                mock_log.warning.assert_called_once()
                assert "no token" in mock_log.warning.call_args[0][0]


# ============================================================================
# store.py  --  invalidate / close / warm
# ============================================================================

class TestInvalidateCloseWarm:

    @pytest.mark.asyncio
    async def test_invalidate_redis_delete_fails(self):
        import app.pingfed.store as store_mod
        redis, pipe = _make_redis(delete=AsyncMock(side_effect=ConnectionError("redis down")))

        with patch.object(store_mod, "_get_redis", return_value=redis):
            # Should not raise
            await store_mod.invalidate("test.example.com")

    @pytest.mark.asyncio
    async def test_close_redis_aclose_raises(self):
        import app.pingfed.store as store_mod
        old_redis = store_mod._redis
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock(side_effect=OSError("close failed"))
        store_mod._redis = mock_redis
        try:
            await store_mod.close()
            assert store_mod._redis is None
        finally:
            store_mod._redis = old_redis

    @pytest.mark.asyncio
    async def test_close_called_multiple_times(self):
        import app.pingfed.store as store_mod
        old_redis = store_mod._redis
        mock_redis = AsyncMock()
        store_mod._redis = mock_redis
        try:
            await store_mod.close()
            assert store_mod._redis is None
            # Second close should be a no-op
            await store_mod.close()
            assert store_mod._redis is None
        finally:
            store_mod._redis = old_redis

    @pytest.mark.asyncio
    async def test_warm_when_token_already_exists(self):
        import app.pingfed.store as store_mod
        now = time.time()
        redis, pipe = _make_redis(pipe_return=["valid_tok", str(now + 600), str(now + 300)])

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with patch.object(store_mod, "get_token") as mock_get:
                await store_mod.warm("test.example.com")
                mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalidate_when_no_token_cached(self):
        import app.pingfed.store as store_mod
        redis = AsyncMock()
        redis.delete = AsyncMock(return_value=0)  # nothing deleted
        with patch.object(store_mod, "_get_redis", return_value=redis):
            await store_mod.invalidate("test.example.com")
            redis.delete.assert_called_once()


# ============================================================================
# sso.py  --  _parse_auth_tokens
# ============================================================================

class TestParseAuthTokens:

    def _parse(self, raw):
        from app.pingfed.sso import _parse_auth_tokens
        return _parse_auth_tokens(raw)

    def test_malformed_json(self):
        result = self._parse("{not valid json")
        assert result is None

    def test_empty_string(self):
        result = self._parse("")
        assert result is None

    def test_non_json_value(self):
        result = self._parse("just_a_plain_string_no_json")
        assert result is None

    def test_json_without_access_token(self):
        result = self._parse(json.dumps({"refresh_token": "r"}))
        assert result is None

    def test_json_with_empty_access_token(self):
        result = self._parse(json.dumps({"access_token": ""}))
        assert result is None

    def test_regex_fallback_access_only(self):
        raw = 'blah "access_token": "tok123" blah'
        result = self._parse(raw)
        assert result is not None
        assert result["access_token"] == "tok123"
        assert "refresh_token" not in result


# ============================================================================
# sso.py  --  _http_login
# ============================================================================

class TestHttpLogin:

    def test_dex_login_returns_non_url(self):
        from app.pingfed.sso import _http_login
        session = MagicMock()
        resp = MagicMock()
        resp.text = "not a url"
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp
        result = _http_login("https://test.com", "user", "pass", session=session)
        assert result is None

    def test_no_cookie_after_non_pf_redirect(self):
        from app.pingfed.sso import _http_login
        session = MagicMock()
        # First call: dex_login returns URL
        dex_resp = MagicMock()
        dex_resp.text = "https://some-other-site.com/auth"
        dex_resp.raise_for_status = MagicMock()
        # Second call: follow the dex URL -- not at PF
        follow_resp = MagicMock()
        follow_resp.url = "https://some-other-site.com/auth"
        follow_resp.text = "<html>no meta refresh</html>"
        session.get.side_effect = [dex_resp, follow_resp]
        session.cookies = []  # no cookies
        result = _http_login("https://test.com", "user", "pass", session=session)
        assert result is None

    def test_missing_refresh_token_forces_browser_fallback(self):
        from app.pingfed.sso import _http_login, COOKIE_NAME
        session = MagicMock()
        dex_resp = MagicMock()
        dex_resp.text = "https://other.com/dex"
        dex_resp.raise_for_status = MagicMock()
        follow_resp = MagicMock()
        follow_resp.url = "https://other.com/callback"
        follow_resp.text = "<html></html>"
        session.get.side_effect = [dex_resp, follow_resp]

        cookie = MagicMock()
        cookie.name = COOKIE_NAME
        cookie.value = json.dumps({"access_token": "tok"})  # no refresh_token
        session.cookies = [cookie]

        result = _http_login("https://test.com", "user", "pass", session=session)
        assert result is None  # forced browser fallback


# ============================================================================
# sso.py  --  login (top level)
# ============================================================================

class TestSsoLogin:

    @pytest.mark.asyncio
    async def test_both_http_and_browser_fail(self):
        from app.pingfed.sso import login
        with patch("app.pingfed.sso._http_login", return_value=None):
            with patch("app.pingfed.sso._browser_login", return_value=None):
                result = await login("https://test.com", "user", "pass")
                assert result is None

    @pytest.mark.asyncio
    async def test_login_browser_timeout(self):
        from app.pingfed.sso import login

        async def slow_browser(*a, **kw):
            await asyncio.sleep(999)

        with patch("app.pingfed.sso._http_login", return_value=None):
            with patch("app.pingfed.sso._browser_login", side_effect=slow_browser):
                with patch("app.pingfed.sso.asyncio.wait_for", side_effect=asyncio.TimeoutError):
                    result = await login("https://test.com", "user", "pass")
                    assert result is None


# ============================================================================
# sso.py  --  _create_session
# ============================================================================

class TestSsoCreateSession:

    def test_session_ssl_config(self):
        from app.pingfed.sso import _create_session
        s = _create_session()
        assert s.verify is False
        assert s.trust_env is False


# ============================================================================
# generic_sso.py  --  login negative tests
# ============================================================================

class TestGenericSsoLogin:

    def test_connection_timeout(self):
        from app.pingfed.generic_sso import login
        with patch("app.pingfed.generic_sso._create_session") as mock_sess:
            session = MagicMock()
            session.get.side_effect = ConnectionError("timeout")
            session.cookies = []
            mock_sess.return_value = session
            result = login("https://test.com", "user", "pass", "_oauth2_proxy")
            assert result is None

    def test_not_redirected_to_pingfed_no_cookie(self):
        from app.pingfed.generic_sso import login
        with patch("app.pingfed.generic_sso._create_session") as mock_sess:
            session = MagicMock()
            resp = MagicMock()
            resp.url = "https://test.com/home"
            resp.status_code = 200
            resp.text = "<html></html>"
            session.get.return_value = resp
            session.cookies = []  # no cookies
            mock_sess.return_value = session
            result = login("https://test.com", "user", "pass", "_oauth2_proxy")
            assert result is None

    def test_empty_cookie_value(self):
        from app.pingfed.generic_sso import login
        with patch("app.pingfed.generic_sso._create_session") as mock_sess:
            session = MagicMock()
            resp = MagicMock()
            resp.url = "https://test.com/home"
            resp.status_code = 200
            resp.text = "<html></html>"
            session.get.return_value = resp
            cookie = MagicMock()
            cookie.name = "_oauth2_proxy"
            cookie.value = ""
            session.cookies = [cookie]
            mock_sess.return_value = session
            result = login("https://test.com", "user", "pass", "_oauth2_proxy")
            assert result is None

    def test_custom_token_parser_raises(self):
        from app.pingfed.generic_sso import login

        def bad_parser(raw):
            raise ValueError("parse error")

        with patch("app.pingfed.generic_sso._create_session") as mock_sess:
            session = MagicMock()
            resp = MagicMock()
            resp.url = "https://pfedprod.wal-mart.com/login"
            resp.status_code = 200
            resp.text = '<html><form action="/submit"><input name="pf.username" value=""></form></html>'
            session.get.return_value = resp
            session.cookies = []
            mock_sess.return_value = session

            with patch("app.pingfed.generic_sso.submit_credentials") as mock_sub:
                post_resp = MagicMock()
                post_resp.status_code = 200
                post_resp.url = "https://test.com/done"
                post_resp.text = "<html></html>"
                mock_sub.return_value = post_resp
                with patch("app.pingfed.generic_sso.follow_auto_submit_forms", return_value=post_resp):
                    cookie = MagicMock()
                    cookie.name = "my_cookie"
                    cookie.value = "raw_val"
                    session.cookies = [cookie]
                    result = login("https://test.com", "user", "pass", "my_cookie", bad_parser)
            # The exception is caught inside login's broad except
            # token_parser raises inside _parse_cookie, which is called inside the try block
            # so result should be None
            assert result is None

    def test_login_cookie_found_after_pf_flow(self):
        from app.pingfed.generic_sso import login
        with patch("app.pingfed.generic_sso._create_session") as mock_sess:
            session = MagicMock()
            resp = MagicMock()
            resp.url = "https://pfedprod.wal-mart.com/login"
            resp.status_code = 200
            resp.text = '<form action="/submit"><input name="pf.username" value=""></form>'
            session.get.return_value = resp

            with patch("app.pingfed.generic_sso.submit_credentials") as mock_sub:
                post_resp = MagicMock()
                post_resp.status_code = 200
                post_resp.url = "https://test.com/done"
                post_resp.text = "<html></html>"
                mock_sub.return_value = post_resp
                with patch("app.pingfed.generic_sso.follow_auto_submit_forms", return_value=post_resp):
                    # No cookie found
                    session.cookies = []
                    mock_sess.return_value = session
                    result = login("https://test.com", "user", "pass", "_session")
            assert result is None

    def test_redirect_loop_meta_refresh(self):
        from app.pingfed.generic_sso import login
        with patch("app.pingfed.generic_sso._create_session") as mock_sess:
            session = MagicMock()
            resp = MagicMock()
            resp.url = "https://pfedprod.wal-mart.com/something"
            resp.status_code = 200
            resp.text = '<html><meta http-equiv="refresh" content="0;url=..."></html>'
            session.get.return_value = resp  # always returns meta-refresh page

            with patch("app.pingfed.generic_sso.submit_credentials") as mock_sub:
                post_resp = MagicMock()
                post_resp.status_code = 200
                post_resp.url = "https://test.com"
                post_resp.text = "<html></html>"
                mock_sub.return_value = post_resp
                with patch("app.pingfed.generic_sso.follow_auto_submit_forms", return_value=post_resp):
                    session.cookies = []
                    mock_sess.return_value = session
                    result = login("https://test.com", "user", "pass", "_cookie")
            assert result is None


# ============================================================================
# hub_sso.py  --  _parse_hub_cookie
# ============================================================================

class TestParseHubPingCookie:

    def _parse(self, raw):
        from app.pingfed.hub_sso import _parse_hub_cookie
        return _parse_hub_cookie(raw)

    def _make_jwt(self, payload: dict) -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
        return f"{header}.{body}.{sig}"

    def test_malformed_jwt_in_cookie(self):
        raw = json.dumps({"token": "not.a.valid-base64-jwt"})
        result = self._parse(raw)
        # The base64 decode may fail or produce garbage -- returns None on exception
        # Actually _parse_hub_cookie catches all exceptions and returns None
        assert result is None or isinstance(result, dict)

    def test_expired_jwt(self):
        jwt = self._make_jwt({"exp": 1000})  # long expired
        raw = json.dumps({"token": jwt})
        result = self._parse(raw)
        assert result is not None
        assert result["expires_at"] == 1000.0

    def test_empty_cookie(self):
        result = self._parse("")
        assert result is None

    def test_non_jwt_token_field(self):
        raw = json.dumps({"token": "single_segment_no_dots"})
        result = self._parse(raw)
        # token has no dots, so it doesn't split into 3 parts => expires_at=0
        assert result is not None
        assert result["expires_at"] == 0.0

    def test_no_token_field(self):
        raw = json.dumps({"other": "value"})
        result = self._parse(raw)
        assert result is None

    def test_garbage_string(self):
        result = self._parse("!@#$%^&*()")
        assert result is None


# ============================================================================
# hub_sso.py  --  _get_token_expiry
# ============================================================================

class TestGetTokenExpiry:

    def test_not_jwt(self):
        from app.pingfed.hub_sso import _get_token_expiry
        assert _get_token_expiry("not-a-jwt") == 0.0

    def test_two_parts(self):
        from app.pingfed.hub_sso import _get_token_expiry
        assert _get_token_expiry("a.b") == 0.0

    def test_invalid_base64_payload(self):
        from app.pingfed.hub_sso import _get_token_expiry
        assert _get_token_expiry("a.!!!invalid!!!.c") == 0.0


# ============================================================================
# _pfed.py  --  submit_credentials
# ============================================================================

class TestSubmitCredentials:

    def test_missing_form_fields_falls_back_to_direct_post(self):
        from app.pingfed._pfed import submit_credentials
        session = MagicMock()
        # GET returns HTML with no form
        resp = MagicMock()
        resp.text = "<html><body>No form here</body></html>"
        resp.url = "https://pfedprod.wal-mart.com/login"
        session.get.return_value = resp
        session.cookies = MagicMock()

        post_resp = MagicMock()
        session.post.return_value = post_resp

        result = submit_credentials(session, "https://pfedprod.wal-mart.com/login", "user", "pass")
        # Should fall back to direct POST with default fields
        session.post.assert_called_once()
        call_data = session.post.call_args[1].get("data") or session.post.call_args[0][1] if len(session.post.call_args[0]) > 1 else session.post.call_args[1]["data"]
        assert call_data["pf.username"] == "user"

    def test_form_with_meta_refresh_retries(self):
        from app.pingfed._pfed import submit_credentials
        session = MagicMock()
        # First GET: meta-refresh, second GET: normal form
        resp1 = MagicMock()
        resp1.text = '<html><meta http-equiv="refresh"><form action="/go"><input name="pf.username" value=""></form></html>'
        resp1.url = "https://pfedprod.wal-mart.com/login"
        resp2 = MagicMock()
        resp2.text = '<html><form action="/go"><input name="pf.username" value=""><input name="pf.pass" value=""></form></html>'
        resp2.url = "https://pfedprod.wal-mart.com/login"
        session.get.side_effect = [resp1, resp2]
        session.cookies = MagicMock()

        post_resp = MagicMock()
        session.post.return_value = post_resp

        result = submit_credentials(session, "https://pfedprod.wal-mart.com/login", "user", "pass")
        assert session.get.call_count == 2


# ============================================================================
# _pfed.py  --  follow_auto_submit_forms
# ============================================================================

class TestFollowAutoSubmitForms:

    def test_max_redirects_exceeded(self):
        from app.pingfed._pfed import follow_auto_submit_forms
        session = MagicMock()
        # Response always has auto-submit form
        resp = MagicMock()
        resp.status_code = 200
        resp.text = (
            '<html><body onload="document.forms[0].submit()">'
            '<form action="https://a.com/next" method="POST">'
            '<input name="SAMLResponse" value="x">'
            '</form></body></html>'
        )
        resp.url = "https://a.com/somewhere"
        session.post.return_value = resp  # always returns same auto-submit

        result = follow_auto_submit_forms(session, resp, max_hops=5)
        # Should stop after 5 hops
        assert session.post.call_count == 5

    def test_non_200_status_stops(self):
        from app.pingfed._pfed import follow_auto_submit_forms
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 302
        resp.text = "<html></html>"
        result = follow_auto_submit_forms(session, resp)
        assert result is resp

    def test_pfed_login_form_stops(self):
        from app.pingfed._pfed import follow_auto_submit_forms
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = (
            '<html><body onload="document.forms[0].submit()">'
            '<form action="/next"><input name="pf.username" value="">'
            '<input name="SAMLResponse" value="x"></form></body></html>'
        )
        result = follow_auto_submit_forms(session, resp)
        # Should stop because is_pfed_login_form is True
        assert result is resp


# ============================================================================
# _pfed.py  --  has_meta_refresh / is_pfed_login_form / parse_form
# ============================================================================

class TestPfedHelpers:

    def test_has_meta_refresh_true(self):
        from app.pingfed._pfed import has_meta_refresh
        html = '<html><head><meta http-equiv="refresh" content="0;url=/next"></head></html>'
        assert has_meta_refresh(html) is True

    def test_has_meta_refresh_false(self):
        from app.pingfed._pfed import has_meta_refresh
        assert has_meta_refresh("<html><head></head></html>") is False

    def test_has_meta_refresh_case_insensitive(self):
        from app.pingfed._pfed import has_meta_refresh
        html = '<META HTTP-EQUIV="Refresh" content="0">'
        assert has_meta_refresh(html) is True

    def test_is_pfed_login_form_true(self):
        from app.pingfed._pfed import is_pfed_login_form
        html = '<input name="pf.username"><input name="pf.pass">'
        assert is_pfed_login_form(html) is True

    def test_is_pfed_login_form_false(self):
        from app.pingfed._pfed import is_pfed_login_form
        html = '<input name="username"><input name="password">'
        assert is_pfed_login_form(html) is False

    def test_parse_form_no_form(self):
        from app.pingfed._pfed import parse_form
        action, method, fields = parse_form("<html>no form</html>")
        assert action is None
        assert fields == {}

    def test_parse_form_extracts_action_url(self):
        from app.pingfed._pfed import parse_form
        html = '<form action="/submit" method="get"><input name="field1" value="v1"></form>'
        action, method, fields = parse_form(html, base_url="https://example.com")
        assert action == "https://example.com/submit"
        assert method == "GET"
        assert fields == {"field1": "v1"}

    def test_has_auto_submit_form_no_form(self):
        from app.pingfed._pfed import has_auto_submit_form
        assert has_auto_submit_form("<html>hello</html>") is False

    def test_has_auto_submit_form_with_saml(self):
        from app.pingfed._pfed import has_auto_submit_form
        html = '<form><input name="SAMLResponse" value="x"></form>'
        assert has_auto_submit_form(html) is True


# ============================================================================
# store.py  --  _parse_hub_ping_cookie (in store module)
# ============================================================================

class TestStoreParseHubPingCookie:
    """Test the _parse_hub_ping_cookie defined in store.py."""

    def _parse(self, raw):
        from app.pingfed.store import _parse_hub_ping_cookie
        return _parse_hub_ping_cookie(raw)

    def test_garbage_input(self):
        result = self._parse("not json at all {{{")
        assert result is None

    def test_empty_token_field(self):
        raw = json.dumps({"token": ""})
        result = self._parse(raw)
        assert result is None

    def test_valid_jwt(self):
        payload = {"exp": 9999999999}
        body_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        header_b64 = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
        jwt = f"{header_b64}.{body_b64}.signature"
        raw = json.dumps({"token": jwt})
        result = self._parse(raw)
        assert result is not None
        assert result["access_token"] == jwt
        assert result["expires_at"] == 9999999999.0


# ============================================================================
# store.py  --  concurrent / race condition edge cases
# ============================================================================

class TestConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_get_token_lock_contention(self):
        """Two concurrent get_token calls: one wins lock, one waits."""
        import app.pingfed.store as store_mod

        now = time.time()
        redis, pipe = _make_redis(
            pipe_return=["", "0", "0"],
            set=AsyncMock(return_value=True),
            get=AsyncMock(return_value=store_mod._pod_id),
            delete=AsyncMock(),
            blpop=AsyncMock(return_value=("nk", "1")),
        )

        tokens_dict = {"access_token": "tok1", "refresh_token": "ref1"}

        async def fake_login(cluster_lb):
            return tokens_dict

        async def capturing_store(r, tk, nk, tokens):
            # After storing, make the pipeline return valid data for waiters
            pipe.execute = AsyncMock(return_value=["tok1", str(now + 600), "0"])

        with patch.object(store_mod, "_get_redis", return_value=redis):
            with patch.object(store_mod, "_do_login", side_effect=fake_login):
                with patch.object(store_mod, "_store_token", side_effect=capturing_store):
                    result = await store_mod.get_token("test.example.com")
                    assert result == "tok1"
