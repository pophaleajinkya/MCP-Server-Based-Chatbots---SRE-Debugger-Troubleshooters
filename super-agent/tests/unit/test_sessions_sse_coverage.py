"""Tests covering missing lines in sessions.py:

  Lines 192-194  — visibility JSON parse in list_sessions (own sessions)
  Lines 738-812  — subscribe_events SSE endpoint (async generator)
"""

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
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_redis(**kw):
    """Return a fully-mocked async Redis client."""
    redis = MagicMock()
    redis.zrevrange  = AsyncMock(return_value=kw.get("zrevrange", []))
    redis.hgetall    = AsyncMock(return_value=kw.get("hgetall", {}))
    redis.smembers   = AsyncMock(return_value=kw.get("smembers", set()))
    redis.lrange     = AsyncMock(return_value=kw.get("lrange", []))
    redis.get        = AsyncMock(return_value=kw.get("get", None))
    redis.hget       = AsyncMock(return_value=kw.get("hget", None))
    redis.set        = AsyncMock(return_value=True)
    redis.expire     = AsyncMock(return_value=True)
    redis.zadd       = AsyncMock(return_value=1)
    redis.zrem       = AsyncMock(return_value=1)
    redis.xread      = AsyncMock(return_value=kw.get("xread", None))
    redis.initialize = AsyncMock()

    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__  = AsyncMock(return_value=None)
    pipe.get        = MagicMock()
    pipe.hget       = MagicMock()
    pipe.lrange     = MagicMock()
    if "pipeline_side_effect" in kw:
        pipe.execute = AsyncMock(side_effect=kw["pipeline_side_effect"])
    else:
        pipe.execute = AsyncMock(return_value=kw.get("pipeline", []))
    redis.pipeline = MagicMock(return_value=pipe)

    async def _scan(*a, **kw2):
        for k in kw.get("scan_keys", []):
            yield k
    redis.scan_iter = _scan
    return redis


def _make_runner(redis):
    runner = MagicMock()
    svc = MagicMock()
    svc._redis = redis
    svc._ttl   = 604800
    runner.session_service = svc
    return runner


def _build_app(redis):
    app = FastAPI()
    app.include_router(router)
    app.state.runner = _make_runner(redis)
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 192-194 — Visibility JSON parse in own sessions (list_sessions)
# ═══════════════════════════════════════════════════════════════════════════════

