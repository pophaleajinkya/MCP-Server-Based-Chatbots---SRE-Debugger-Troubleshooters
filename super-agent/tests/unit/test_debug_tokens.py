"""Unit tests for debug router /debug/tokens endpoint."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


def _make_settings(urls=None, sso_user="u", sso_pass="p"):
    return SimpleNamespace(
        pingfed_url_list=urls or ["https://intl.logs.prod.walmart.com"],
        sso_username=sso_user,
        sso_password=sso_pass,
    )


def _make_debug_app(redis_mock=None, settings=None):
    """Build a test app with the debug router."""
    from app.routers.debug import router

    app = FastAPI()
    app.include_router(router)
    return app, redis_mock, settings


class TestDebugTokens:
    @pytest.mark.asyncio
    @patch("app.routers.debug._get_pingfed_redis")
    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._pingfed_keys")
    @patch("app.routers.debug._bare_host")
    async def test_valid_token(self, mock_bare, mock_keys, mock_settings, mock_get_redis):
        from app.routers.debug import debug_tokens

        now = time.time()
        mock_settings.return_value = _make_settings()
        mock_bare.return_value = "intl.logs.prod.walmart.com"
        mock_keys.return_value = ("token:key", "lock:key", "notify:key")

        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            "access_token": "jwt-token",
            "expires_at": str(now + 3600),
            "refresh_at": str(now + 2700),
            "acquired_by": "pod-1",
            "acquired_at": str(now - 100),
        })
        redis.ttl = AsyncMock(return_value=3500)
        mock_get_redis.return_value = redis

        from fastapi import Request
        from starlette.testclient import TestClient as _TC

        _app = FastAPI()
        from app.routers.debug import router
        _app.include_router(router)
        client = _TC(_app)

        resp = client.get("/debug/tokens")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sso_configured"] is True
        assert len(data["clusters"]) == 1
        assert data["clusters"][0]["status"] == "valid"
        assert data["clusters"][0]["has_token"] is True

    @pytest.mark.asyncio
    @patch("app.routers.debug._get_pingfed_redis")
    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._pingfed_keys")
    @patch("app.routers.debug._bare_host")
    async def test_expired_token(self, mock_bare, mock_keys, mock_settings, mock_get_redis):
        now = time.time()
        mock_settings.return_value = _make_settings()
        mock_bare.return_value = "intl.logs.prod.walmart.com"
        mock_keys.return_value = ("token:key", "lock:key", "notify:key")

        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            "access_token": "jwt-token",
            "expires_at": str(now - 100),  # expired
            "refresh_at": str(now - 200),
        })
        redis.ttl = AsyncMock(return_value=100)
        mock_get_redis.return_value = redis

        _app = FastAPI()
        from app.routers.debug import router
        _app.include_router(router)
        client = TestClient(_app)

        resp = client.get("/debug/tokens")
        data = resp.json()
        assert data["clusters"][0]["status"] == "expired"

    @pytest.mark.asyncio
    @patch("app.routers.debug._get_pingfed_redis")
    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._pingfed_keys")
    @patch("app.routers.debug._bare_host")
    async def test_missing_token(self, mock_bare, mock_keys, mock_settings, mock_get_redis):
        mock_settings.return_value = _make_settings()
        mock_bare.return_value = "intl.logs.prod.walmart.com"
        mock_keys.return_value = ("token:key", "lock:key", "notify:key")

        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={})
        redis.ttl = AsyncMock(return_value=-2)
        mock_get_redis.return_value = redis

        _app = FastAPI()
        from app.routers.debug import router
        _app.include_router(router)
        client = TestClient(_app)

        resp = client.get("/debug/tokens")
        data = resp.json()
        assert data["clusters"][0]["status"] == "missing"

    @pytest.mark.asyncio
    @patch("app.routers.debug._get_pingfed_redis")
    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._pingfed_keys")
    @patch("app.routers.debug._bare_host")
    async def test_stale_token(self, mock_bare, mock_keys, mock_settings, mock_get_redis):
        now = time.time()
        mock_settings.return_value = _make_settings()
        mock_bare.return_value = "intl.logs.prod.walmart.com"
        mock_keys.return_value = ("token:key", "lock:key", "notify:key")

        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            "access_token": "jwt-token",
            "expires_at": str(now + 600),
            "refresh_at": str(now - 10),  # past refresh_at
        })
        redis.ttl = AsyncMock(return_value=500)
        mock_get_redis.return_value = redis

        _app = FastAPI()
        from app.routers.debug import router
        _app.include_router(router)
        client = TestClient(_app)

        resp = client.get("/debug/tokens")
        data = resp.json()
        assert data["clusters"][0]["status"] == "stale"

    @pytest.mark.asyncio
    @patch("app.routers.debug._get_pingfed_redis")
    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._pingfed_keys")
    @patch("app.routers.debug._bare_host")
    async def test_redis_error_returns_error_status(self, mock_bare, mock_keys, mock_settings, mock_get_redis):
        mock_settings.return_value = _make_settings()
        mock_bare.return_value = "intl.logs.prod.walmart.com"
        mock_keys.return_value = ("token:key", "lock:key", "notify:key")

        redis = AsyncMock()
        redis.hgetall = AsyncMock(side_effect=ConnectionError("redis down"))
        redis.ttl = AsyncMock(side_effect=ConnectionError("redis down"))
        mock_get_redis.return_value = redis

        _app = FastAPI()
        from app.routers.debug import router
        _app.include_router(router)
        client = TestClient(_app)

        resp = client.get("/debug/tokens")
        data = resp.json()
        assert data["clusters"][0]["status"] == "redis_error"

    @pytest.mark.asyncio
    @patch("app.routers.debug._get_pingfed_redis")
    @patch("app.routers.debug.get_settings")
    @patch("app.routers.debug._pingfed_keys")
    @patch("app.routers.debug._bare_host")
    async def test_no_sso_configured(self, mock_bare, mock_keys, mock_settings, mock_get_redis):
        # Empty URL list means no clusters to iterate
        mock_settings.return_value = SimpleNamespace(
            pingfed_url_list=[],
            sso_username="",
            sso_password="",
        )
        redis = AsyncMock()
        mock_get_redis.return_value = redis

        _app = FastAPI()
        from app.routers.debug import router
        _app.include_router(router)
        client = TestClient(_app)

        resp = client.get("/debug/tokens")
        data = resp.json()
        assert data["sso_configured"] is False
        assert data["clusters"] == []
