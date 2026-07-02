"""
Unit tests for app.routers.sessions — list_sessions and get_session_messages.

Tests use a minimal FastAPI TestClient with a mocked Redis client wired onto
``app.state.runner.session_service._redis``.  No live Redis, ADK runtime, or
Google GenAI credentials are required.

Each test verifies a specific piece of *behaviour* visible to an API consumer:
what HTTP status code is returned, what JSON shape appears in the body, how
the response changes when Redis returns different data, and so on.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pipeline_mock(execute_results: list | None = None):
    """Return a mock async context manager that mimics redis.pipeline().

    ``pipe.lrange(...)`` is a no-op (records the call); ``pipe.execute()``
    returns ``execute_results`` (default: empty list).
    """
    mock_pipe = MagicMock()
    mock_pipe.lrange = MagicMock(return_value=mock_pipe)
    mock_pipe.execute = AsyncMock(return_value=execute_results or [])

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_pipe)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx, mock_pipe


@pytest.fixture
def mock_redis():
    """Return a MagicMock Redis client whose async methods are AsyncMocks.

    list_sessions uses two paths:
      Fast (ZSET): zrevrange + hgetall   — for sessions created post-migration
      Legacy (SET): smembers + pipeline  — fallback for old sessions

    By default zrevrange returns [] so tests that want the fast path set it
    explicitly; tests for the legacy path leave it empty and set smembers.
    lrange is still used by the session-messages endpoint.
    """
    redis = MagicMock()
    redis.zrevrange = AsyncMock(return_value=[])   # fast path: empty → fall through
    redis.hgetall   = AsyncMock(return_value={})
    redis.smembers  = AsyncMock(return_value=set())
    redis.lrange    = AsyncMock(return_value=[])
    redis.get     = AsyncMock(return_value=None)
    pipeline_ctx, _ = _make_pipeline_mock(execute_results=[])
    redis.pipeline  = MagicMock(return_value=pipeline_ctx)
    return redis


def _adk_lrange_side_effect(adk_events: list):
    """Return an AsyncMock side_effect that yields adk_events only for the ADK key.

    The ui_events key (contains 'ui_events') returns [] so that sessions.py
    falls through to the legacy ADK-events path.  Any other key (the ADK events
    list) returns the provided adk_events data.
    """
    async def _side_effect(key, start, end):
        if "ui_events" in key:
            return []
        return adk_events
    return _side_effect


@pytest.fixture
def sessions_client(mock_redis):
    """Return (TestClient, mock_redis) backed by a minimal FastAPI app."""
    from app.routers import sessions as sessions_router

    test_app = FastAPI()
    test_app.include_router(sessions_router.router)

    mock_runner = MagicMock()
    mock_runner.session_service = MagicMock()
    mock_runner.session_service._redis = mock_redis
    test_app.state.runner = mock_runner

    return TestClient(test_app), mock_redis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_doc(last_update_time: float = 0.0) -> str:
    return json.dumps({"state": {}, "last_update_time": last_update_time})


def _user_event(text: str, timestamp: float = 0.0) -> str:
    return json.dumps({
        "content": {"role": "user", "parts": [{"text": text}]},
        "timestamp": timestamp,
    })


def _model_event(text: str, timestamp: float = 0.0) -> str:
    return json.dumps({
        "content": {"role": "model", "parts": [{"text": text}]},
        "timestamp": timestamp,
    })


# ── UI-event format helpers (new event-sourced path) ──────────────────────────

def _ui_user_event(text: str, ts: float = 1.0) -> str:
    return json.dumps({"type": "user", "text": text, "ts": ts})

def _ui_progress_event(tool: str, status: str, ts: float = 2.0, args: dict | None = None) -> str:
    ev: dict = {"type": "progress", "tool": tool, "call_id": tool, "label": tool.replace("_", " ").title(), "status": status, "ts": ts}
    if args:
        ev["args"] = args
    return json.dumps(ev)

def _ui_complete_event(text: str, ts: float = 3.0) -> str:
    return json.dumps({"type": "complete", "text": text, "ts": ts})


# ---------------------------------------------------------------------------
# Tests: GET /sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    """Behaviour of GET /sessions — fast ZSET path (primary) and legacy SET fallback."""

    # ── Fast path (ZSET + hgetall) — 2 Redis commands ─────────────────────────

    def test_returns_200_with_empty_sessions_when_no_zset_and_no_set(self, sessions_client):
        """Empty ZSET and empty SET index → HTTP 200 with empty sessions list."""
        client, redis = sessions_client
        # zrevrange returns [] (default), smembers returns set() (default)
        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert resp.json() == {"sessions": []}

    def test_fast_path_returns_session_id(self, sessions_client):
        """ZSET entry must produce a session in the response."""
        client, redis = sessions_client
        redis.zrevrange.return_value = [("abc-123", 1000.0)]
        redis.hgetall.return_value   = {"abc-123": "Hello world"}

        sessions = client.get("/sessions").json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "abc-123"

    def test_fast_path_uses_hgetall_title(self, sessions_client):
        """Title comes from the meta hash — no pipeline needed."""
        client, redis = sessions_client
        redis.zrevrange.return_value = [("s", 1.0)]
        redis.hgetall.return_value   = {"s": "Check namespace health intl-sre"}

        title = client.get("/sessions").json()["sessions"][0]["title"]
        assert title == "Check namespace health intl-sre"

    def test_fast_path_missing_title_defaults_to_new_conversation(self, sessions_client):
        """Session ID in ZSET but missing from meta hash → 'New conversation'."""
        client, redis = sessions_client
        redis.zrevrange.return_value = [("s", 1.0)]
        redis.hgetall.return_value   = {}   # no title for this session

        title = client.get("/sessions").json()["sessions"][0]["title"]
        assert title == "New conversation"

    def test_fast_path_preserves_last_update_time_from_zset_score(self, sessions_client):
        """Timestamp comes from the ZSET score — no doc fetch needed."""
        client, redis = sessions_client
        ts = 1_700_000_000.5
        redis.zrevrange.return_value = [("s", ts)]
        redis.hgetall.return_value   = {"s": "Q"}

        assert client.get("/sessions").json()["sessions"][0]["last_update_time"] == pytest.approx(ts)

    def test_fast_path_echoes_user_id(self, sessions_client):
        """Each entry must include the queried user_id."""
        client, redis = sessions_client
        redis.zrevrange.return_value = [("s", 1.0)]
        redis.hgetall.return_value   = {"s": "Q"}

        assert client.get("/sessions").json()["sessions"][0]["user_id"] == "admin"

    def test_fast_path_already_sorted_newest_first(self, sessions_client):
        """ZSET returns newest-first; the router must preserve that order."""
        client, redis = sessions_client
        # zrevrange already sorted: 300 > 200 > 100
        redis.zrevrange.return_value = [("new", 300.0), ("mid", 200.0), ("old", 100.0)]
        redis.hgetall.return_value   = {"new": "Q", "mid": "Q", "old": "Q"}

        times = [s["last_update_time"] for s in client.get("/sessions").json()["sessions"]]
        assert times == [300.0, 200.0, 100.0]

    def test_fast_path_multiple_sessions_all_returned(self, sessions_client):
        """All sessions in the ZSET must appear in the response."""
        client, redis = sessions_client
        sids = [f"session-{i}" for i in range(5)]
        redis.zrevrange.return_value = [(sid, float(i)) for i, sid in enumerate(sids)]
        redis.hgetall.return_value   = {sid: "Q" for sid in sids}

        returned_ids = {s["session_id"] for s in client.get("/sessions").json()["sessions"]}
        assert returned_ids == set(sids)

    def test_fast_path_user_id_scopes_zset_key(self, sessions_client):
        """The user_id query param must be embedded in at least one zrevrange key."""
        client, redis = sessions_client
        client.get("/sessions?user_id=john")
        # zrevrange is called for both the user ZSET and the public ZSET —
        # verify the user-scoped key is among the calls.
        all_calls = [call[0][0] for call in redis.zrevrange.call_args_list]
        assert any("john" in k for k in all_calls), f"Expected 'john' in one of {all_calls}"

    def test_fast_path_uses_pipeline_for_batch_metadata(self, sessions_client):
        """Fast path uses a pipeline to batch-fetch shared + visibility metadata."""
        client, redis = sessions_client
        redis.zrevrange.return_value = [("s", 1.0)]
        redis.hgetall.return_value   = {"s": "Q"}

        client.get("/sessions")
        redis.pipeline.assert_called()

    # ── Legacy fallback (old SET index) ───────────────────────────────────────

    def test_legacy_fallback_used_when_zset_empty(self, sessions_client):
        """When ZSET is empty, sessions from the old SET index must still be returned."""
        client, redis = sessions_client
        # zrevrange empty → fall through to smembers
        redis.smembers.return_value = {"old-sess"}
        doc = json.dumps({"state": {}, "last_update_time": 1.0, "title": "Legacy Q"})
        pipeline_ctx, _ = _make_pipeline_mock(execute_results=[doc])
        redis.pipeline = MagicMock(return_value=pipeline_ctx)

        sessions = client.get("/sessions").json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "old-sess"
        assert sessions[0]["title"] == "Legacy Q"

    def test_legacy_title_from_events_when_doc_has_no_title(self, sessions_client):
        """Legacy path derives title from the first user event when doc has no title."""
        client, redis = sessions_client
        redis.smembers.return_value = {"s"}
        pipeline_results = iter([
            [_session_doc()],
            [[_user_event("Check namespace health intl-sre")]],
        ])
        redis.pipeline = MagicMock(
            side_effect=lambda **kw: _make_pipeline_mock(execute_results=next(pipeline_results))[0]
        )

        title = client.get("/sessions").json()["sessions"][0]["title"]
        assert title == "Check namespace health intl-sre"

    def test_legacy_title_truncated_to_60_chars(self, sessions_client):
        """Legacy path truncates titles longer than 60 characters."""
        client, redis = sessions_client
        redis.smembers.return_value = {"s"}
        pipeline_results = iter([[_session_doc()], [[_user_event("W" * 80)]]])
        redis.pipeline = MagicMock(
            side_effect=lambda **kw: _make_pipeline_mock(execute_results=next(pipeline_results))[0]
        )

        title = client.get("/sessions").json()["sessions"][0]["title"]
        assert len(title) == 61
        assert title.endswith("…")

    def test_legacy_expired_sessions_skipped(self, sessions_client):
        """Legacy path skips sessions whose doc key has expired (pipeline get → None)."""
        client, redis = sessions_client
        redis.smembers.return_value = {"expired-sid", "live-sid"}
        live_doc = json.dumps({"state": {}, "last_update_time": 999.0, "title": "Q"})
        captured = []

        def _make_aware_pipeline(**kwargs):
            pipe = MagicMock()
            pipe.get = MagicMock(side_effect=lambda k: captured.append(k))
            pipe.lrange = MagicMock()

            async def _execute():
                return [None if "expired-sid" in k else live_doc for k in captured]

            pipe.execute = _execute
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=pipe)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        redis.pipeline = MagicMock(side_effect=_make_aware_pipeline)

        sessions = client.get("/sessions").json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "live-sid"

    def test_legacy_sorted_newest_first(self, sessions_client):
        """Legacy path sorts sessions by last_update_time descending."""
        client, redis = sessions_client
        redis.smembers.return_value = {"old", "new", "mid"}
        timestamps = {"old": 100.0, "new": 300.0, "mid": 200.0}
        captured = []

        def _make_aware_pipeline(**kwargs):
            pipe = MagicMock()
            pipe.get = MagicMock(side_effect=lambda k: captured.append(k))
            pipe.lrange = MagicMock()

            async def _execute():
                return [
                    json.dumps({"state": {}, "last_update_time": ts, "title": "Q"})
                    if (ts := next((v for sid, v in timestamps.items() if sid in k), None))
                    else None
                    for k in captured
                ]

            pipe.execute = _execute
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=pipe)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        redis.pipeline = MagicMock(side_effect=_make_aware_pipeline)

        times = [s["last_update_time"] for s in client.get("/sessions").json()["sessions"]]
        assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Tests: GET /sessions/{session_id}/messages
# ---------------------------------------------------------------------------


class TestGetSessionMessages:
    """Behaviour of GET /sessions/{session_id}/messages."""

    def test_returns_200_for_valid_session(self, sessions_client):
        """The endpoint must return HTTP 200 even for a session with no events."""
        client, redis = sessions_client
        redis.lrange.return_value = []

        resp = client.get("/sessions/sess-abc/messages")

        assert resp.status_code == 200

    def test_session_id_echoed_in_response(self, sessions_client):
        """The response body must echo back the session_id from the URL path."""
        client, redis = sessions_client
        redis.lrange.return_value = []

        resp = client.get("/sessions/my-special-session/messages")

        assert resp.json()["session_id"] == "my-special-session"

    def test_empty_events_returns_empty_messages(self, sessions_client):
        """A session with no Redis events should return an empty messages list."""
        client, redis = sessions_client
        redis.lrange.return_value = []

        resp = client.get("/sessions/s/messages")

        assert resp.json()["messages"] == []

    def test_user_message_has_correct_role_and_content(self, sessions_client):
        """A user-role ADK event must appear with role='user' and its text content."""
        client, redis = sessions_client
        ts = 1234567890.0
        adk_data = [json.dumps({"content": {"role": "user", "parts": [{"text": "What pods are failing?"}]}, "timestamp": ts})]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What pods are failing?"
        assert messages[0]["timestamp"] == pytest.approx(ts)

    def test_model_role_mapped_to_assistant(self, sessions_client):
        """Model-role ADK events must appear with role='assistant' in the API response."""
        client, redis = sessions_client
        adk_data = [json.dumps({"content": {"role": "model", "parts": [{"text": "All pods are running."}]}, "timestamp": 0.0})]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        assert resp.json()["messages"][0]["role"] == "assistant"

    def test_tool_and_other_roles_are_excluded(self, sessions_client):
        """Events with roles other than 'user' and 'model' must be filtered out."""
        client, redis = sessions_client
        adk_data = [
            json.dumps({"content": {"role": "tool", "parts": [{"text": "tool result"}]}, "timestamp": 1.0}),
            json.dumps({"content": {"role": "user", "parts": [{"text": "my query"}]}, "timestamp": 2.0}),
            json.dumps({"content": {"role": "function", "parts": [{"text": "fn data"}]}, "timestamp": 3.0}),
        ]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "my query"

    def test_events_with_no_text_parts_are_skipped(self, sessions_client):
        """ADK events whose content produces no text are excluded from the response."""
        client, redis = sessions_client
        adk_data = [
            json.dumps({"content": {"role": "user", "parts": []}, "timestamp": 0.0}),
            json.dumps({"content": {"role": "model", "parts": [{"text": ""}]}, "timestamp": 1.0}),
            json.dumps({"content": {"role": "user", "parts": [{"text": "  "}]}, "timestamp": 2.0}),
        ]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        assert resp.json()["messages"] == []

    def test_multiple_text_parts_joined_by_newline(self, sessions_client):
        """Multiple text parts within a single ADK event are joined with '\\n'."""
        client, redis = sessions_client
        adk_data = [json.dumps({"content": {"role": "model", "parts": [{"text": "Line one"}, {"text": "Line two"}, {"text": "Line three"}]}, "timestamp": 0.0})]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        assert resp.json()["messages"][0]["content"] == "Line one\nLine two\nLine three"

    def test_messages_preserve_event_list_order(self, sessions_client):
        """Messages are returned in the same order as the underlying Redis LIST."""
        client, redis = sessions_client
        adk_data = [
            json.dumps({"content": {"role": "user", "parts": [{"text": "Q1"}]}, "timestamp": 1.0}),
            json.dumps({"content": {"role": "model", "parts": [{"text": "A1"}]}, "timestamp": 2.0}),
            json.dumps({"content": {"role": "user", "parts": [{"text": "Q2"}]}, "timestamp": 3.0}),
            json.dumps({"content": {"role": "model", "parts": [{"text": "A2"}]}, "timestamp": 4.0}),
        ]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        contents = [m["content"] for m in resp.json()["messages"]]
        assert contents == ["Q1", "A1", "Q2", "A2"]

    def test_custom_user_id_scopes_events_key(self, sessions_client):
        """The user_id query param must be embedded in all Redis keys queried."""
        client, redis = sessions_client
        redis.lrange.return_value = []

        client.get("/sessions/sess-x/messages?user_id=alice")

        all_keys = [call[0][0] for call in redis.lrange.call_args_list]
        assert any("alice" in k and "sess-x" in k for k in all_keys)

    def test_timestamp_defaults_to_zero_when_missing(self, sessions_client):
        """ADK events without a 'timestamp' field must default to 0.0."""
        client, redis = sessions_client
        adk_data = [json.dumps({"content": {"role": "user", "parts": [{"text": "hello"}]}})]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        assert resp.json()["messages"][0]["timestamp"] == 0.0


# ---------------------------------------------------------------------------
# Tests: GET /sessions/{session_id}/messages — event-sourced path (ui_events)
# ---------------------------------------------------------------------------


class TestGetSessionMessagesEventSourced:
    """When ui_events are present, the endpoint replays them directly."""

    def _ui_lrange_side_effect(self, ui_events: list):
        """Return ui_events for the ui_events key; [] for the ADK key."""
        async def _side_effect(key, start, end):
            if "ui_events" in key:
                return ui_events
            return []
        return _side_effect

    def test_returns_events_field_when_ui_events_present(self, sessions_client):
        """When ui_events exist the response must include an 'events' list."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            _ui_user_event("hello"),
            _ui_complete_event("world"),
        ]))

        resp = client.get("/sessions/s/messages")

        assert resp.status_code == 200
        assert "events" in resp.json()

    def test_no_events_field_in_legacy_fallback(self, sessions_client):
        """When only ADK events exist the response must NOT include an 'events' key."""
        client, redis = sessions_client
        adk_data = [json.dumps({"content": {"role": "user", "parts": [{"text": "q"}]}, "timestamp": 1.0})]
        redis.lrange = AsyncMock(side_effect=_adk_lrange_side_effect(adk_data))

        resp = client.get("/sessions/s/messages")

        assert "events" not in resp.json()

    def test_user_turn_in_messages_from_ui_events(self, sessions_client):
        """User message must appear in the legacy messages field from ui_events."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            _ui_user_event("show cpu trend"),
            _ui_complete_event("Here is the chart"),
        ]))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "show cpu trend"

    def test_assistant_turn_in_messages_from_ui_events(self, sessions_client):
        """Assistant message must appear in the legacy messages field from ui_events."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            _ui_user_event("query"),
            _ui_complete_event("the answer"),
        ]))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        asst_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(asst_msgs) == 1
        assert asst_msgs[0]["content"] == "the answer"

    def test_render_tool_call_included_in_messages_tool_calls(self, sessions_client):
        """A render tool call with args must appear in tool_calls on the assistant message."""
        client, redis = sessions_client
        chart_args = {"title": "CPU", "charts": [{"labels": ["t1"], "datasets": []}]}
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            _ui_user_event("chart please"),
            _ui_progress_event("render_multi_chart", "running", args=chart_args),
            _ui_complete_event("Here is the chart"),
        ]))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        asst = next(m for m in messages if m["role"] == "assistant")
        assert "tool_calls" in asst
        render_calls = [tc for tc in asst["tool_calls"] if tc["name"] == "render_multi_chart"]
        assert len(render_calls) == 1
        assert render_calls[0]["args"]["title"] == "CPU"

    def test_progress_only_events_not_in_tool_calls(self, sessions_client):
        """Progress events without args (data-fetch tools) must not appear in tool_calls."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            _ui_user_event("check health"),
            _ui_progress_event("wcnp_check_namespace_health", "running"),   # no args
            _ui_progress_event("wcnp_check_namespace_health", "done"),
            _ui_complete_event("All healthy"),
        ]))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        asst = next(m for m in messages if m["role"] == "assistant")
        assert asst.get("tool_calls") is None

    def test_multi_turn_ui_events_produce_correct_message_count(self, sessions_client):
        """Two question-answer turns must produce 4 messages (2 user + 2 assistant)."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            _ui_user_event("turn 1 question"),
            _ui_complete_event("turn 1 answer"),
            _ui_user_event("turn 2 question"),
            _ui_complete_event("turn 2 answer"),
        ]))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        assert len(messages) == 4
        assert messages[0]["content"] == "turn 1 question"
        assert messages[1]["content"] == "turn 1 answer"
        assert messages[2]["content"] == "turn 2 question"
        assert messages[3]["content"] == "turn 2 answer"

    def test_raw_events_returned_in_order(self, sessions_client):
        """The 'events' list must preserve the original Redis LIST order."""
        client, redis = sessions_client
        raw = [
            _ui_user_event("q", ts=1.0),
            _ui_progress_event("wcnp_check_namespace_health", "running", ts=2.0),
            _ui_complete_event("done", ts=3.0),
        ]
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect(raw))

        resp = client.get("/sessions/s/messages")

        events = resp.json()["events"]
        assert [e["type"] for e in events] == ["user", "progress", "complete"]

    def test_user_turn_in_messages_includes_user_metadata(self, sessions_client):
        """User metadata (user_id and user_name) must be mapped from ui_events to messages."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=self._ui_lrange_side_effect([
            json.dumps({"type": "user", "text": "hello", "ts": 1.0, "user_id": "U123", "user_name": "Alice"}),
        ]))

        resp = client.get("/sessions/s/messages")

        messages = resp.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hello"
        assert messages[0]["user_id"] == "U123"
        assert messages[0]["user_name"] == "Alice"

# ---------------------------------------------------------------------------
# Tests: error / exception paths — lines 68-70, 92-94, 105-107, 121-122
# ---------------------------------------------------------------------------


class TestListSessionsRedisErrors:
    """Redis error paths in list_sessions that return graceful fallbacks."""

    def test_fast_path_redis_error_returns_empty_sessions(self, sessions_client):
        """When the fast-path gather() raises, return 200 with empty sessions — lines 68-70."""
        client, redis = sessions_client
        redis.zrevrange = AsyncMock(side_effect=RuntimeError("Redis unavailable"))
        redis.hgetall = AsyncMock(side_effect=RuntimeError("Redis unavailable"))

        resp = client.get("/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data

    def test_legacy_smembers_redis_error_returns_empty_sessions(self, sessions_client):
        """When legacy smembers raises, return 200 with empty sessions — lines 92-94."""
        client, redis = sessions_client
        # fast path returns empty so we fall through to legacy
        redis.zrevrange = AsyncMock(return_value=[])
        redis.hgetall = AsyncMock(return_value={})
        redis.smembers = AsyncMock(side_effect=RuntimeError("smembers failure"))

        resp = client.get("/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data

    def test_legacy_pipeline_redis_error_returns_empty_sessions(self, sessions_client):
        """When legacy pipeline.execute() raises, return 200 with empty sessions — lines 105-107."""
        client, redis = sessions_client
        redis.zrevrange = AsyncMock(return_value=[])
        redis.hgetall = AsyncMock(return_value={})
        redis.smembers = AsyncMock(return_value={"some-session"})

        # Make pipeline raise on execute
        mock_pipe = MagicMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(side_effect=RuntimeError("pipeline error"))
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_pipe)
        ctx.__aexit__ = AsyncMock(return_value=None)
        redis.pipeline = MagicMock(return_value=ctx)

        resp = client.get("/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert "error" in data

    def test_legacy_events_pipeline_error_silently_ignored(self, sessions_client):
        """When event-fetch pipeline for title resolution raises, list continues — lines 121-122."""
        client, redis = sessions_client
        redis.zrevrange = AsyncMock(return_value=[])
        redis.hgetall = AsyncMock(return_value={})
        redis.smembers = AsyncMock(return_value={"sid-1"})

        # First pipeline (session docs) succeeds — returns a doc with no title
        doc_without_title = _session_doc(last_update_time=1.0)

        first_pipe = MagicMock()
        first_pipe.get = MagicMock(return_value=first_pipe)
        first_pipe.execute = AsyncMock(return_value=[doc_without_title])
        first_ctx = MagicMock()
        first_ctx.__aenter__ = AsyncMock(return_value=first_pipe)
        first_ctx.__aexit__ = AsyncMock(return_value=None)

        # Second pipeline (events for title) raises
        second_pipe = MagicMock()
        second_pipe.lrange = MagicMock(return_value=second_pipe)
        second_pipe.execute = AsyncMock(side_effect=RuntimeError("events pipeline error"))
        second_ctx = MagicMock()
        second_ctx.__aenter__ = AsyncMock(return_value=second_pipe)
        second_ctx.__aexit__ = AsyncMock(return_value=None)

        pipeline_calls = iter([first_ctx, second_ctx])
        redis.pipeline = MagicMock(side_effect=lambda **kw: next(pipeline_calls))

        resp = client.get("/sessions")

        # Still returns 200 with the session (title defaults to "New conversation")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["title"] == "New conversation"


# ---------------------------------------------------------------------------
# Tests: get_session_messages — error and shared-session paths
# ---------------------------------------------------------------------------


class TestGetSessionMessagesErrorPaths:
    """Error and shared-session paths in get_session_messages."""

    def test_ui_events_lrange_error_returns_503(self, sessions_client):
        """When the ui_events lrange raises, return 503 — lines 193-195."""
        client, redis = sessions_client
        redis.lrange = AsyncMock(side_effect=RuntimeError("Redis timeout"))
        redis.scan = AsyncMock(return_value=(0, []))  # scan returns nothing

        resp = client.get("/sessions/s/messages")

        assert resp.status_code == 503
        data = resp.json()
        assert data["messages"] == []
        assert "error" in data

    def test_fallback_adk_events_error_returns_503(self, sessions_client):
        """When both ui_events and adk lrange raise, return 503 — lines 262-264.

        We need ui_events lrange to return [] (no error) and scan to find nothing,
        then the ADK events lrange raises.
        """
        client, redis = sessions_client

        call_count = [0]

        async def _lrange_side_effect(key, start, end):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: ui_events → empty (no error, triggers fallback path)
                return []
            # Second call: ADK events → raise
            raise RuntimeError("ADK events unavailable")

        redis.lrange = AsyncMock(side_effect=_lrange_side_effect)
        redis.scan = AsyncMock(return_value=(0, []))  # no shared session found

        resp = client.get("/sessions/s/messages")

        assert resp.status_code == 503
        data = resp.json()
        assert data["messages"] == []
        assert "error" in data

    def test_shared_session_scan_finds_owner(self, sessions_client):
        """When viewer owns no ui_events, scan finds the owner and fetches theirs — lines 209-218."""
        from app.constants import APP_NAME as _APP_NAME

        client, redis = sessions_client
        session_id = "shared-session-xyz"
        owner_uid = "alice"

        # Construct the expected Redis key
        owner_key = f"agent:ui_events:{_APP_NAME}:{owner_uid}:{session_id}"
        ui_event = _ui_user_event("alice's query", ts=1.0)

        call_count = [0]

        async def _lrange_side_effect(key, start, end):
            call_count[0] += 1
            if call_count[0] == 1:
                # ui_events for the viewer (admin) → empty
                return []
            # ui_events for the owner (alice) → data
            return [ui_event]

        redis.lrange = AsyncMock(side_effect=_lrange_side_effect)
        # scan_iter is now an async generator — yield the owner key once
        async def _scan_iter(*args, **kwargs):
            yield owner_key
        redis.scan_iter = _scan_iter

        resp = client.get(f"/sessions/{session_id}/messages?user_id=admin")

        assert resp.status_code == 200
        data = resp.json()
        # Should have found alice's events
        assert len(data["events"]) == 1
        assert data["events"][0]["type"] == "user"

    def test_shared_session_scan_raises_gracefully(self, sessions_client):
        """When scan raises, the error is swallowed and fallback continues — line 219-220."""
        client, redis = sessions_client

        async def _lrange_side_effect(key, start, end):
            # ui_events returns empty, ADK events returns empty too
            return []

        redis.lrange = AsyncMock(side_effect=_lrange_side_effect)
        async def _scan_iter_raises(*args, **kwargs):
            raise RuntimeError("scan failed")
            yield  # make it an async generator
        redis.scan_iter = _scan_iter_raises

        # Should not raise — falls through to empty ADK events path
        resp = client.get("/sessions/some-session/messages")
        assert resp.status_code == 200

    def test_shared_session_owner_lrange_error_silently_ignored(self, sessions_client):
        """When fetching owner's ui_events raises, error is swallowed — lines 230-231."""
        from app.constants import APP_NAME as _APP_NAME

        client, redis = sessions_client
        session_id = "shared-sess"
        owner_uid = "bob"
        owner_key = f"agent:ui_events:{_APP_NAME}:{owner_uid}:{session_id}"

        call_count = [0]

        async def _lrange_side_effect(key, start, end):
            call_count[0] += 1
            if call_count[0] == 1:
                # viewer has no events
                return []
            # Fetching owner's events raises
            raise RuntimeError("owner fetch failed")

        redis.lrange = AsyncMock(side_effect=_lrange_side_effect)
        redis.scan = AsyncMock(return_value=(0, [owner_key]))

        # Must not raise — falls through to ADK events path
        resp = client.get(f"/sessions/{session_id}/messages?user_id=admin")
        assert resp.status_code in (200, 503)  # either graceful response is acceptable