class TestListSessionsVisibilityParse:
    """Cover the vis_raw JSON parse branch for own sessions in list_sessions."""

    def test_visibility_metadata_parsed_for_own_session(self):
        """When visibility JSON exists for an own session, public + tags are set."""
        now = time.time()
        vis_json = json.dumps({"public": True, "tags": ["tag1", "tag2"]})

        redis = _make_redis(
            hgetall={},
            # Pipeline results: pairs of [shared_raw, vis_raw] per session
            # shared_raw=None, vis_raw=vis_json
            pipeline=[None, vis_json],
        )
        redis.zrevrange = AsyncMock(side_effect=[
            [("sess-1", now)],  # own sessions
            [],                  # public sessions
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=testuser")

        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-1"
        assert sessions[0]["public"] is True
        assert sessions[0]["tags"] == ["tag1", "tag2"]

    def test_visibility_public_false_and_empty_tags(self):
        """Visibility with public=false and no tags."""
        now = time.time()
        vis_json = json.dumps({"public": False})

        redis = _make_redis(
            hgetall={},
            pipeline=[None, vis_json],
        )
        redis.zrevrange = AsyncMock(side_effect=[
            [("sess-2", now)],
            [],
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=testuser")

        sessions = resp.json()["sessions"]
        assert sessions[0]["public"] is False
        assert sessions[0]["tags"] == []

    def test_visibility_with_shared_metadata(self):
        """Both shared_raw and vis_raw are set for an own session."""
        now = time.time()
        shared_json = json.dumps({"owner_id": "other_user", "permission": "read"})
        vis_json = json.dumps({"public": True, "tags": ["shared"]})

        redis = _make_redis(
            hgetall={},
            pipeline=[shared_json, vis_json],
        )
        redis.zrevrange = AsyncMock(side_effect=[
            [("sess-3", now)],
            [],
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=testuser")

        sessions = resp.json()["sessions"]
        assert sessions[0]["shared_by"] == "other_user"
        assert sessions[0]["permission"] == "read"
        assert sessions[0]["public"] is True
        assert sessions[0]["tags"] == ["shared"]


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 738-812 — subscribe_events SSE endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubscribeEventsSSE:
    """Test the SSE subscribe_events endpoint via its internal event_iter generator."""

    @pytest.mark.asyncio
    async def test_sse_starts_from_dollar_when_no_last_event_id(self):
        """Without Last-Event-ID, initial_id should be '$'."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 1

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(return_value=None)

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Verify xread was called with "$" (not a resume ID)
        call_args = redis.xread.call_args_list[0]
        stream_dict = call_args[0][0]
        stream_values = list(stream_dict.values())
        assert stream_values[0] == "$"

    @pytest.mark.asyncio
    async def test_sse_event_iter_string_entry_id(self):
        """xread returns string entry_id and string data field."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params = MagicMock()
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        # Mock xread to return data then empty
        redis.xread = AsyncMock(side_effect=[
            [("stream-key", [("1776734822169-0", {"data": '{"type":"test"}'})])],
            [],
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert any("id: 1776734822169-0" in c for c in chunks)
        assert any('{"type":"test"}' in c for c in chunks)

    @pytest.mark.asyncio
    async def test_sse_event_iter_bytes_entry_id(self):
        """xread returns bytes entry_id -- should decode."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=[
            [("stream-key", [(b"1776734822169-1", {"data": "hello"})])],
            [],
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert any("id: 1776734822169-1" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_sse_event_iter_bytes_data_field(self):
        """data field as bytes should be decoded to str."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=[
            [("stream-key", [("100-0", {b"data": b'{"msg":"bytes"}'})])],
            [],
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert any('{"msg":"bytes"}' in c for c in chunks)

    @pytest.mark.asyncio
    async def test_sse_event_iter_missing_data_field_skipped(self):
        """Entry with no 'data' key should be skipped (continue)."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=[
            [("stream-key", [("100-0", {"other_field": "value"})])],
            [],
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Should only get a ping from the empty second xread, no data frames
        data_frames = [c for c in chunks if c.startswith("id:")]
        assert len(data_frames) == 0

    @pytest.mark.asyncio
    async def test_sse_event_iter_empty_response_yields_ping(self):
        """xread returning empty/None yields a ': ping' comment."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=[None, None])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        ping_frames = [c for c in chunks if ": ping" in c]
        assert len(ping_frames) >= 1

    @pytest.mark.asyncio
    async def test_sse_event_iter_xread_exception_yields_ping(self):
        """xread raising an exception yields ': ping' and continues."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=[
            ConnectionError("redis down"),
            ConnectionError("redis down"),
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        ping_frames = [c for c in chunks if ": ping" in c]
        assert len(ping_frames) >= 1

    @pytest.mark.asyncio
    async def test_sse_event_iter_cluster_reinit_after_5_failures(self):
        """After 5 consecutive xread failures, redis.initialize() is called."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            # Allow 6 iterations (5 failures + 1 to disconnect)
            return iteration > 6

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=ConnectionError("redis down"))

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # After 5 failures, initialize() should have been called
        assert redis.initialize.await_count >= 1

    @pytest.mark.asyncio
    async def test_sse_event_iter_cluster_reinit_failure_handled(self):
        """redis.initialize() itself can raise without crashing the generator."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)
        redis.initialize = AsyncMock(side_effect=ConnectionError("init failed"))

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 6

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(side_effect=ConnectionError("redis down"))

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Should not crash; pings are emitted
        ping_frames = [c for c in chunks if ": ping" in c]
        assert len(ping_frames) >= 5
        assert redis.initialize.await_count >= 1

    @pytest.mark.asyncio
    async def test_sse_event_iter_disconnected_immediately(self):
        """Client disconnects before any xread -- generator exits cleanly."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = AsyncMock(return_value=True)
        mock_request.app.state.runner.session_service._redis = redis

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert chunks == []
        redis.xread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sse_resume_with_valid_last_event_id_header(self):
        """Valid Last-Event-ID header sets initial_id for resume."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 1

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value="1776734822169-0")
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(return_value=[
            ("stream-key", [("1776734822170-0", {"data": "resumed"})]),
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        # Verify xread was called with the resume ID, not "$"
        call_args = redis.xread.call_args_list[0]
        stream_dict = call_args[0][0]
        stream_values = list(stream_dict.values())
        assert stream_values[0] == "1776734822169-0"

        assert any("resumed" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_sse_resume_with_valid_last_event_id_query_param(self):
        """Valid last_event_id query param used when header is absent."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 1

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value="9999-1")
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(return_value=None)

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        call_args = redis.xread.call_args_list[0]
        stream_dict = call_args[0][0]
        stream_values = list(stream_dict.values())
        assert stream_values[0] == "9999-1"

    @pytest.mark.asyncio
    async def test_sse_invalid_last_event_id_uses_dollar(self):
        """Invalid Last-Event-ID falls back to '$'."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 1

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value="not-a-valid-id")
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        redis.xread = AsyncMock(return_value=None)

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        call_args = redis.xread.call_args_list[0]
        stream_dict = call_args[0][0]
        stream_values = list(stream_dict.values())
        assert stream_values[0] == "$"

    @pytest.mark.asyncio
    async def test_sse_fields_not_dict_skipped(self):
        """If fields is not a dict, raw stays None and entry is skipped."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=None)

        iteration = 0

        async def fake_is_disconnected():
            nonlocal iteration
            iteration += 1
            return iteration > 2

        mock_request = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)
        mock_request.query_params.get = MagicMock(return_value=None)
        mock_request.is_disconnected = fake_is_disconnected
        mock_request.app.state.runner.session_service._redis = redis

        # fields is a list instead of dict
        redis.xread = AsyncMock(side_effect=[
            [("stream-key", [("100-0", [b"data", b"value"])])],
            [],
        ])

        from app.routers.sessions import subscribe_events
        response = await subscribe_events(
            session_id="sess-1",
            request=mock_request,
            user_id="admin",
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        data_frames = [c for c in chunks if c.startswith("id:")]
        assert len(data_frames) == 0
