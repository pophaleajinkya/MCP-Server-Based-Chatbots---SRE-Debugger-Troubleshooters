"""
Async HTTP client for OpenObserve API.

Design:
- Single responsibility: only HTTP operations
- Auth token injected by the caller (from the incoming request Authorization header)
- 4XX errors are surfaced as structured error dicts — the calling agent handles
  retry logic (e.g. call pingfed_playwright_token then retry the tool)
- No SSO, no self-healing, no circular dependencies
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Shared async HTTP client — one connection pool for the entire process.
# O2HttpClient instances are created per-request (to carry different auth
# tokens), but they all share this pool to avoid TCP churn.
_shared_http: httpx.AsyncClient | None = None
_shared_http_lock = asyncio.Lock()
_shared_http_sync_lock = threading.Lock()  # guards the sync creation path


async def _get_shared_http_async(timeout: float, ssl_verify: bool) -> httpx.AsyncClient:
    """Thread-safe async accessor for the shared HTTP client."""
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        return _shared_http
    async with _shared_http_lock:
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(timeout=timeout, verify=ssl_verify)
    return _shared_http


def _get_shared_http(timeout: float, ssl_verify: bool) -> httpx.AsyncClient:
    """Sync accessor — creates client if needed.

    Protected by a threading.Lock so concurrent O2HttpClient constructions
    (e.g. multiple uvicorn worker threads starting simultaneously) cannot each
    create their own AsyncClient and leak the first one.
    """
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        return _shared_http
    with _shared_http_sync_lock:
        # Double-check inside the lock — another thread may have created it
        # while we were waiting.
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(timeout=timeout, verify=ssl_verify)
    return _shared_http


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _bearer_to_basic(bearer_token: str) -> str:
    """
    Convert a raw PingFederate access_token to the Basic auth token
    expected by OpenObserve: base64("root:<access_token>").
    """
    return base64.b64encode(f"root:{bearer_token}".encode()).decode()


def _is_session_token(token: str) -> bool:
    """Return True when token is an O2 web session token (starts with 'session ').

    O2 session tokens from the web SSO flow look like 'session <id>' and must
    be passed as the auth_tokens cookie, not as Basic auth credentials.
    JWT access tokens (eyJ...) use Basic auth: base64('root:<jwt>').
    """
    return bool(token) and token.strip().startswith("session ")


def _is_full_cookie_json(token: str) -> bool:
    """Return True when token is the full auth_tokens cookie JSON from pingfed_playwright_token.

    pingfed_playwright_token returns a compact JSON string like:
        '{"access_token":"session XXXXX","refresh_token":"Chl..."}'
    when the O2 session flow is active.  This JSON must be passed verbatim
    (no URL-encoding) as the auth_tokens cookie value to the O2 REST API.

    Validates that:
      - The string is parseable as JSON
      - "access_token" key exists and is a non-empty string
    """
    t = (token or "").strip()
    if not t.startswith("{"):
        return False
    try:
        obj = json.loads(t)
        return isinstance(obj, dict) and bool(obj.get("access_token"))
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class O2Error(Exception):
    """Base exception for all OpenObserve client errors."""


class O2ApiError(O2Error):
    """HTTP-level API error with status code."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"O2 API {status_code}: {message}")


