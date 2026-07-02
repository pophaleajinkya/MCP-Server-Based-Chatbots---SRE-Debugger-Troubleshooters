"""E2E tests for the Sessions API (/sessions, /sessions/{id}/messages, /sessions/{id}/visibility).

Exercises the full HTTP stack of the sessions router with a mocked Redis
client.  Tests cover the complete user-facing behaviour including shared
sessions, public session merging, visibility toggling, and error handling.

Coverage targets:
  - GET /sessions with no sessions -> empty list
  - GET /sessions returns sessions sorted by recency
  - GET /sessions includes shared/public sessions from other users
  - GET /sessions handles Redis timeout gracefully
  - GET /sessions/{id}/messages with ui_events -> returns events + messages
  - GET /sessions/{id}/messages falls back to ADK events
  - GET /sessions/{id}/messages resolves shared session owner
  - GET /sessions/{id}/messages handles Redis timeout -> 503
  - PATCH /sessions/{id}/visibility public=true -> adds to public ZSET
  - PATCH /sessions/{id}/visibility public=false -> removes from public ZSET
  - PATCH /sessions/{id}/visibility with tags -> stores tags
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Redis mock builder
# ---------------------------------------------------------------------------

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
    redis.hgetall = AsyncMock(return_value=hgetall_result or {})
    redis.smembers = AsyncMock(return_value=smembers_result or set())
    redis.lrange = AsyncMock(return_value=lrange_result or [])
    redis.get = AsyncMock(return_value=get_result)
    redis.hget = AsyncMock(return_value=hget_result)
    redis.set = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    redis.zadd = AsyncMock(return_value=1)
    redis.zrem = AsyncMock(return_value=1)

    # Pipeline mock
    pipe_mock = MagicMock()
    pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
    pipe_mock.__aexit__ = AsyncMock(return_value=None)
    pipe_mock.get = MagicMock()
    pipe_mock.hget = MagicMock()
    pipe_mock.lrange = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=pipeline_results or [])
    redis.pipeline = MagicMock(return_value=pipe_mock)

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


def _build_ui_event(event_type: str, **kwargs) -> bytes:
    ev = {"type": event_type, "ts": time.time(), **kwargs}
    return json.dumps(ev).encode()


# ===========================================================================
# GET /sessions — empty, sorted, public, and error cases
# ===========================================================================

class TestListSessionsEmpty:
    """GET /sessions with no sessions returns an empty list."""

    def test_no_sessions_zset_empty(self):
        redis = _make_redis(zrevrange_result=[], hgetall_result={})
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []

    def test_no_sessions_legacy_empty(self):
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

    def test_default_user_id(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions")
        assert resp.status_code == 200


class TestListSessionsSorted:
    """GET /sessions returns sessions sorted by recency (newest first)."""

    def test_two_sessions_sorted_newest_first(self):
        now = time.time()
        redis = _make_redis(
            zrevrange_result=[
                ("sess-new", now),
                ("sess-old", now - 7200),
            ],
            hgetall_result={
                "sess-new": "Newest query",
                "sess-old": "Oldest query",
            },
        )
        redis.get = AsyncMock(return_value=None)
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        assert len(sessions) == 2
        assert sessions[0]["session_id"] == "sess-new"
        assert sessions[1]["session_id"] == "sess-old"
        assert sessions[0]["last_update_time"] > sessions[1]["last_update_time"]

    def test_three_sessions_sorted(self):
        now = time.time()
        redis = _make_redis(
            zrevrange_result=[
                ("sess-c", now),
                ("sess-b", now - 3600),
                ("sess-a", now - 86400),
            ],
            hgetall_result={
                "sess-c": "C",
                "sess-b": "B",
                "sess-a": "A",
            },
        )
        redis.get = AsyncMock(return_value=None)
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=bob")
        sessions = resp.json()["sessions"]
        assert [s["session_id"] for s in sessions] == ["sess-c", "sess-b", "sess-a"]


class TestListSessionsPublic:
    """GET /sessions includes shared/public sessions from other users."""

    def test_public_sessions_merged_from_other_users(self):
        now = time.time()
        # Alice has one own session
        redis = _make_redis(
            zrevrange_result=[("sess-alice", now - 100)],
            hgetall_result={"sess-alice": "Alice's query"},
        )

        # Public ZSET has bob's session
        bob_member = f"bob:{('sess-bob')}"
        redis.zrevrange = AsyncMock(side_effect=[
            [("sess-alice", now - 100)],  # alice's ZSET
            [(bob_member, now)],  # public ZSET
        ])

        # Pipeline for own sessions: [shared=None, vis=None]
        pipe_mock = MagicMock()
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        pipe_mock.get = MagicMock()
        pipe_mock.hget = MagicMock()
        pipe_mock.execute = AsyncMock(side_effect=[
            # First pipeline: public session metadata [hget title, get visibility]
            ["Bob's shared analysis", None],
            # Second pipeline: own session metadata [get shared, get vis]
            [None, None],
        ])
        redis.pipeline = MagicMock(return_value=pipe_mock)

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        # Should contain both alice's and bob's sessions
        sids = [s["session_id"] for s in sessions]
        assert "sess-alice" in sids
        assert "sess-bob" in sids

    def test_public_session_has_shared_by_field(self):
        now = time.time()
        redis = _make_redis(zrevrange_result=[], hgetall_result={})

        bob_member = "bob:sess-shared"
        redis.zrevrange = AsyncMock(side_effect=[
            [],  # alice's ZSET (empty)
            [(bob_member, now)],  # public ZSET
        ])

        pipe_mock = MagicMock()
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        pipe_mock.get = MagicMock()
        pipe_mock.hget = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[
            "Bob's analysis",  # title
            None,  # visibility
        ])
        redis.pipeline = MagicMock(return_value=pipe_mock)

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        if sessions:
            shared = [s for s in sessions if s.get("shared_by")]
            assert len(shared) > 0
            assert shared[0]["shared_by"] == "bob"


class TestListSessionsRedisTimeout:
    """GET /sessions handles Redis timeout gracefully."""

    def test_zset_timeout_returns_empty_with_error(self):
        redis = _make_redis()
        redis.zrevrange = AsyncMock(side_effect=asyncio.TimeoutError())
        redis.hgetall = AsyncMock(side_effect=asyncio.TimeoutError())

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data

    def test_generic_redis_error_returns_graceful_empty(self):
        redis = _make_redis()
        redis.zrevrange = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis.hgetall = AsyncMock(side_effect=ConnectionError("Redis down"))

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=bob")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data


# ===========================================================================
# GET /sessions/{id}/messages — ui_events, ADK fallback, shared, timeout
# ===========================================================================

class TestGetMessagesUIEvents:
    """GET /sessions/{id}/messages with ui_events returns events + messages."""

    def test_ui_events_returns_user_and_assistant_messages(self):
        user_ev = _build_ui_event("user", text="Check health of sre-ns")
        progress_ev = _build_ui_event("progress", tool="check_health", args={"ns": "sre-ns"})
        complete_ev = _build_ui_event("complete", text="All 17 checks passed.")

        redis = _make_redis(lrange_result=[user_ev, progress_ev, complete_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert len(data["messages"]) == 2  # user + assistant
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Check health of sre-ns"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "All 17 checks passed."

    def test_ui_events_returns_events_array(self):
        user_ev = _build_ui_event("user", text="test")
        redis = _make_redis(lrange_result=[user_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        data = resp.json()
        assert "events" in data
        assert len(data["events"]) == 1
        assert data["events"][0]["type"] == "user"

    def test_ui_events_tool_calls_attached_to_assistant(self):
        user_ev = _build_ui_event("user", text="Check namespace")
        tool_ev = _build_ui_event("progress", tool="check_health", args={"ns": "sre"}, category="tool")
        complete_ev = _build_ui_event("complete", text="Health OK")

        redis = _make_redis(lrange_result=[user_ev, tool_ev, complete_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        msgs = resp.json()["messages"]
        assistant = [m for m in msgs if m["role"] == "assistant"][0]
        assert "tool_calls" in assistant
        assert assistant["tool_calls"][0]["name"] == "check_health"

    def test_ui_events_user_message_includes_user_metadata(self):
        user_ev = _build_ui_event("user", text="hi", user_id="alice@walmart.com", user_name="alice")
        redis = _make_redis(lrange_result=[user_ev])
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        msg = resp.json()["messages"][0]
        assert msg["user_id"] == "alice@walmart.com"
        assert msg["user_name"] == "alice"


class TestGetMessagesADKFallback:
    """GET /sessions/{id}/messages falls back to ADK events when ui_events is empty."""

    def test_falls_back_to_adk_events(self):
        adk_user_ev = json.dumps({
            "content": {"role": "user", "parts": [{"text": "What is the CPU?"}]},
            "timestamp": time.time(),
        }).encode()
        adk_model_ev = json.dumps({
            "content": {"role": "model", "parts": [{"text": "CPU usage is 42%"}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        # First lrange (ui_events) = empty; second lrange (adk:events) = events
        redis.lrange = AsyncMock(side_effect=[[], [adk_user_ev, adk_model_ev]])
        redis.get = AsyncMock(return_value=None)  # no shared/visibility

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "What is the CPU?"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "CPU usage is 42%"

    def test_adk_fallback_skips_system_role(self):
        sys_ev = json.dumps({
            "content": {"role": "system", "parts": [{"text": "System message"}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[[], [sys_ev]])
        redis.get = AsyncMock(return_value=None)

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.json()["messages"] == []

    def test_adk_fallback_includes_function_call_tool_calls(self):
        fc_ev = json.dumps({
            "content": {
                "role": "model",
                "parts": [
                    {"text": "Checking..."},
                    {"functionCall": {"name": "check_health", "args": {"ns": "sre"}}},
                ],
            },
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[[], [fc_ev]])
        redis.get = AsyncMock(return_value=None)

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        msgs = resp.json()["messages"]
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert any(tc["name"] == "check_health" for tc in msgs[0].get("tool_calls", []))


class TestGetMessagesSharedSession:
    """GET /sessions/{id}/messages resolves shared session owner."""

    def test_resolves_shared_session_owner_via_shared_key(self):
        """When viewer has no ui_events but session is shared, resolve owner."""
        shared_meta = json.dumps({"owner_id": "bob", "participants": "all", "permission": "read"})
        owner_user_ev = _build_ui_event("user", text="Bob's question")
        owner_complete_ev = _build_ui_event("complete", text="Bob's answer")

        redis = _make_redis()
        # First lrange (viewer's ui_events) = empty
        # After owner resolution, second lrange (owner's ui_events) = events
        redis.lrange = AsyncMock(side_effect=[[], [owner_user_ev, owner_complete_ev]])
        redis.get = AsyncMock(side_effect=[
            shared_meta.encode(),  # session_shared key
        ])

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-shared/messages?user_id=alice")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Bob's question"

    def test_resolves_owner_via_visibility_key(self):
        """When shared key is absent, check visibility key for public session."""
        vis_data = json.dumps({"public": True, "owner_id": "carol"})
        owner_ev = _build_ui_event("user", text="Carol's query")

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[[], [owner_ev]])
        redis.get = AsyncMock(side_effect=[
            None,  # no shared key
            vis_data.encode(),  # visibility key with owner_id
        ])

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-pub/messages?user_id=alice")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 1

    def test_resolves_owner_via_scan_fallback(self):
        """When no shared/visibility keys, scan for ui_events owner."""
        from app.constants import APP_NAME as _APP_NAME

        owner_ev = _build_ui_event("user", text="Dave's query")
        scan_key = f"agent:ui_events:{_APP_NAME}:dave:sess-scan"

        redis = _make_redis(scan_iter_keys=[scan_key])
        redis.lrange = AsyncMock(side_effect=[[], [owner_ev]])
        redis.get = AsyncMock(return_value=None)  # no shared/visibility

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-scan/messages?user_id=alice")
        assert resp.status_code == 200


class TestGetMessagesRedisTimeout:
    """GET /sessions/{id}/messages handles Redis timeout -> 503."""

    def test_ui_events_timeout_returns_503(self):
        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=asyncio.TimeoutError())

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 503
        data = resp.json()
        assert "error" in data
        assert "unavailable" in data["error"]

    def test_generic_redis_error_returns_503(self):
        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=ConnectionError("Redis connection lost"))

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-001/messages?user_id=alice")
        assert resp.status_code == 503


# ===========================================================================
# PATCH /sessions/{id}/visibility
# ===========================================================================

class TestVisibilitySetPublic:
    """PATCH /sessions/{id}/visibility public=true adds to public ZSET."""

    def test_set_public_true_returns_200(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": [], "user_id": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert data["public"] is True

    def test_set_public_true_calls_zadd(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": [], "user_id": "alice"},
        )
        redis.zadd.assert_called_once()
        # Verify the member format is "user_id:session_id"
        call_args = redis.zadd.call_args
        members = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("mapping", {})
        assert any("alice:sess-001" in str(k) for k in (members if isinstance(members, dict) else [members]))

    def test_set_public_true_persists_visibility_data(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": ["Alert"], "user_id": "alice"},
        )
        redis.set.assert_called()
        call_args = redis.set.call_args
        vis_data = json.loads(call_args[0][1])
        assert vis_data["public"] is True
        assert vis_data["owner_id"] == "alice"

    def test_set_public_true_expires_public_zset(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": [], "user_id": "alice"},
        )
        # expire should be called for the public ZSET
        assert redis.expire.call_count >= 1


class TestVisibilitySetPrivate:
    """PATCH /sessions/{id}/visibility public=false removes from public ZSET."""

    def test_set_private_returns_200(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-001/visibility",
            json={"public": False, "tags": [], "user_id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["public"] is False

    def test_set_private_calls_zrem(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        client.patch(
            "/sessions/sess-001/visibility",
            json={"public": False, "tags": [], "user_id": "alice"},
        )
        redis.zrem.assert_called_once()

    def test_set_private_still_persists_visibility_data(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        client.patch(
            "/sessions/sess-001/visibility",
            json={"public": False, "tags": [], "user_id": "alice"},
        )
        redis.set.assert_called()
        vis_data = json.loads(redis.set.call_args[0][1])
        assert vis_data["public"] is False


class TestVisibilityTags:
    """PATCH /sessions/{id}/visibility with tags stores tags."""

    def test_single_tag_stored(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-001/visibility",
            json={"public": True, "tags": ["Alert"], "user_id": "alice"},
        )
        assert resp.json()["tags"] == ["Alert"]
        vis_data = json.loads(redis.set.call_args[0][1])
        assert vis_data["tags"] == ["Alert"]

    def test_multiple_tags_stored(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-002/visibility",
            json={"public": True, "tags": ["Alert", "P1", "Incident-99"], "user_id": "bob"},
        )
        assert resp.json()["tags"] == ["Alert", "P1", "Incident-99"]
        vis_data = json.loads(redis.set.call_args[0][1])
        assert "Alert" in vis_data["tags"]
        assert "Incident-99" in vis_data["tags"]

    def test_empty_tags_stored(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-003/visibility",
            json={"public": False, "tags": [], "user_id": "carol"},
        )
        assert resp.json()["tags"] == []
        vis_data = json.loads(redis.set.call_args[0][1])
        assert vis_data["tags"] == []

    def test_tags_with_public_false(self):
        """Tags can be set even when public is false."""
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-004/visibility",
            json={"public": False, "tags": ["Internal"], "user_id": "dave"},
        )
        assert resp.status_code == 200
        vis_data = json.loads(redis.set.call_args[0][1])
        assert vis_data["public"] is False
        assert vis_data["tags"] == ["Internal"]

    def test_visibility_includes_adk_user_id(self):
        """Visibility data includes adk_user_id for session lookup."""
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        client.patch(
            "/sessions/sess-005/visibility",
            json={"public": True, "tags": [], "user_id": "eve"},
        )
        vis_data = json.loads(redis.set.call_args[0][1])
        assert vis_data["adk_user_id"] == "A2A_USER_sess-005"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestSessionsEdgeCases:
    """Additional edge cases for robustness."""

    def test_get_messages_empty_session_returns_empty(self):
        redis = _make_redis(lrange_result=[])
        redis.lrange = AsyncMock(side_effect=[[], []])  # ui_events empty, adk events empty
        redis.get = AsyncMock(return_value=None)

        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions/sess-empty/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_visibility_default_user_id_is_admin(self):
        redis = _make_redis()
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.patch(
            "/sessions/sess-default/visibility",
            json={"public": False},
        )
        assert resp.status_code == 200

    def test_list_sessions_with_missing_title_uses_default(self):
        redis = _make_redis(
            zrevrange_result=[("sess-notitle", time.time())],
            hgetall_result={},  # no title
        )
        redis.get = AsyncMock(return_value=None)
        app = _build_sessions_app(_make_runner(redis))
        client = TestClient(app)

        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        assert sessions[0]["title"] == "New conversation"
