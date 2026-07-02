"""
Async HTTP client for Signal API.

Authentication:
    Signal API currently requires no API key or bearer token.
    Every request includes:
      - accept: application/json
      - Content-Type: application/json  (for POST requests)

Design:
    Single shared httpx.AsyncClient for connection pooling.
    All errors surfaced as structured exceptions for the service layer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import httpx

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SignalError(Exception):
    """Base exception for Signal client errors."""


class SignalApiError(SignalError):
    """HTTP-level API error with status code."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Signal API {status_code}: {message}")


class SignalConnectionError(SignalError):
    """Network-level connection failure."""


_shared_http: httpx.AsyncClient | None = None
_shared_http_lock = asyncio.Lock()
_shared_http_sync_lock = threading.Lock()


async def _get_shared_http_async(
    timeout: float, ssl_verify: bool,
) -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        return _shared_http
    async with _shared_http_lock:
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(
                timeout=timeout, verify=ssl_verify,
            )
    return _shared_http


def _get_shared_http(timeout: float, ssl_verify: bool) -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        return _shared_http
    with _shared_http_sync_lock:
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(
                timeout=timeout, verify=ssl_verify,
            )
    return _shared_http


class SignalHttpClient:
    """
    Async HTTP client for the Signal REST API.

    No API key authentication is required. Requests include
    accept: application/json header.

    Usage::

        client = SignalHttpClient()
        data = await client.get("/api/appInventory/suggestions/all")
        data = await client.post("/api/oeReport/intl-oe-wcnp-data-certified", json={...})
    """

    def __init__(self, *, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        self._base_url = cfg.signal_base_url.rstrip("/")
        self._timeout = cfg.signal_timeout
        self._ssl_verify = cfg.signal_verify_ssl
        self._http = _get_shared_http(self._timeout, self._ssl_verify)

        logger.debug(
            "SignalHttpClient ready: base_url=%s timeout=%.1fs",
            self._base_url, self._timeout,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self, *, is_post: bool = False) -> dict[str, str]:
        h: dict[str, str] = {"accept": "application/json"}
        if is_post:
            h["Content-Type"] = "application/json"
        return h

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """
        Make an HTTP request to Signal API.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: URL path (e.g. "/api/appInventory/suggestions/all")

        Raises:
            SignalApiError: Non-2xx HTTP responses.
            SignalConnectionError: Network or timeout failures.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        is_post = method.upper() in ("POST", "PUT", "PATCH")

        if self._http.is_closed:
            self._http = await _get_shared_http_async(
                self._timeout, self._ssl_verify,
            )

        try:
            resp = await self._http.request(
                method=method, url=url,
                headers=self._headers(is_post=is_post),
                **kwargs,
            )
            resp.raise_for_status()
            if not resp.content:
                return {}
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                logger.error(
                    "Non-JSON response from %s (status=%s): %s",
                    url, resp.status_code, resp.text[:200],
                )
                raise SignalApiError(
                    resp.status_code,
                    f"Non-JSON response: {resp.text[:200]}",
                ) from exc

        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            logger.error(
                "HTTP %s %s → %s", method, url, exc.response.status_code,
            )
            raise SignalApiError(exc.response.status_code, body) from exc

        except httpx.ConnectError as exc:
            logger.error("Connect error %s: %s", url, exc)
            raise SignalConnectionError(f"Cannot connect to {url}") from exc

        except httpx.TimeoutException as exc:
            logger.error("Timeout %s after %.1fs", url, self._timeout)
            raise SignalConnectionError(
                f"Request timed out after {self._timeout}s",
            ) from exc

        except (SignalApiError, SignalConnectionError):
            raise

        except Exception as exc:
            logger.error("Unexpected error %s: %s", url, exc)
            raise SignalConnectionError(str(exc)) from exc

    async def get(
        self, path: str, *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        return await self.request("GET", path, params=params)

    async def post(
        self, path: str, *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        return await self.request("POST", path, json=json)