class O2ConnectionError(O2Error):
    """Network-level connection failure."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class O2HttpClient:
    """
    Async HTTP client for the OpenObserve REST API.

    Auth priority (first non-empty wins):
      1. ``bearer_token`` — raw PingFederate access_token from the incoming
                            ``Authorization: Bearer <token>`` request header.
                            Automatically encoded as Basic auth for O2.
      2. ``auth_token``   — pre-encoded Basic auth token (O2_AUTH_TOKEN env var).

    On 4XX the error is returned as a structured dict with ``auth_expired: true``
    so the agent can detect it, call ``pingfed_playwright_token`` for a fresh
    token, and retry the tool call.  No self-healing happens inside this client.

    Usage::

        client = O2HttpClient(bearer_token="<access_token>")
        client = O2HttpClient(auth_token="<base64-encoded>")   # static / legacy
        client = O2HttpClient()                                 # O2_AUTH_TOKEN env var
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        base_url: str = "",
        auth_token: str = "",
        bearer_token: str = "",
        org_id: str = "",
        timeout: float = 0.0,
        ssl_verify: bool | None = None,
    ) -> None:
        cfg = settings or get_settings()

        resolved_url = (base_url or cfg.base_url or "").strip().rstrip("/")
        if not resolved_url:
            raise ValueError(
                "O2HttpClient: base_url is required. "
                "Pass it explicitly or set O2_ENDPOINT env var."
            )
        self._base_url   = resolved_url
        self._org_id     = org_id or cfg.org_id
        self._timeout    = timeout or cfg.timeout
        self._ssl_verify = ssl_verify if ssl_verify is not None else cfg.ssl_verify

        # Resolve auth strategy based on token type:
        #   Full cookie JSON '{"access_token":"session ...","refresh_token":"..."}' →
        #       pass as RAW JSON — NO URL-encoding. O2 reads the Cookie header as
        #       plain JSON, same as the browser sends it (ref: david/endpoint_config.py).
        #   Bare session token ("session <id>") → wrap in minimal JSON, no encoding
        #   JWT ("eyJ...")                 → Basic base64("root:<jwt>")
        #   Pre-encoded auth_token (O2_AUTH_TOKEN env) → Basic <token>
        self._auth_header  = ""
        self._session_cookie = ""  # raw JSON — set when using O2 web session token

        if bearer_token:
            if _is_full_cookie_json(bearer_token):
                # Full cookie JSON from pingfed_playwright_token — use verbatim, no encoding.
                self._session_cookie = bearer_token
            elif _is_session_token(bearer_token):
                # Bare session token (legacy fallback) — wrap in minimal JSON, no encoding.
                import json as _json
                self._session_cookie = _json.dumps(
                    {"access_token": bearer_token}, separators=(",", ":")
                )
            else:
                self._auth_header = f"Basic {_bearer_to_basic(bearer_token)}"
        elif auth_token:
            self._auth_header = f"Basic {auth_token}"
        elif cfg.auth_token:
            self._auth_header = f"Basic {cfg.auth_token}"

        self._http = _get_shared_http(self._timeout, self._ssl_verify)

        _auth_mode = (
            "cookie" if self._session_cookie
            else "header" if self._auth_header
            else "NONE"
        )
        if _auth_mode == "NONE":
            logger.warning(
                "O2HttpClient: no auth configured for %s — "
                "every request will fail with 401. "
                "Pass bearer_token= or set O2_AUTH_TOKEN env var.",
                self._base_url,
            )
        else:
            logger.debug(
                "O2HttpClient ready: base_url=%s org=%s timeout=%.1fs auth=%s",
                self._base_url, self._org_id, self._timeout, _auth_mode,
            )

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._session_cookie:
            # O2 web session auth — pass as cookie (same mechanism as the browser UI)
            h["Cookie"] = f"auth_tokens={self._session_cookie}"
        elif self._auth_header:
            h["Authorization"] = self._auth_header
        return h

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def org(self) -> str:
        return self._org_id

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Make an authenticated HTTP request.

        On 4XX the method raises ``O2ApiError`` with the status code.
        Callers (MCP tools) catch this and return a structured error dict
        that includes ``"auth_expired": true`` for 401/403, giving the
        orchestrating agent enough signal to call ``pingfed_playwright_token``
        and retry.

        Raises:
            O2ApiError: Non-2xx HTTP responses.
            O2ConnectionError: Network or timeout failures.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        # Lazily refresh the shared client if it was closed (e.g., after server reload).
        if self._http.is_closed:
            self._http = await _get_shared_http_async(self._timeout, self._ssl_verify)

        try:
            resp = await self._http.request(
                method=method, url=url, headers=self._headers(), **kwargs,
            )
            resp.raise_for_status()
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                # O2 sometimes returns HTML error pages (e.g., nginx 502) — surface as O2ApiError.
                logger.error("Non-JSON response from %s (status=%s): %s", url, resp.status_code, resp.text[:200])
                raise O2ApiError(resp.status_code, f"Non-JSON response: {resp.text[:200]}") from exc

        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            logger.error("HTTP %s %s → %s", method, url, exc.response.status_code)
            raise O2ApiError(exc.response.status_code, body) from exc

        except httpx.ConnectError as exc:
            logger.error("Connect error %s: %s", url, exc)
            raise O2ConnectionError(f"Cannot connect to {url}") from exc

        except httpx.TimeoutException as exc:
            logger.error("Timeout %s after %.1fs", url, self._timeout)
            raise O2ConnectionError(f"Request timed out after {self._timeout}s") from exc

        except (O2ApiError, O2ConnectionError):
            raise  # already classified — don't re-wrap

        except Exception as exc:
            logger.error("Unexpected error %s: %s", url, exc)
            raise O2ConnectionError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Convenience verbs
    # ------------------------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: dict[str, Any] | None = None,
                   params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("POST", path, json=json, params=params)

    async def put(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("PUT", path, json=json)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self.request("DELETE", path)

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_time_range(time_range: str) -> tuple[int, int]:
        """Convert a relative time range string to microsecond timestamps.

        Supported suffixes: ``m`` (minutes), ``h`` (hours), ``d`` (days).
        Returns ``(start_us, end_us)`` in microseconds.

        Edge cases handled:
          - Empty / None        → defaults to 1h
          - Single char ("h")   → defaults to 1h
          - Zero value ("0h")   → defaults to 1h (zero-width range is useless)
          - Negative ("-1h")    → defaults to 1h
          - Unknown suffix      → defaults to 1h
          - OverflowError       → defaults to 1h
        """
        now = datetime.now(timezone.utc)
        _default = timedelta(hours=1)

        if not time_range or len(time_range) < 2:
            logger.warning("Invalid time_range %r, defaulting to 1h", time_range)
            delta = _default
        else:
            unit = time_range[-1].lower()
            try:
                value = int(time_range[:-1])
                if value <= 0:
                    raise ValueError("non-positive")
                if unit == "m":
                    delta = timedelta(minutes=value)
                elif unit == "h":
                    delta = timedelta(hours=value)
                elif unit == "d":
                    delta = timedelta(days=value)
                else:
                    logger.warning("Unknown time unit %r in %r, defaulting to 1h", unit, time_range)
                    delta = _default
            except (ValueError, OverflowError):
                logger.warning("Invalid time_range %r, defaulting to 1h", time_range)
                delta = _default

        start = now - delta
        return int(start.timestamp() * 1_000_000), int(now.timestamp() * 1_000_000)

    @staticmethod
    def now_us() -> int:
        """Current UTC time in microseconds."""
        return int(time.time() * 1_000_000)
