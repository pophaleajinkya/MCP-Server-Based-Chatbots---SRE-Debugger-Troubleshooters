"""Additional unit tests for sessions router — covers uncovered lines."""

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.routers.sessions import (
    _is_valid_stream_id,
    _user_id_from_headers,
    _resolve_session_owner,
    router,
    VisibilityUpdate,
)


# ── Tests: _is_valid_stream_id ───────────────────────────────────────────────

class TestIsValidStreamId:
    def test_valid_stream_id(self):
        assert _is_valid_stream_id("1776734822169-0") is True

    def test_valid_large_seq(self):
        assert _is_valid_stream_id("100-999") is True

    def test_empty_string(self):
        assert _is_valid_stream_id("") is False

    def test_no_dash(self):
        assert _is_valid_stream_id("12345") is False

    def test_special_dollar(self):
        assert _is_valid_stream_id("$") is False

    def test_special_zero(self):
        assert _is_valid_stream_id("0-0") is True

    def test_letters(self):
        assert _is_valid_stream_id("abc-def") is False

    def test_double_dash(self):
        assert _is_valid_stream_id("100-0-1") is False


# ── Tests: _user_id_from_headers ─────────────────────────────────────────────

class TestUserIdFromHeaders:
    def _make_request(self, headers: dict):
        from starlette.requests import Request
        from starlette.datastructures import Headers
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
        return Request(scope)

    def test_explicit_query_uid_takes_priority(self):
        request = self._make_request({"x-login-id": "header-user"})
        result = _user_id_from_headers(request, "explicit-user")
        assert result == "explicit-user"

    def test_default_uid_falls_through_to_header(self):
        request = self._make_request({"x-login-id": "header-user"})
        result = _user_id_from_headers(request, "admin")
        assert result == "header-user"

    def test_loginid_header_fallback(self):
        request = self._make_request({"loginid": "login-user"})
        result = _user_id_from_headers(request, "admin")
        assert result == "login-user"

    def test_no_headers_returns_query_uid(self):
        request = self._make_request({})
        result = _user_id_from_headers(request, "admin")
        assert result == "admin"

    def test_whitespace_header_ignored(self):
        request = self._make_request({"x-login-id": "   "})
        result = _user_id_from_headers(request, "admin")
        assert result == "admin"


# ── Tests: _resolve_session_owner ────────────────────────────────────────────

