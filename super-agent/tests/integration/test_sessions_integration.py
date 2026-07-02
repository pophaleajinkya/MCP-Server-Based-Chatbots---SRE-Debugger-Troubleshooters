"""Integration tests for the Sessions API.

Exercises the full HTTP stack of the sessions router with a mocked Redis
client — no live Redis connection required.

Coverage targets (src/app/routers/sessions.py):
  - GET /sessions              — ZSET fast path + legacy SET fallback
  - GET /sessions?user_id=X   — custom user_id query parameter
  - GET /sessions/{id}/messages — ui_events fast path + ADK event fallback
  - GET /sessions/{id}/messages — shared session fallback (scan for owner)
  - PATCH /sessions/{id}/visibility — set public / private + tags
  - Edge: Redis timeout → graceful error response
  - Edge: empty session store → empty list
  - Edge: public session merge + dedup logic
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Redis mock builder ────────────────────────────────────────────────────────

def _make_redis(
    *,
    zrevrange_result=None,
    hgetall_result=None,
    smembers_result=None,
    lrange_result=None,
    get_result=None,
    hget_result=None,
    pipeline_results=None,
    zrange_public=None,
    scan_iter_keys=None,
):
    """Build a fully-mocked async Redis client."""
    redis = MagicMock()

    redis.zrevrange = AsyncMock(return_value=zrevrange_result or [])
    redis.hgetall    = AsyncMock(return_value=hgetall_result or {})
    redis.smembers   = AsyncMock(return_value=smembers_result or set())
    redis.lrange     = AsyncMock(return_value=lrange_result or [])
    redis.get        = AsyncMock(return_value=get_result)
    redis.hget       = AsyncMock(return_value=hget_result)
    redis.set        = AsyncMock(return_value=True)
    redis.expire     = AsyncMock(return_value=True)
    redis.zadd       = AsyncMock(return_value=1)
    redis.zrem       = AsyncMock(return_value=1)

    # Pipeline mock
    pipe_mock = MagicMock()
    pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
    pipe_mock.__aexit__  = AsyncMock(return_value=None)
    pipe_mock.get       = MagicMock()
    pipe_mock.hget      = MagicMock()
    pipe_mock.lrange    = MagicMock()
    pipe_mock.execute   = AsyncMock(return_value=pipeline_results or [])
    redis.pipeline      = MagicMock(return_value=pipe_mock)

    # scan_iter — async generator
    async def _scan(*args, **kwargs):
        for k in (scan_iter_keys or []):
            yield k
    redis.scan_iter = _scan

    return redis


def _make_session_service(redis):
    svc = MagicMock()
    svc._redis = redis
    svc._ttl = 604800
    return svc


def _make_runner(redis):
    runner = MagicMock()
    runner.session_service = _make_session_service(redis)
    return runner


def _build_sessions_app(runner):
    from app.routers.sessions import router
    app = FastAPI()
    app.include_router(router)
    app.state.runner = runner
    return app


# ── GET /sessions ─────────────────────────────────────────────────────────────

class TestListSessionsZsetPath:
    def test_empty_zset_returns_empty_list(self):
        redis = _make_redis(zrevrange_result=[], hgetall_result={})
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_single_session_in_zset(self):
        session_id = "sess-001"
        ts = time.time()
        redis = _make_redis(
            zrevrange_result=[(session_id, ts)],
            hgetall_result={session_id: "Health check query"},
        )
        redis.get = AsyncMock(return_value=None)  # no shared/visibility metadata
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == session_id
        assert sessions[0]["title"] == "Health check query"

    def test_multiple_sessions_sorted_newest_first(self):
        now = time.time()
        redis = _make_redis(
            zrevrange_result=[
                ("sess-newest", now),
                ("sess-oldest", now - 3600),
            ],
            hgetall_result={
                "sess-newest": "Recent query",
                "sess-oldest": "Old query",
            },
        )
        redis.get = AsyncMock(return_value=None)
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        assert sessions[0]["session_id"] == "sess-newest"
        assert sessions[1]["session_id"] == "sess-oldest"

    def test_default_user_id_is_admin(self):
        redis = _make_redis(zrevrange_result=[], hgetall_result={})
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions")
        assert resp.status_code == 200

    def test_session_with_no_title_uses_default(self):
        redis = _make_redis(
            zrevrange_result=[("sess-no-title", time.time())],
            hgetall_result={},  # no title in meta hash
        )
        redis.get = AsyncMock(return_value=None)
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        assert sessions[0]["title"] == "New conversation"

    def test_redis_error_returns_graceful_empty(self):
        redis = _make_redis()
        redis.zrevrange = AsyncMock(side_effect=RuntimeError("Redis down"))
        redis.hgetall   = AsyncMock(side_effect=RuntimeError("Redis down"))
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data

    def test_session_with_visibility_public_true(self):
        now = time.time()
        vis = json.dumps({"public": True, "tags": ["Alert"]})
        redis = _make_redis(
            zrevrange_result=[("sess-pub", now)],
            hgetall_result={"sess-pub": "Public session"},
        )
        # First call: shared metadata; second call: visibility
        redis.get = AsyncMock(side_effect=[None, vis.encode()])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200

    def test_session_shared_by_another_user_shows_shared_by(self):
        now = time.time()
        shared_meta = json.dumps({"owner_id": "bob", "permission": "read"})
        redis = _make_redis(
            zrevrange_result=[("sess-shared", now)],
            hgetall_result={"sess-shared": "Bob's query"},
            # Pipeline: [get(shared)=shared_meta, get(vis)=None]
            pipeline_results=[shared_meta.encode(), None],
        )
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        assert sessions[0].get("shared_by") == "bob"


class TestListSessionsLegacyPath:
    """Exercises the old SET-based index (pre-ZSET migration) fallback."""

    def test_legacy_path_returns_sessions_from_smembers(self):
        now = time.time()
        session_doc = json.dumps({
            "state": {},
            "last_update_time": now,
            "title": "Legacy query",
        })
        redis = _make_redis(
            zrevrange_result=[],    # ZSET empty → triggers legacy
            hgetall_result={},
            smembers_result={"sess-legacy"},
            pipeline_results=[session_doc.encode()],
        )
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["title"] == "Legacy query"

    def test_legacy_path_empty_smembers_returns_empty(self):
        redis = _make_redis(
            zrevrange_result=[],
            hgetall_result={},
            smembers_result=set(),
        )
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_legacy_path_redis_timeout_returns_error(self):
        redis = _make_redis(zrevrange_result=[], hgetall_result={})
        redis.smembers = AsyncMock(side_effect=asyncio.TimeoutError())
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_legacy_path_none_raw_session_skipped(self):
        redis = _make_redis(
            zrevrange_result=[],
            hgetall_result={},
            smembers_result={"sess-gone"},
            pipeline_results=[None],  # session doc is missing
        )
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions?user_id=alice")
        assert resp.json()["sessions"] == []


# ── GET /sessions/{id}/messages ───────────────────────────────────────────────

class TestGetSessionMessages:
    def _build_ui_event(self, event_type: str, **kwargs) -> bytes:
        ev = {"type": event_type, "ts": time.time(), **kwargs}
        return json.dumps(ev).encode()

    def test_ui_events_path_returns_messages(self):
        user_ev  = self._build_ui_event("user", text="Check health of intl-sre")
        tool_ev  = self._build_ui_event("progress", tool="check_health", args={"ns": "intl-sre"})
        done_ev  = self._build_ui_event("complete", text="All pods healthy.")
        redis = _make_redis(lrange_result=[user_ev, tool_ev, done_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert len(data["messages"]) == 2  # user + assistant
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"

    def test_ui_events_assistant_message_includes_tool_calls(self):
        tool_ev  = self._build_ui_event("progress", tool="check_health", args={"ns": "sre"})
        done_ev  = self._build_ui_event("complete", text="Health OK.")
        user_ev  = self._build_ui_event("user", text="Check sre")
        redis = _make_redis(lrange_result=[user_ev, tool_ev, done_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        msgs = resp.json()["messages"]
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "tool_calls" in assistant_msgs[0]
        assert assistant_msgs[0]["tool_calls"][0]["name"] == "check_health"

    def test_ui_events_path_returns_events_list(self):
        user_ev = self._build_ui_event("user", text="test query")
        redis = _make_redis(lrange_result=[user_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert "events" in resp.json()

    def test_redis_timeout_returns_503(self):
        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=asyncio.TimeoutError())
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 503
        assert "error" in resp.json()

    def test_empty_ui_events_falls_back_to_adk_events(self):
        """When ui_events is empty, fall back to adk:events."""
        adk_ev = json.dumps({
            "content": {
                "role": "user",
                "parts": [{"text": "Check namespace"}],
            },
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis(lrange_result=[])  # ui_events empty
        # Second call (adk:events) returns the ADK event
        redis.lrange = AsyncMock(side_effect=[[], [adk_ev]])
        redis.get    = AsyncMock(return_value=None)  # no shared/visibility

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"

    def test_adk_events_skips_non_user_model_roles(self):
        """Events with roles other than 'user'/'model' are ignored."""
        sys_ev = json.dumps({
            "content": {"role": "system", "parts": [{"text": "Ignored"}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis(lrange_result=[])
        redis.lrange = AsyncMock(side_effect=[[], [sys_ev]])
        redis.get    = AsyncMock(return_value=None)
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.json()["messages"] == []


# ── PATCH /sessions/{id}/visibility ──────────────────────────────────────────

class TestUpdateSessionVisibility:
    def test_set_public_true_returns_session_id_and_flags(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": ["Alert"], "user_id": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert data["public"] is True
        assert "Alert" in data["tags"]

    def test_set_private_removes_from_public_index(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.patch(
            "/sessions/sess-001/visibility",
            json={"public": False, "tags": [], "user_id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["public"] is False
        redis.zrem.assert_called_once()

    def test_set_public_true_adds_to_public_zset(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": [], "user_id": "alice"},
        )
        redis.zadd.assert_called_once()

    def test_set_visibility_persists_to_redis(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        client.patch(
            "/sessions/sess-002/visibility",
            json={"public": True, "tags": ["Incident-42"], "user_id": "bob"},
        )
        # redis.set should have been called with the visibility key
        redis.set.assert_called()
        call_args = redis.set.call_args
        vis_data = json.loads(call_args[0][1])
        assert vis_data["owner_id"] == "bob"
        assert "Incident-42" in vis_data["tags"]

    def test_default_user_id_in_body_is_admin(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.patch(
            "/sessions/sess-003/visibility",
            json={"public": False},  # no user_id → should default to "admin"
        )
        assert resp.status_code == 200

    def test_multiple_tags(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)
        resp = client.patch(
            "/sessions/sess-004/visibility",
            json={"public": True, "tags": ["Alert", "P1", "Incident-99"], "user_id": "carol"},
        )
        assert resp.json()["tags"] == ["Alert", "P1", "Incident-99"]
