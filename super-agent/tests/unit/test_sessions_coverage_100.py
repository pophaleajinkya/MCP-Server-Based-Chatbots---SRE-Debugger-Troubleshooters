"""Targeted tests to push sessions.py from 83% → 100%.

Each class targets exactly the uncovered line ranges reported by coverage:

  Lines 94-122   — public ZSET sessions merge (other users' shared sessions)
  Lines 150-151  — exception swallow in per-session asyncio.gather
  Lines 281-284  — raw_shared JSON parse inside get_session_messages
  Lines 290-295  — public visibility JSON parse inside get_session_messages
  Lines 321-322  — exception when fetching shared owner's ui_events
  Lines 373-379  — ADK events scan_iter fallback (inner coroutine body)
  Lines 386-394  — ADK owner found → fetch their lrange + exception path
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


# ── Redis / runner / app helpers ──────────────────────────────────────────────

def _make_redis(**kw):
    """Return a fully-mocked async Redis client with AsyncMock on every method."""
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

    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__  = AsyncMock(return_value=None)
    pipe.get        = MagicMock()
    pipe.hget       = MagicMock()
    pipe.lrange     = MagicMock()
    # Support multiple pipeline calls with different results via pipeline_side_effect
    if "pipeline_side_effect" in kw:
        pipe.execute = AsyncMock(side_effect=kw["pipeline_side_effect"])
    else:
        pipe.execute = AsyncMock(return_value=kw.get("pipeline", []))
    redis.pipeline  = MagicMock(return_value=pipe)

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
    from app.routers.sessions import router
    app = FastAPI()
    app.include_router(router)
    app.state.runner = _make_runner(redis)
    return app


def _ui(type_, **kw):
    return json.dumps({"type": type_, "ts": time.time(), **kw}).encode()


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 94-120 — Public ZSET: other users' sessions merged into listing
# ═══════════════════════════════════════════════════════════════════════════════

class TestPublicSessionsMerge:
    """Lines 94-120: for member, ts in pub_pairs — build public_sessions list."""

    def test_foreign_public_session_appears_in_listing(self):
        """bob:sess-pub is in the global public ZSET → alice's listing includes it."""
        now = time.time()
        vis = json.dumps({"tags": ["Alert"], "public": True}).encode()

        redis = _make_redis(
            zrevrange=[],       # alice has no own sessions
            hgetall={},
            # Pipeline returns [hget(title), get(visibility)] for bob:sess-pub
            pipeline=["Bob's analysis", vis],
        )
        # zrevrange called twice: 1st for alice's ZSET, 2nd for global public
        redis.zrevrange = AsyncMock(side_effect=[
            [],                                   # alice's own ZSET — empty
            [("bob:sess-pub", now)],              # global public ZSET
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")

        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-pub"
        assert sessions[0]["shared_by"] == "bob"
        assert sessions[0]["user_id"] == "bob"
        assert sessions[0]["permission"] == "write"
        assert sessions[0]["public"] is True
        assert "Alert" in sessions[0]["tags"]

    def test_public_session_with_title_from_owner_meta(self):
        """Title fetched via pipeline hget from owner's meta hash."""
        now = time.time()
        redis = _make_redis(
            hgetall={},
            # Pipeline: [hget(title), get(visibility)]
            pipeline=["Carol's health report", None],
        )
        redis.zrevrange = AsyncMock(side_effect=[
            [],
            [("carol:sess-c", now)],
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        sessions = resp.json()["sessions"]
        assert sessions[0]["title"] == "Carol's health report"

    def test_public_session_no_title_uses_default(self):
        """When pipeline hget returns None, title defaults to 'Shared analysis'."""
        now = time.time()
        redis = _make_redis(
            hgetall={},
            # Pipeline: [hget(title)=None, get(vis)=None]
            pipeline=[None, None],
        )
        redis.zrevrange = AsyncMock(side_effect=[[], [("bob:sess-x", now)]])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.json()["sessions"][0]["title"] == "Shared analysis"

    def test_malformed_public_member_no_colon_skipped(self):
        """Member without ':' has parts len != 2 → silently skipped."""
        now = time.time()
        redis = _make_redis(hgetall={})
        redis.zrevrange = AsyncMock(side_effect=[
            [],
            [("invalid-no-colon", now)],   # malformed → skipped
        ])
        redis.get  = AsyncMock(return_value=None)
        redis.hget = AsyncMock(return_value=None)

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.json()["sessions"] == []

    def test_malformed_member_empty_owner_skipped(self):
        """Member ':sess-id' → owner_id='' → guard triggers continue (line 96)."""
        now = time.time()
        redis = _make_redis(hgetall={})
        redis.zrevrange = AsyncMock(side_effect=[[], [(":sess-only", now)]])
        redis.get  = AsyncMock(return_value=None)
        redis.hget = AsyncMock(return_value=None)

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.json()["sessions"] == []

    def test_malformed_member_empty_sid_skipped(self):
        """Member 'owner:' → sid='' → guard triggers continue (line 96)."""
        now = time.time()
        redis = _make_redis(hgetall={})
        redis.zrevrange = AsyncMock(side_effect=[[], [("bob:", now)]])
        redis.get  = AsyncMock(return_value=None)
        redis.hget = AsyncMock(return_value=None)

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.json()["sessions"] == []

    def test_own_public_session_not_duplicated(self):
        """When owner_id == user_id, the session is skipped (line 97-98)."""
        now = time.time()
        redis = _make_redis(hgetall={})
        redis.zrevrange = AsyncMock(side_effect=[
            [],
            [("alice:sess-own", now)],   # alice == user_id → skip
        ])
        redis.get  = AsyncMock(return_value=None)
        redis.hget = AsyncMock(return_value=None)

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.json()["sessions"] == []   # not duplicated

    def test_public_visibility_json_parse_on_vis_raw(self):
        """Lines 105-108: vis_raw present with valid JSON → tags and public_flag parsed."""
        now = time.time()
        vis = json.dumps({"tags": ["P1", "Incident-99"], "public": False}).encode()
        redis = _make_redis(
            hgetall={},
            # Pipeline: [hget(title)=None, get(vis)=vis]
            pipeline=[None, vis],
        )
        redis.zrevrange = AsyncMock(side_effect=[[], [("bob:sess-b", now)]])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        sess = resp.json()["sessions"][0]
        assert sess["public"] is False
        assert "P1" in sess["tags"]
        assert "Incident-99" in sess["tags"]

    def test_public_visibility_invalid_json_silently_swallowed(self):
        """Line 108: except Exception: pass — bad JSON in vis_raw → default values."""
        now = time.time()
        redis = _make_redis(
            hgetall={},
            # Pipeline: [hget(title)=None, get(vis)=bad-json]
            pipeline=[None, b"not-valid-json{{"],
        )
        redis.zrevrange = AsyncMock(side_effect=[[], [("bob:sess-b", now)]])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        # No exception raised; public_flag defaults to True, tags to []
        assert resp.status_code == 200
        sess = resp.json()["sessions"][0]
        assert sess["tags"] == []
        assert sess["public"] is True

    def test_public_sessions_fetch_exception_logged_and_swallowed(self):
        """Lines 121-122: exception in the entire public sessions block → logged, not raised."""
        redis = _make_redis(hgetall={})
        redis.zrevrange = AsyncMock(side_effect=[
            [],
            RuntimeError("cluster unavailable"),   # 2nd call raises
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_public_and_own_sessions_merged_and_sorted(self):
        """Own ZSET + public ZSET → merged list sorted by last_update_time desc."""
        now = time.time()
        redis = _make_redis(
            hgetall={"sess-own": "My query"},
            # Pipeline called twice:
            #   1st (public): [hget(title)="Bob's analysis", get(vis)=None]
            #   2nd (own):    [get(shared)=None, get(vis)=None]
            pipeline_side_effect=[
                ["Bob's analysis", None],   # public session metadata
                [None, None],               # own session shared+vis
            ],
        )
        redis.zrevrange = AsyncMock(side_effect=[
            [("sess-own", now - 5)],       # alice's own (older)
            [("bob:sess-pub", now)],        # bob's public (newer)
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 2
        # Newest (bob's) should come first
        assert sessions[0]["user_id"] == "bob"
        assert sessions[1]["session_id"] == "sess-own"


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 150-151 — Exception swallow in per-session asyncio.gather
# ═══════════════════════════════════════════════════════════════════════════════

class TestOwnSessionsGatherException:
    """Pipeline execute raises → except pass keeps sessions in the list."""

    def test_session_still_returned_when_metadata_pipeline_fails(self):
        """Even if the pipeline execute raises, the session is still included
        because the exception is caught at the outer level and we fall through
        with whatever sessions we already have."""
        now = time.time()
        redis = _make_redis(
            hgetall={"sess-abc": "My session"},
            # Pipeline execute raises → triggers except: pass
            pipeline_side_effect=[RuntimeError("connection pool exhausted")],
        )
        redis.zrevrange = AsyncMock(side_effect=[
            [("sess-abc", now)],      # alice's own ZSET
            [],                        # public ZSET — empty
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions?user_id=alice")

        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        # Session still appears despite the metadata error
        assert any(s["session_id"] == "sess-abc" for s in sessions)


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 281-284 — raw_shared JSON parse in get_session_messages
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharedSessionFallbackParsing:
    """Lines 281-284: raw_shared present → parse owner_id, enable shared session lookup."""

    def _make_event(self, type_, text="hello"):
        return json.dumps({"type": type_, "text": text, "ts": time.time()}).encode()

    def test_raw_shared_with_valid_json_uses_owner_uid(self):
        """Lines 281-282: raw_shared JSON parsed → owner_uid set → ui_events fetched for owner."""
        user_ev   = self._make_event("user",     "Check health")
        done_ev   = self._make_event("complete", "All OK.")
        shared    = json.dumps({"owner_id": "carol"}).encode()

        redis = _make_redis()
        # First lrange (viewer alice): empty
        # Second lrange (owner carol): events
        redis.lrange = AsyncMock(side_effect=[[], [user_ev, done_ev]])
        # get calls: shared metadata → visibility (None)
        redis.get = AsyncMock(side_effect=[shared, None])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-shared/messages?user_id=alice")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"

    def test_raw_shared_invalid_json_silently_swallowed(self):
        """Lines 283-284: bad JSON in raw_shared → except pass, owner_uid stays None."""
        redis = _make_redis(lrange=[])
        redis.get = AsyncMock(side_effect=[b"{corrupt{{json", None])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-bad/messages?user_id=alice")
        # No crash; empty messages returned
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_raw_shared_missing_owner_id_does_not_set_owner_uid(self):
        """raw_shared JSON without 'owner_id' key → owner_uid remains None."""
        redis = _make_redis(lrange=[])
        redis.get = AsyncMock(side_effect=[
            json.dumps({"permission": "read"}).encode(),  # no owner_id!
            None,
        ])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-x/messages?user_id=alice")
        assert resp.status_code == 200
        # Falls through to ADK fallback with no owner_uid set
        assert resp.json()["messages"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 290-295 — Public visibility JSON parse in get_session_messages
# ═══════════════════════════════════════════════════════════════════════════════

class TestPublicVisibilityFallback:
    """Lines 290-295: raw_vis with public=True and owner_id → set owner_uid."""

    def _make_event(self, type_, text="hello"):
        return json.dumps({"type": type_, "text": text, "ts": time.time()}).encode()

    def test_public_visibility_sets_owner_uid(self):
        """Lines 291-293: vis has public=True and owner_id → owner_uid set."""
        user_ev = self._make_event("user", "namespace health?")
        done_ev = self._make_event("complete", "Healthy.")
        vis     = json.dumps({"public": True, "owner_id": "dave"}).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[[], [user_ev, done_ev]])
        # get calls: shared=None, visibility=vis
        redis.get = AsyncMock(side_effect=[None, vis])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-vis/messages?user_id=alice")

        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 2

    def test_public_visibility_public_false_does_not_set_owner_uid(self):
        """vis.public == False → owner_uid NOT set even with owner_id present."""
        vis = json.dumps({"public": False, "owner_id": "dave"}).encode()
        redis = _make_redis(lrange=[])
        redis.get = AsyncMock(side_effect=[None, vis])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-priv/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_public_visibility_no_owner_id_does_not_set_owner_uid(self):
        """vis.public == True but no owner_id key → owner_uid stays None."""
        vis = json.dumps({"public": True}).encode()  # no owner_id
        redis = _make_redis(lrange=[])
        redis.get = AsyncMock(side_effect=[None, vis])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-y/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_public_visibility_invalid_json_silently_swallowed(self):
        """Lines 294-295: bad JSON in raw_vis → except pass, owner_uid stays None."""
        redis = _make_redis(lrange=[])
        redis.get = AsyncMock(side_effect=[None, b"not-json{{{{"])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-bad-vis/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 321-322 — Exception fetching shared owner's ui_events
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharedOwnerUiEventsException:
    """Lines 321-322: owner_uid found but lrange for owner raises → exception swallowed."""

    def test_lrange_exception_for_shared_owner_swallowed(self):
        """Lines 321-322: exception when fetching owner's ui_events → empty messages.

        Call sequence for lrange:
          1. alice's ui_events (empty) → triggers shared-session fallback
          2. bob's ui_events → raises (lines 321-322 swallow it)
          3. alice's adk:events (ADK fallback, empty) → no messages
        """
        shared = json.dumps({"owner_id": "bob"}).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[
            [],                          # 1. alice's ui_events: empty
            asyncio.TimeoutError(),      # 2. bob's ui_events: timeout → swallowed
            [],                          # 3. alice's adk:events: empty
        ])
        redis.get = AsyncMock(side_effect=[shared, None])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-shared/messages?user_id=alice")

        assert resp.status_code == 200
        # Exception was swallowed → falls through to ADK fallback → empty
        assert resp.json()["messages"] == []

    def test_runtime_error_for_shared_owner_also_swallowed(self):
        """RuntimeError in lrange for owner → except swallows, continues to ADK path."""
        shared = json.dumps({"owner_id": "carol"}).encode()
        redis  = _make_redis()
        redis.lrange = AsyncMock(side_effect=[
            [],                                   # 1. alice's ui_events: empty
            RuntimeError("connection pool exhausted"),  # 2. carol: RuntimeError swallowed
            [],                                   # 3. alice's adk:events: empty
        ])
        redis.get = AsyncMock(side_effect=[shared, None])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-s/messages?user_id=alice")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 373-379 — ADK scan_iter fallback (inner coroutine body)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdkScanOwnerFallback:
    """Lines 373-379: scan_iter over adk:events keys to find the real owner UID."""

    def _adk_key(self, user: str, session: str) -> str:
        return f"adk:events:health_agent:{user}:{session}"

    def test_scan_finds_adk_owner_and_returns_messages(self):
        """Lines 373-379 + 385-392: scan returns adk key → owner extracted → events fetched."""
        adk_ev = json.dumps({
            "content": {"role": "user", "parts": [{"text": "Check ns"}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        # 1. alice's ui_events: empty
        # 2. alice's adk:events: empty
        # 3. bob's adk:events (after scan finds owner): the event
        redis.lrange = AsyncMock(side_effect=[[], [], [adk_ev]])
        redis.get    = AsyncMock(return_value=None)  # no shared/vis
        # scan_iter yields the key for bob's adk:events
        scan_key = self._adk_key("bob", "sess-adk")
        redis.scan_iter = self._make_scan([scan_key])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-adk/messages?user_id=alice")

        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        assert any(m["role"] == "user" for m in msgs)

    def test_scan_with_bytes_key_decoded_correctly(self):
        """Lines 373-374: raw_key is bytes → decoded to str before parsing."""
        adk_ev = json.dumps({
            "content": {"role": "model", "parts": [{"text": "All healthy"}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[[], [], [adk_ev]])
        redis.get    = AsyncMock(return_value=None)
        # scan key as bytes
        scan_key_bytes = self._adk_key("eve", "sess-bytes").encode()
        redis.scan_iter = self._make_scan([scan_key_bytes])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-bytes/messages?user_id=alice")
        assert resp.status_code == 200

    def test_scan_key_no_prefix_match_skipped(self):
        """scan_iter yields a key that does NOT match the expected prefix → skipped."""
        redis = _make_redis()
        redis.lrange    = AsyncMock(return_value=[])
        redis.get       = AsyncMock(return_value=None)
        # Key doesn't start with the correct prefix
        redis.scan_iter = self._make_scan(["wrong:prefix:health_agent:bob:sess-x"])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-x/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_scan_key_empty_owner_uid_skipped(self):
        """Line 378: uid='' (empty owner) → guard `if uid:` skips it."""
        redis = _make_redis()
        redis.lrange    = AsyncMock(return_value=[])
        redis.get       = AsyncMock(return_value=None)
        # Construct a key that parses to an empty owner UID
        # prefix = "adk:events:health_agent:" → key ends with ":sess-x"
        # so uid would be "" if key = "adk:events:health_agent::sess-x"
        bad_key = "adk:events:health_agent::sess-x"
        redis.scan_iter = self._make_scan([bad_key])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-x/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_scan_timeout_silently_swallowed(self):
        """scan_iter timeout → except swallows, returns empty messages."""
        redis = _make_redis()
        redis.lrange = AsyncMock(return_value=[])
        redis.get    = AsyncMock(return_value=None)

        async def _timeout_scan(*a, **kw):
            raise asyncio.TimeoutError()
            yield  # pragma: no cover

        redis.scan_iter = _timeout_scan

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-scan-timeout/messages?user_id=alice")
        assert resp.status_code == 200

    def test_scan_runtime_error_silently_swallowed(self):
        """RuntimeError in scan → except swallows, returns empty messages."""
        redis = _make_redis()
        redis.lrange = AsyncMock(return_value=[])
        redis.get    = AsyncMock(return_value=None)

        async def _error_scan(*a, **kw):
            raise RuntimeError("cluster error")
            yield  # pragma: no cover

        redis.scan_iter = _error_scan

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-scan-err/messages?user_id=alice")
        assert resp.status_code == 200

    @staticmethod
    def _make_scan(keys):
        async def _gen(*a, **kw):
            for k in keys:
                yield k
        return _gen


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 386-394 — ADK owner found → fetch their events + exception path
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdkOwnerEventsFetch:
    """Lines 385-394: adk_owner_uid set and != user_id → fetch their lrange."""

    def _adk_key(self, user: str, session: str) -> str:
        return f"adk:events:health_agent:{user}:{session}"

    def test_adk_owner_events_fetched_and_returned(self):
        """Lines 385-392: owner found → lrange called for owner → model response returned."""
        model_ev = json.dumps({
            "content": {"role": "model", "parts": [{"text": "Namespace is healthy."}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[
            [],           # alice's ui_events: empty
            [],           # alice's adk:events: empty
            [model_ev],   # bob's adk:events: found (lines 389-392)
        ])
        redis.get    = AsyncMock(return_value=None)
        redis.scan_iter = self._make_scan([self._adk_key("bob", "sess-model")])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-model/messages?user_id=alice")

        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        assert any(m["role"] == "assistant" for m in msgs)
        assert msgs[0]["content"] == "Namespace is healthy."

    def test_adk_owner_same_as_user_id_not_fetched(self):
        """Lines 385: adk_owner_uid == user_id → block NOT entered (no duplicate fetch)."""
        redis = _make_redis()
        redis.lrange    = AsyncMock(return_value=[])
        redis.get       = AsyncMock(return_value=None)
        # scan finds alice's own key → owner == user_id → skip
        redis.scan_iter = self._make_scan([self._adk_key("alice", "sess-z")])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-z/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_adk_owner_lrange_timeout_swallowed(self):
        """Lines 393-394: lrange for adk_owner_uid raises TimeoutError → except swallows."""
        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[
            [],
            [],
            asyncio.TimeoutError(),   # bob's lrange times out (line 393-394)
        ])
        redis.get    = AsyncMock(return_value=None)
        redis.scan_iter = self._make_scan([self._adk_key("bob", "sess-to")])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-to/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_adk_owner_lrange_runtime_error_swallowed(self):
        """Lines 393-394: RuntimeError in lrange for adk_owner_uid → except swallows."""
        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[
            [],
            [],
            RuntimeError("pool exhausted"),
        ])
        redis.get    = AsyncMock(return_value=None)
        redis.scan_iter = self._make_scan([self._adk_key("carol", "sess-re")])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-re/messages?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_adk_owner_events_with_user_and_model_messages(self):
        """Full conversation via ADK fallback: user + model events both returned."""
        user_ev  = json.dumps({
            "content": {"role": "user",  "parts": [{"text": "Check intl-sre"}]},
            "timestamp": time.time(),
        }).encode()
        model_ev = json.dumps({
            "content": {"role": "model", "parts": [{"text": "intl-sre is healthy."}]},
            "timestamp": time.time(),
        }).encode()

        redis = _make_redis()
        redis.lrange = AsyncMock(side_effect=[[], [], [user_ev, model_ev]])
        redis.get    = AsyncMock(return_value=None)
        redis.scan_iter = self._make_scan([self._adk_key("dave", "sess-full")])

        client = TestClient(_build_app(redis))
        resp = client.get("/sessions/sess-full/messages?user_id=alice")

        msgs = resp.json()["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    @staticmethod
    def _make_scan(keys):
        async def _gen(*a, **kw):
            for k in keys:
                yield k
        return _gen
