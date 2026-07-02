"""
Async HTTP client for Valid8 API.

Authentication:
    Valid8 uses API key + tenant header authentication.
    Every request includes:
      - X-API-Key: <api_key>    (from VALID8_API_KEY env var)
      - X-Tenant:  <tenant>     (ca / mx, passed per request)
      - Content-Type: application/json

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


class Valid8Error(Exception):
    """Base exception for Valid8 client errors."""


class Valid8ApiError(Valid8Error):
    """HTTP-level API error with status code."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Valid8 API {status_code}: {message}")


class Valid8ConnectionError(Valid8Error):
    """Network-level connection failure."""


_shared_http: httpx.AsyncClient | None = None
_shared_http_lock = asyncio.Lock()
_shared_http_sync_lock = threading.Lock()


async def _get_shared_http_async(
    timeout: float, ssl_verify: bool | str,
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


def _get_shared_http(
    timeout: float, ssl_verify: bool | str,
) -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        return _shared_http
    with _shared_http_sync_lock:
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(
                timeout=timeout, verify=ssl_verify,
            )
    return _shared_http


def _describe_verify(v: bool | str) -> str:
    """Human-readable label for startup logs."""
    if v is True:
        return "on (system trust store)"
    if v is False:
        return "OFF (insecure)"
    return f"on (CA bundle: {v})"


class Valid8HttpClient:
    """
    Async HTTP client for the Valid8 REST API.

    Authentication is via X-API-Key and X-Tenant headers.
    The API key is set at construction time from config; the tenant
    is passed per request since it varies by market (ca / mx).

    Usage::

        client = Valid8HttpClient()
        data = await client.post("/ca/api/orchestrated-query", tenant="ca", json={...})
        data = await client.post("/mx/api/item-status", tenant="mx", json={...})
    """

    def __init__(self, *, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        self._base_url = cfg.valid8_base_url.rstrip("/")
        self._api_key = cfg.valid8_api_key
        self._timeout = cfg.valid8_timeout
        self._ssl_verify = cfg.valid8_verify_ssl
        self._http = _get_shared_http(self._timeout, self._ssl_verify)

        logger.info(
            "Valid8HttpClient ready: base_url=%s timeout=%.1fs api_key=%s verify=%s",
            self._base_url, self._timeout,
            "***" if self._api_key else "<not set>",
            _describe_verify(self._ssl_verify),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self, tenant: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        if tenant:
            h["X-Tenant"] = tenant
        return h

    async def request(
        self,
        method: str,
        path: str,
        *,
        tenant: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to Valid8.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: URL path (e.g. "/ca/api/orchestrated-query")
            tenant: Market tenant for X-Tenant header ("ca" or "mx").
                    Optional — omit for tenant-agnostic endpoints like /health.

        Raises:
            Valid8ApiError: Non-2xx HTTP responses.
            Valid8ConnectionError: Network or timeout failures.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"

        if self._http.is_closed:
            self._http = await _get_shared_http_async(
                self._timeout, self._ssl_verify,
            )

        try:
            resp = await self._http.request(
                method=method, url=url,
                headers=self._headers(tenant),
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
                raise Valid8ApiError(
                    resp.status_code,
                    f"Non-JSON response: {resp.text[:200]}",
                ) from exc

        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            logger.error(
                "HTTP %s %s → %s", method, url, exc.response.status_code,
            )
            raise Valid8ApiError(exc.response.status_code, body) from exc

        except httpx.ConnectError as exc:
            logger.error("Connect error %s: %s", url, exc)
            raise Valid8ConnectionError(f"Cannot connect to {url}") from exc

        except httpx.TimeoutException as exc:
            logger.error("Timeout %s after %.1fs", url, self._timeout)
            raise Valid8ConnectionError(
                f"Request timed out after {self._timeout}s",
            ) from exc

        except (Valid8ApiError, Valid8ConnectionError):
            raise

        except Exception as exc:
            logger.error("Unexpected error %s: %s", url, exc)
            raise Valid8ConnectionError(str(exc)) from exc

    async def get(
        self, path: str, *,
        tenant: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.request("GET", path, tenant=tenant, params=params)

    async def post(
        self, path: str, *,
        tenant: str | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.request("POST", path, tenant=tenant, json=json)
