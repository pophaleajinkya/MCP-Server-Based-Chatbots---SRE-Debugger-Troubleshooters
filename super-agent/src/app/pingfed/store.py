"""
Distributed bearer token store backed by Redis.

One pod acquires the token per cluster; all 200 pods reuse it.
Uses SET NX EX (distributed lock) + BLPOP (zero-CPU wait) + stale-while-revalidate.

Tokens are keyed by bare LB hostname (e.g. "intl.logs.prod.walmart.com") so each
service endpoint gets its own isolated token, lock, and notify slot in Redis.

Supported service types (via login strategy registry):
  - O2 clusters  (Dex → PingFed → auth_tokens cookie)      — default
  - DX Hub       (direct → PingFed → hub-ping cookie)       — via generic_sso
  - Prometheus   (oauth2-proxy → Platform SSO → PingFed)    — via generic_sso
  - Any new PingFed-protected service                       — one-line registry entry

Public API
----------
    token = await get_token(cluster_lb)    # hot path: O(1) Redis HGET — works for ANY service
    await invalidate(cluster_lb)           # called on 4XX — forces re-login on next get_token()
    await warm(cluster_lb)                 # called at startup to pre-populate the token
    await close()                          # graceful shutdown (closes Redis connection)

    # Backward-compat aliases (thin wrappers around get_token):
    token = await get_hub_token()          # == get_token("dx.walmart.com")
    await invalidate_hub()                 # == invalidate("dx.walmart.com")
    await warm_hub()                       # == warm("dx.walmart.com")
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

from app.config import get_settings
from app.pingfed.sso import login as sso_login
from app.pingfed.generic_sso import login as generic_sso_login

log = logging.getLogger(__name__)

_redis: object | None = None
_pod_id: str = str(uuid.uuid4())
_init_lock = asyncio.Lock()


# ── Login strategy registry ──────────────────────────────────────────────────
# Maps bare hostnames to their login configuration.  Hosts NOT in the registry
# fall back to the default O2 Dex-based SSO flow (sso.py).
#
# Adding a new PingFed-protected service = one entry here.  No new functions,
# no new files, no new auth tools — get_token(host) just works.


@dataclass(frozen=True)
class _LoginConfig:
    """Describes how to authenticate against a specific PingFed-protected service."""

    cookie_name: str
    """Name of the auth cookie to extract (e.g. "_oauth2_proxy", "hub-ping")."""

    token_parser: Optional[Callable[[str], Optional[dict]]] = None
    """Optional callable to transform the raw cookie value into a token dict.
    When None, the raw cookie value is stored as-is in access_token."""


def _parse_hub_ping_cookie(raw: str) -> Optional[dict]:
    """Parse the DX hub-ping cookie: URL-encoded JSON with a 'token' field containing a JWT."""
    try:
        parsed = json.loads(unquote(raw))
        token = parsed.get("token", "")
        if token:
            # Extract expiry from JWT without full validation
            parts = token.split(".")
            if len(parts) == 3:
                payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
                payload = json.loads(base64.b64decode(payload_b64))
                expires_at = float(payload.get("exp", 0))
            else:
                expires_at = 0.0
            return {"access_token": token, "expires_at": expires_at}
    except Exception as exc:
        log.warning("pingfed.store: failed to parse hub-ping cookie: %s", exc)
    return None


_LOGIN_REGISTRY: dict[str, _LoginConfig] = {
    # DX Hub — platform-hub JWT for ChangeIQ and other MCP servers
    "dx.walmart.com": _LoginConfig(
        cookie_name="hub-ping",
        token_parser=_parse_hub_ping_cookie,
    ),
    # Prometheus MMS — oauth2-proxy session cookie
    "prometheus.query.prod.mms.walmart.net": _LoginConfig(
        cookie_name="_oauth2_proxy",
    ),
    # ── Add new services here ─────────────────────────────────────────────
    # "new-service.walmart.net": _LoginConfig(cookie_name="_session"),
}


def _bare_host(cluster_lb: str) -> str:
    """Normalise cluster_lb to a bare hostname, stripping scheme and path.

    Accepts any of:
      "intl.logs.prod.walmart.com"
      "https://intl.logs.prod.walmart.com"
      "https://intl.logs.prod.walmart.com/api"
    Returns:
      "intl.logs.prod.walmart.com"

    Raises ValueError if cluster_lb is empty after stripping.
    """
    if not cluster_lb or not cluster_lb.strip():
        raise ValueError("pingfed.store: cluster_lb must not be empty")
    s = cluster_lb.strip()
    if "://" in s:
        parsed = urlparse(s)
        if parsed.hostname:
            return parsed.hostname.lower()
        # urlparse failed to extract hostname — strip scheme manually
        s = s.split("://", 1)[1]
    # Strip path and port (e.g. "host:443/path" → "host")
    host_part = s.split("/")[0]
    host_part = host_part.split(":")[0]  # remove port if present
    return host_part.lower()


def _keys(cluster_lb: str) -> tuple[str, str, str]:
    """Return (token_key, lock_key, notify_key) for the given cluster.

    Hash tags {auth:<host>} force all three keys to the same Redis Cluster slot
    so BLPOP/LPUSH are guaranteed to target the same node.
    """
    host = _bare_host(cluster_lb)
    tag = f"{{auth:{host}}}"
    return (
        f"agent:{tag}:token",
        f"agent:{tag}:lock",
        f"agent:{tag}:notify",
    )


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis

    async with _init_lock:
        if _redis is not None:   # re-check after acquiring lock
            return _redis

        s = get_settings()
        if not s.redis_host:
            raise RuntimeError("pingfed.store: REDIS_HOST not configured")

        try:
            from redis.asyncio.cluster import RedisCluster
            _redis = RedisCluster(
                host=s.redis_host,
                port=s.redis_port,
                password=s.redis_password or None,
                username=s.redis_username or None,
                ssl=s.redis_ssl,
                ssl_cert_reqs=None,              # internal Walmart cert — skip verify
                socket_timeout=s.redis_socket_timeout,
                socket_connect_timeout=s.redis_socket_connect_timeout,
                max_connections=s.redis_max_connections,
                decode_responses=True,
            )
        except ImportError:
            import redis.asyncio as aioredis
            _redis = aioredis.Redis(
                host=s.redis_host,
                port=s.redis_port,
                password=s.redis_password or None,
                username=s.redis_username or None,
                ssl=s.redis_ssl,
                ssl_cert_reqs=None,              # internal Walmart cert — skip verify
                socket_timeout=s.redis_socket_timeout,
                socket_connect_timeout=s.redis_socket_connect_timeout,
                max_connections=s.redis_max_connections,
                decode_responses=True,
            )
    return _redis


async def _read_token_fields(redis, token_key: str) -> tuple[str, float, float]:
    """Return (access_token, expires_at, refresh_at) from Redis in one pipeline."""
    pipe = redis.pipeline()
    pipe.hget(token_key, "access_token")
    pipe.hget(token_key, "expires_at")
    pipe.hget(token_key, "refresh_at")
    token, expires_raw, refresh_raw = await pipe.execute()
    return (
        token or "",
        float(expires_raw or 0),
        float(refresh_raw or 0),
    )


async def _read_full_token_fields(redis, token_key: str) -> tuple[str, str, float, float]:
    """Return (access_token, refresh_token, expires_at, refresh_at) from Redis in one pipeline."""
    pipe = redis.pipeline()
    pipe.hget(token_key, "access_token")
    pipe.hget(token_key, "refresh_token")
    pipe.hget(token_key, "expires_at")
    pipe.hget(token_key, "refresh_at")
    token, refresh_token, expires_raw, refresh_raw = await pipe.execute()
    return (
        token or "",
        refresh_token or "",
        float(expires_raw or 0),
        float(refresh_raw or 0),
    )


async def _try_acquire_lock(redis, lock_key: str) -> bool:
    s = get_settings()
    result = await redis.set(lock_key, _pod_id, nx=True, ex=s.auth_lock_ttl)
    return result is True


async def _release_lock(redis, lock_key: str) -> None:
    try:
        owner = await redis.get(lock_key)
        if owner == _pod_id:
            await redis.delete(lock_key)
    except Exception as exc:
        log.warning("pingfed.store: could not release lock: %s", exc)


async def _store_token(redis, token_key: str, notify_key: str, tokens: dict) -> None:
    s = get_settings()
    now = time.time()
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        # Only warn for O2 session tokens — they require both access_token and
        # refresh_token.  Generic SSO services (Hub JWT, oauth2-proxy) don't
        # have refresh tokens and that's fine.
        access = tokens.get("access_token", "")
        if access.startswith("session "):
            log.warning(
                "pingfed.store: _store_token: refresh_token is empty for key=%s "
                "— O2 session auth will fail. Check sso.py HTTP/browser login flow.",
                token_key,
            )
    fields = {
        "access_token":  tokens.get("access_token", ""),
        "refresh_token": refresh_token,
        "expires_at":    str(tokens.get("expires_at",  now + s.auth_token_ttl)),
        "refresh_at":    str(tokens.get("refresh_at",  now + s.auth_token_refresh_at)),
        "acquired_by":   _pod_id,
        "acquired_at":   str(now),
    }
    pipe = redis.pipeline()
    pipe.hset(token_key, mapping=fields)
    pipe.expire(token_key, s.auth_token_ttl)
    pipe.lpush(notify_key, "1")
    pipe.expire(notify_key, 5)
    await pipe.execute()


async def _wait_for_token(redis, token_key: str, notify_key: str, timeout: int = 30) -> str:
    """Block (server-side) until another pod stores the token.

    Returns empty string on timeout or if the notified token is already expired.
    """
    result = await redis.blpop([notify_key], timeout=timeout)
    if result is None:
        return ""
    token, expires_at, _ = await _read_token_fields(redis, token_key)
    if token and expires_at > time.time():
        return token
    log.warning("pingfed.store: notified token is already expired (expires_at=%.0f)", expires_at)
    return ""


async def _do_login(cluster_lb: str) -> dict | None:
    """Authenticate against the given service and return a token dict.

    Dispatches to the appropriate login strategy based on the hostname:
      - Hosts in _LOGIN_REGISTRY → generic_sso.login (cookie-name parameterised)
      - All others              → sso.login (O2 Dex-based flow, the default)

    The generic_sso path is synchronous HTTP (requests library), so it runs in
    a thread executor to avoid blocking the event loop.
    """
    s = get_settings()
    if not s.sso_username or not s.sso_password:
        raise RuntimeError("pingfed.store: SSO_USERNAME and SSO_PASSWORD must be set")

    host = _bare_host(cluster_lb)
    config = _LOGIN_REGISTRY.get(host)

    if config is not None:
        # Generic flow: follow redirects → PingFed → extract named cookie.
        # generic_sso.login is synchronous (uses requests) — run in executor.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            generic_sso_login,
            f"https://{host}",
            s.sso_username,
            s.sso_password,
            config.cookie_name,
            config.token_parser,
        )

    # Default: O2 Dex-based SSO (async, supports HTTP + Playwright fallback)
    base_url = f"https://{host}"
    return await sso_login(base_url, s.sso_username, s.sso_password)


async def _background_refresh(redis, cluster_lb: str) -> None:
    token_key, _, notify_key = _keys(cluster_lb)
    try:
        tokens = await _do_login(cluster_lb)
        if tokens:
            await _store_token(redis, token_key, notify_key, tokens)
            log.info("pingfed.store: background token refresh complete for %s", _bare_host(cluster_lb))
        else:
            log.warning("pingfed.store: background refresh returned no token for %s", _bare_host(cluster_lb))
    except Exception as exc:
        log.warning("pingfed.store: background refresh failed for %s: %s", _bare_host(cluster_lb), exc)


async def get_token(cluster_lb: str) -> str:
    """Return a live auth token for any PingFed-protected service, shared across all pods.

    Works for ALL service types — O2 clusters, DX Hub, Prometheus MMS, or any
    new service added to ``_LOGIN_REGISTRY``.  The hostname determines which
    login strategy is used.

    Parameters
    ----------
    cluster_lb:
        The service's hostname (bare or with scheme).
        Examples:
          "intl.logs.prod.walmart.com"                  — O2 cluster (Dex SSO)
          "dx.walmart.com"                              — DX Hub (platform-hub JWT)
          "prometheus.query.prod.mms.walmart.net"       — Prometheus (oauth2-proxy)

    Path selection:
      1. Hot   — token in Redis, not yet stale           → return immediately
      2. Stale — past refresh_at but still valid          → background refresh,
                 return current token without blocking
      3. Cold  — no token; this pod wins the lock         → login, store, return
      4. Wait  — no token; another pod holds the lock     → BLPOP until notified

    Raises RuntimeError if login fails and no token is available.
    """
    redis = await _get_redis()
    now = time.time()
    token_key, lock_key, notify_key = _keys(cluster_lb)

    token, expires_at, refresh_at = await _read_token_fields(redis, token_key)

    if token and now < expires_at:
        if now >= refresh_at:
            try:
                asyncio.create_task(_background_refresh(redis, cluster_lb))
            except RuntimeError:
                pass  # no running loop at shutdown — skip background refresh
        return token

    if await _try_acquire_lock(redis, lock_key):
        # Double-check: another pod may have stored the token while we raced
        token, expires_at, _ = await _read_token_fields(redis, token_key)
        if token and expires_at > now:
            await _release_lock(redis, lock_key)
            return token

        try:
            tokens = await _do_login(cluster_lb)
            if not tokens or not tokens.get("access_token"):
                raise RuntimeError(f"pingfed.store: SSO login returned no token for {_bare_host(cluster_lb)}")
            await _store_token(redis, token_key, notify_key, tokens)
            log.info("pingfed.store: token acquired by this pod for %s", _bare_host(cluster_lb))
            return tokens["access_token"]
        finally:
            await _release_lock(redis, lock_key)

    token = await _wait_for_token(redis, token_key, notify_key)
    if token:
        return token
    # Timeout fallback — one last direct read, but only if token is not expired
    token, expires_at, _ = await _read_token_fields(redis, token_key)
    if token and expires_at > now:
        return token
    raise RuntimeError(
        f"pingfed.store: timed out waiting for token from peer pod for {_bare_host(cluster_lb)}"
    )


async def get_full_tokens(cluster_lb: str) -> dict:
    """Return the full token dict for a cluster, including the refresh_token.

    O2 session-based auth (tokens starting with ``"session "``) requires
    **both** ``access_token`` and ``refresh_token`` to be present in the
    ``auth_tokens`` cookie.  This function returns both so callers can
    reconstruct the exact cookie value that O2 expects.

    Returns:
        {
          "access_token":  "<session XXXXX or eyJ...>",
          "refresh_token": "<refresh token, may be empty for JWT flows>",
        }

    Raises RuntimeError if no valid token is available (same as get_token()).
    """
    redis = await _get_redis()
    now = time.time()
    token_key, lock_key, notify_key = _keys(cluster_lb)

    access_token, refresh_token, expires_at, refresh_at = await _read_full_token_fields(redis, token_key)

    if access_token and now < expires_at:
        if now >= refresh_at:
            try:
                asyncio.create_task(_background_refresh(redis, cluster_lb))
            except RuntimeError:
                pass  # no running loop at shutdown
        return {"access_token": access_token, "refresh_token": refresh_token}

    # No valid cached token — run the full login flow (acquires lock, stores token).
    await get_token(cluster_lb)  # raises RuntimeError if login fails

    # Re-read both fields atomically after login completes.
    access_token, refresh_token, _, _ = await _read_full_token_fields(redis, token_key)
    if not access_token:
        raise RuntimeError(
            f"pingfed.store: get_full_tokens: access_token missing after login for {_bare_host(cluster_lb)}"
        )
    return {"access_token": access_token, "refresh_token": refresh_token}


async def invalidate(cluster_lb: str) -> None:
    """Delete the cached token for a cluster — next get_token() call will re-login."""
    try:
        redis = await _get_redis()
        token_key, _, _ = _keys(cluster_lb)
        await redis.delete(token_key)
        log.info("pingfed.store: token invalidated for %s", _bare_host(cluster_lb))
    except Exception as exc:
        log.warning("pingfed.store: invalidate failed for %s: %s", _bare_host(cluster_lb), exc)


async def warm(cluster_lb: str) -> None:
    """Pre-warm the token for a cluster at startup. No-op if a valid token already exists."""
    redis = await _get_redis()
    token_key, _, _ = _keys(cluster_lb)
    token, expires_at, _ = await _read_token_fields(redis, token_key)
    if token and expires_at > time.time():
        log.info("pingfed.store: token already warm in Redis for %s", _bare_host(cluster_lb))
        return
    await get_token(cluster_lb)
    log.info("pingfed.store: warm-up complete for %s", _bare_host(cluster_lb))


# ── Hub token backward-compat aliases ────────────────────────────────────────
# DX Hub (dx.walmart.com) is now handled by the generic login registry above.
# These thin wrappers maintain backward compatibility with existing callers
# (factory.py warm-up, auth_tool.py, __init__.py exports).

_HUB_HOST = "dx.walmart.com"


async def get_hub_token() -> str:
    """Return a live platform-hub JWT token.  Alias for ``get_token("dx.walmart.com")``."""
    return await get_token(_HUB_HOST)


async def invalidate_hub() -> None:
    """Delete the cached hub token.  Alias for ``invalidate("dx.walmart.com")``."""
    await invalidate(_HUB_HOST)


async def warm_hub() -> None:
    """Pre-warm the hub token at startup.  Alias for ``warm("dx.walmart.com")``."""
    await warm(_HUB_HOST)


async def close() -> None:
    """Close the Redis connection cleanly."""
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