class TestResolveSessionOwner:
    @pytest.mark.asyncio
    async def test_shared_record_returns_owner(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[
            json.dumps({"owner_id": "real-owner"}),  # shared lookup
        ])
        result = await _resolve_session_owner(redis, "sid-1", "fallback-user")
        assert result == "real-owner"

    @pytest.mark.asyncio
    async def test_visibility_record_returns_owner(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[
            None,  # shared lookup
            json.dumps({"owner_id": "vis-owner", "public": True}),  # visibility
        ])
        result = await _resolve_session_owner(redis, "sid-1", "fallback-user")
        assert result == "vis-owner"

    @pytest.mark.asyncio
    async def test_no_records_returns_fallback(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        result = await _resolve_session_owner(redis, "sid-1", "fallback-user")
        assert result == "fallback-user"

    @pytest.mark.asyncio
    async def test_redis_error_returns_fallback(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        result = await _resolve_session_owner(redis, "sid-1", "fallback-user")
        assert result == "fallback-user"


# ── Tests: update_session_visibility ─────────────────────────────────────────

def _make_test_app():
    app = FastAPI()
    app.include_router(router)

    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.zadd = AsyncMock()
    redis.zrem = AsyncMock()
    redis.expire = AsyncMock()

    mock_runner = MagicMock()
    mock_runner.session_service._redis = redis
    mock_runner.session_service._ttl = 86400
    app.state.runner = mock_runner

    return app, redis


class TestUpdateSessionVisibility:
    def test_set_public_true(self):
        app, redis = _make_test_app()
        client = TestClient(app)
        resp = client.patch(
            "/sessions/sid-1/visibility",
            json={"public": True, "tags": ["Alert"], "user_id": "owner1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["public"] is True
        assert data["tags"] == ["Alert"]

    def test_set_public_false(self):
        app, redis = _make_test_app()
        client = TestClient(app)
        resp = client.patch(
            "/sessions/sid-1/visibility",
            json={"public": False, "tags": [], "user_id": "owner1"},
        )
        assert resp.status_code == 200
        assert resp.json()["public"] is False


# ── Tests: inject_message ────────────────────────────────────────────────────

class TestInjectMessage:
    def _make_app(self):
        app = FastAPI()
        app.include_router(router)

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)

        pipeline = AsyncMock()
        pipeline.rpush = MagicMock()
        pipeline.expire = MagicMock()
        pipeline.xadd = MagicMock()
        pipeline.execute = AsyncMock(return_value=[])
        redis.pipeline = MagicMock(return_value=pipeline)

        mock_runner = MagicMock()
        mock_runner.session_service._redis = redis
        mock_runner.session_service._ttl = 86400
        app.state.runner = mock_runner

        return app, redis

    def test_basic_inject(self):
        app, redis = self._make_app()
        client = TestClient(app, headers={"x-login-id": "test-user"})
        resp = client.post(
            "/sessions/sid-1/inject_message?user_id=admin",
            json={"content": "## Alert: CPU spike detected"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["session_id"] == "sid-1"

    def test_inject_with_idempotency_key_dedup(self):
        app, redis = self._make_app()
        # First call claims, second is duplicate
        redis.set = AsyncMock(side_effect=[True, False])
        client = TestClient(app, headers={"Idempotency-Key": "lc:INC123:v1"})
        # First request
        resp1 = client.post("/sessions/sid-1/inject_message?user_id=testuser",
                           json={"content": "Alert!"})
        assert resp1.status_code == 200
        assert resp1.json().get("deduplicated") is not True

    def test_inject_dedup_second_call(self):
        app, redis = self._make_app()
        redis.set = AsyncMock(return_value=False)  # Already claimed
        client = TestClient(app, headers={"Idempotency-Key": "lc:INC123:v1"})
        resp = client.post("/sessions/sid-1/inject_message?user_id=testuser",
                          json={"content": "Alert!"})
        assert resp.status_code == 200
        assert resp.json()["deduplicated"] is True

    def test_inject_idempotency_redis_error_falls_through(self):
        app, redis = self._make_app()
        redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
        client = TestClient(app, headers={"Idempotency-Key": "key1"})
        resp = client.post("/sessions/sid-1/inject_message?user_id=testuser",
                          json={"content": "Alert!"})
        # Should fall through and succeed
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestUserIdFromHeadersIntegration:
    """Integration test for header-based user_id resolution in inject_message."""

    def test_inject_uses_x_login_id_header(self):
        app, redis = _make_test_app()

        pipeline = AsyncMock()
        pipeline.rpush = MagicMock()
        pipeline.expire = MagicMock()
        pipeline.xadd = MagicMock()
        pipeline.execute = AsyncMock(return_value=[])
        redis.pipeline = MagicMock(return_value=pipeline)
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)

        client = TestClient(app, headers={"x-login-id": "header-user"})
        resp = client.post(
            "/sessions/sid-1/inject_message?user_id=admin",
            json={"content": "test"},
        )
        assert resp.status_code == 200


# ── Tests: list_sessions with shared metadata ───────────────────────────────

class TestListSessionsSharedMetadata:
    """Cover lines 185-194 — shared session metadata resolution in list_sessions."""

    def _make_pipeline_ctx(self, results):
        """Build an async context manager pipeline mock."""
        pipe = AsyncMock()
        pipe.get = MagicMock()
        pipe.hget = MagicMock()
        pipe.execute = AsyncMock(return_value=results)
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        return pipe

    def test_own_session_with_shared_metadata(self):
        app = FastAPI()
        app.include_router(router)

        redis = AsyncMock()
        # ZSET returns one session
        redis.zrevrange = AsyncMock(side_effect=[
            [("sid-1", 1000.0)],  # own sessions
            [],  # public sessions
        ])
        redis.hgetall = AsyncMock(return_value={"sid-1": "My Session"})

        shared_meta = json.dumps({"owner_id": "other-user", "permission": "read"})
        vis_data = json.dumps({"public": True, "tags": ["Alert"]})
        pipe = self._make_pipeline_ctx([shared_meta, vis_data])
        redis.pipeline = MagicMock(return_value=pipe)

        mock_runner = MagicMock()
        mock_runner.session_service._redis = redis
        app.state.runner = mock_runner

        client = TestClient(app)
        resp = client.get("/sessions?user_id=testuser")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) >= 1
        session = data["sessions"][0]
        assert session["session_id"] == "sid-1"
        assert session["shared_by"] == "other-user"
        assert session["permission"] == "read"

    def test_own_session_with_visibility_tags(self):
        app = FastAPI()
        app.include_router(router)

        redis = AsyncMock()
        redis.zrevrange = AsyncMock(side_effect=[
            [("sid-1", 1000.0)],
            [],
        ])
        redis.hgetall = AsyncMock(return_value={"sid-1": "Test"})

        vis_data = json.dumps({"public": True, "tags": ["Incident"]})
        pipe = self._make_pipeline_ctx([None, vis_data])
        redis.pipeline = MagicMock(return_value=pipe)

        mock_runner = MagicMock()
        mock_runner.session_service._redis = redis
        app.state.runner = mock_runner

        client = TestClient(app)
        resp = client.get("/sessions?user_id=testuser")
        assert resp.status_code == 200
        data = resp.json()
        session = data["sessions"][0]
        assert session.get("public") is True
        assert session.get("tags") == ["Incident"]


# ── Tests: progress event with category ──────────────────────────────────────

class TestProgressEventCategory:
    """Cover line 388 — topic category detection in progress events."""

    def test_messages_include_tool_call_category(self):
        app = FastAPI()
        app.include_router(router)

        redis = AsyncMock()
        ui_events = [
            json.dumps({"type": "user", "text": "check health", "ts": 1.0}),
            json.dumps({"type": "progress", "tool": "check_health", "args": {"ns": "prod"}, "category": "tool", "label": "Checking Health"}),
            json.dumps({"type": "complete", "text": "All healthy", "ts": 2.0}),
        ]
        redis.lrange = AsyncMock(return_value=ui_events)
        redis.get = AsyncMock(return_value=None)

        mock_runner = MagicMock()
        mock_runner.session_service._redis = redis
        app.state.runner = mock_runner

        client = TestClient(app)
        resp = client.get("/sessions/sid-1/messages?user_id=testuser")
        assert resp.status_code == 200
        data = resp.json()
        # Should have 2 messages (user + assistant)
        assert len(data["messages"]) == 2
        assistant_msg = data["messages"][1]
        assert assistant_msg["role"] == "assistant"
        assert len(assistant_msg.get("tool_calls", [])) == 1
        assert assistant_msg["tool_calls"][0]["category"] == "tool"
        assert assistant_msg["tool_calls"][0]["label"] == "Checking Health"
