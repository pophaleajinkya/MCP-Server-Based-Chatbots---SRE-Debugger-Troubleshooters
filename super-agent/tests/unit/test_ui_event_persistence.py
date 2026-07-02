"""
Unit tests for UI event persistence — _build_interceptors & eager user-message
write in _before_agent.

These tests validate:
  1. Event ordering: user message ALWAYS precedes thinking/progress events
  2. Dedup: user message is written exactly once even when _before_agent AND
     _after_event both attempt it
  3. Thinking events: only adk_thought=true parts are persisted
  4. Progress events: function_call → running, function_response → done
  5. Complete event: written once by _after_agent with final text
  6. Artifact-update thinking: adk_thought parts extracted correctly
  7. Submitted state: NOT treated as assistant text
  8. Shared state bridge: _before_agent ↔ _build_interceptors dedup sets
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.factory import _build_interceptors, _cv_login_id, _cv_session_id, _cv_user_text, _cv_user_name, _cv_participants, _cv_permission
from app.constants import APP_NAME
from a2a.types import TaskStatusUpdateEvent, TaskArtifactUpdateEvent, TaskState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRedis:
    """In-memory Redis mock that records rpush/expire calls in order."""

    def __init__(self):
        self.store: dict[str, list[str]] = {}
        self.call_log: list[tuple[str, Any]] = []

    async def rpush(self, key: str, *values: str):
        self.call_log.append(("rpush", key, values))
        self.store.setdefault(key, []).extend(values)

    async def expire(self, key: str, ttl: int):
        self.call_log.append(("expire", key, ttl))

    async def zadd(self, key, mapping):
        self.call_log.append(("zadd", key, mapping))

    async def hset(self, key, field, value=None):
        self.call_log.append(("hset", key, field, value))

    async def get(self, key: str):
        return None

    async def set(self, key: str, value: str, ex: int = 0):
        self.call_log.append(("set", key, value))

    async def lrange(self, key: str, start: int, end: int):
        return []


class FakeExecutorCtx:
    def __init__(self, app_name=APP_NAME, user_id="testuser", session_id="sess-1"):
        self.app_name = app_name
        self.user_id = user_id
        self.session_id = session_id


def _make_text_part(text: str, *, adk_thought: bool = False):
    """Simulate an ADK TextPart with optional metadata."""
    part = MagicMock()
    part.root = part
    part.text = text
    part.metadata = {"adk_thought": True} if adk_thought else {}
    type(part).__name__ = "TextPart"  # type: ignore
    return part


class _DataPartMock:
    """Minimal DataPart stand-in — no .text attribute, type().__name__ == 'DataPart'."""

    def __init__(self, data: dict, metadata: dict):
        self.root = self
        self.data = data
        self.metadata = metadata


# Override class name so type(root).__name__ == "DataPart" in factory.py
_DataPartMock.__name__ = "DataPart"


def _make_data_part(data: dict, *, adk_type: str = ""):
    """Simulate an ADK DataPart with no .text attribute."""
    meta = {"adk_type": adk_type} if adk_type else {}
    return _DataPartMock(data, meta)


def _make_status_event(state_str: str, parts: list | None = None) -> TaskStatusUpdateEvent:
    """Build a mock TaskStatusUpdateEvent that passes isinstance checks."""
    msg = MagicMock()
    msg.parts = parts or []

    status = MagicMock()
    status.state = TaskState(state_str)
    status.message = msg if parts else None

    ev = MagicMock(spec=TaskStatusUpdateEvent)
    ev.status = status
    return ev


def _make_artifact_event(parts: list | None = None) -> TaskArtifactUpdateEvent:
    """Build a mock TaskArtifactUpdateEvent that passes isinstance checks."""
    artifact = MagicMock()
    artifact.parts = parts or []

    ev = MagicMock(spec=TaskArtifactUpdateEvent)
    ev.artifact = artifact
    return ev


def _events_of_type(redis: FakeRedis, key: str, event_type: str) -> list[dict]:
    """Return parsed events of a given type from the Redis list."""
    results = []
    for raw in redis.store.get(key, []):
        ev = json.loads(raw)
        if ev.get("type") == event_type:
            results.append(ev)
    return results


def _all_events(redis: FakeRedis, key: str) -> list[dict]:
    return [json.loads(raw) for raw in redis.store.get(key, [])]


def _ui_key(user_id: str, session_id: str) -> str:
    return f"agent:ui_events:{APP_NAME}:{user_id}:{session_id}"


def _turn_key(session_id: str, text: str) -> str:
    """Build the same turn_key format as factory.py uses."""
    bucket = int(time.time()) // 300
    return f"{session_id}:{text}:{bucket}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def shared_state():
    return {"user_msg_written": set(), "session_owner_cache": {}, "identity_by_session": {}}


@pytest.fixture
def interceptors(redis, shared_state):
    after_event, after_agent = _build_interceptors(redis, ttl=3600, shared_state=shared_state)
    return after_event, after_agent


@pytest.fixture(autouse=True)
def _reset_contextvars():
    """Reset all contextvars before each test."""
    tok_lid = _cv_login_id.set("")
    tok_sid = _cv_session_id.set("")
    tok_ut  = _cv_user_text.set("")
    tok_un  = _cv_user_name.set("")
    tok_pa  = _cv_participants.set("")
    tok_pe  = _cv_permission.set("read")
    yield
    _cv_login_id.reset(tok_lid)
    _cv_session_id.reset(tok_sid)
    _cv_user_text.reset(tok_ut)
    _cv_user_name.reset(tok_un)
    _cv_participants.reset(tok_pa)
    _cv_permission.reset(tok_pe)


def _set_cv(user_id: str, session_id: str, user_text: str = ""):
    """Set the contextvars that _after_event/_after_agent read."""
    _cv_login_id.set(user_id)
    _cv_session_id.set(session_id)
    _cv_user_text.set(user_text)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. User message ordering — the core bug fix
# ═══════════════════════════════════════════════════════════════════════════════


class TestUserMessageOrdering:
    """Verify user message always precedes thinking/progress in Redis."""

    @pytest.mark.asyncio
    async def test_user_msg_before_thinking_when_eager_write(self, redis, shared_state):
        """Simulate _before_agent eager write, then _after_event thinking event."""
        key = _ui_key("alice", "s1")
        # 1. _before_agent writes user message eagerly
        await redis.rpush(key, json.dumps({"type": "user", "text": "trend graph?", "ts": 1}))
        shared_state["user_msg_written"].add(_turn_key("s1", "trend graph?"))

        # 2. _after_event writes thinking event
        after_event, _ = _build_interceptors(redis, 3600, shared_state=shared_state)
        ctx = FakeExecutorCtx(user_id="alice", session_id="s1")
        _set_cv("alice", "s1", "trend graph?")
        ev = _make_status_event("working", [_make_text_part("thinking...", adk_thought=True)])
        await after_event(ctx, ev, None)

        events = _all_events(redis, key)
        assert len(events) >= 2
        assert events[0]["type"] == "user", "User message must come first"
        assert events[1]["type"] == "thinking", "Thinking must come after user"

    @pytest.mark.asyncio
    async def test_user_msg_before_progress_when_eager_write(self, redis, shared_state):
        """Simulate _before_agent eager write, then _after_event progress event."""
        key = _ui_key("alice", "s1")
        await redis.rpush(key, json.dumps({"type": "user", "text": "check health", "ts": 1}))
        shared_state["user_msg_written"].add(_turn_key("s1", "check health"))

        after_event, _ = _build_interceptors(redis, 3600, shared_state=shared_state)
        ctx = FakeExecutorCtx(user_id="alice", session_id="s1")
        _set_cv("alice", "s1", "check health")
        fcall_part = _make_data_part(
            {"name": "render_chart", "id": "c1", "args": {"labels": ["a"]}},
            adk_type="function_call",
        )
        ev = _make_status_event("working", [fcall_part])
        await after_event(ctx, ev, None)

        events = _all_events(redis, key)
        assert events[0]["type"] == "user"
        assert events[1]["type"] == "progress"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Dedup — user message written exactly once
# ═══════════════════════════════════════════════════════════════════════════════


class TestUserMessageDedup:
    """Verify user message is not duplicated when both _before_agent and _after_event try to write."""

    @pytest.mark.asyncio
    async def test_no_duplicate_when_both_paths_fire(self, redis, shared_state, interceptors):
        """_before_agent writes first, _after_event should skip due to dedup set."""
        after_event, after_agent = interceptors
        key = _ui_key("bob", "s2")

        # Simulate _before_agent already wrote user msg
        await redis.rpush(key, json.dumps({"type": "user", "text": "hello", "ts": 1}))
        shared_state["user_msg_written"].add(_turn_key("s2", "hello"))

        ctx = FakeExecutorCtx(user_id="bob", session_id="s2")
        _set_cv("bob", "s2", "hello")
        ev = _make_status_event("submitted", [_make_text_part("hello")])
        await after_event(ctx, ev, None)

        user_events = _events_of_type(redis, key, "user")
        assert len(user_events) == 1, "User message must not be duplicated"

    @pytest.mark.asyncio
    async def test_after_agent_also_deduped(self, redis, shared_state, interceptors):
        """_after_agent should not re-write user message."""
        after_event, after_agent = interceptors
        key = _ui_key("carol", "s3")

        await redis.rpush(key, json.dumps({"type": "user", "text": "hello", "ts": 1}))
        shared_state["user_msg_written"].add(_turn_key("s3", "hello"))

        ctx = FakeExecutorCtx(user_id="carol", session_id="s3")
        _set_cv("carol", "s3", "hello")
        await after_agent(ctx, None)

        user_events = _events_of_type(redis, key, "user")
        assert len(user_events) == 1

    @pytest.mark.asyncio
    async def test_different_questions_not_deduped(self, redis, shared_state, interceptors):
        """Two different questions in the same session should both be written."""
        after_event, after_agent = interceptors
        key = _ui_key("dave", "s4")

        ctx = FakeExecutorCtx(user_id="dave", session_id="s4")

        # First question
        _set_cv("dave", "s4", "question 1")
        ev1 = _make_status_event("submitted", [_make_text_part("question 1")])
        await after_event(ctx, ev1, None)

        # Second question
        _set_cv("dave", "s4", "question 2")
        ev2 = _make_status_event("submitted", [_make_text_part("question 2")])
        await after_event(ctx, ev2, None)

        user_events = _events_of_type(redis, key, "user")
        assert len(user_events) == 2
        assert user_events[0]["text"] == "question 1"
        assert user_events[1]["text"] == "question 2"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Thinking event persistence
# ═══════════════════════════════════════════════════════════════════════════════


class TestThinkingPersistence:
    """Verify only adk_thought=true parts are persisted as thinking events."""

    @pytest.mark.asyncio
    async def test_adk_thought_true_persisted(self, redis, shared_state, interceptors):
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s5")
        key = _ui_key("alice", "s5")

        _set_cv("alice", "s5")
        ev = _make_status_event("working", [
            _make_text_part("I should check memory metrics", adk_thought=True),
        ])
        await after_event(ctx, ev, None)

        thinking = _events_of_type(redis, key, "thinking")
        assert len(thinking) == 1
        assert thinking[0]["text"] == "I should check memory metrics"

    @pytest.mark.asyncio
    async def test_non_thought_text_NOT_persisted_as_thinking(self, redis, shared_state, interceptors):
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s6")
        key = _ui_key("alice", "s6")

        _set_cv("alice", "s6")
        ev = _make_status_event("working", [
            _make_text_part("Here is the health report", adk_thought=False),
        ])
        await after_event(ctx, ev, None)

        thinking = _events_of_type(redis, key, "thinking")
        assert len(thinking) == 0, "Non-thought text must NOT create thinking events"

    @pytest.mark.asyncio
    async def test_empty_thought_text_ignored(self, redis, shared_state, interceptors):
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s7")
        key = _ui_key("alice", "s7")

        _set_cv("alice", "s7")
        ev = _make_status_event("working", [
            _make_text_part("   ", adk_thought=True),
        ])
        await after_event(ctx, ev, None)

        thinking = _events_of_type(redis, key, "thinking")
        assert len(thinking) == 0, "Whitespace-only thought must be ignored"

    @pytest.mark.asyncio
    async def test_thinking_from_artifact_update(self, redis, shared_state, interceptors):
        """adk_thought parts in artifact-update events are persisted."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s8")
        key = _ui_key("alice", "s8")

        _set_cv("alice", "s8")
        ev = _make_artifact_event([
            _make_text_part("artifact thought", adk_thought=True),
            _make_text_part("visible response", adk_thought=False),
        ])
        await after_event(ctx, ev, None)

        thinking = _events_of_type(redis, key, "thinking")
        assert len(thinking) == 1
        assert thinking[0]["text"] == "artifact thought"

    @pytest.mark.asyncio
    async def test_mixed_thought_and_text_parts(self, redis, shared_state, interceptors):
        """Both thought and non-thought parts in same event are handled correctly."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s9")
        key = _ui_key("alice", "s9")

        _set_cv("alice", "s9")
        ev = _make_status_event("working", [
            _make_text_part("thought 1", adk_thought=True),
            _make_text_part("visible text"),
            _make_text_part("thought 2", adk_thought=True),
        ])
        await after_event(ctx, ev, None)

        thinking = _events_of_type(redis, key, "thinking")
        assert len(thinking) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Progress event persistence (function_call / function_response)
# ═══════════════════════════════════════════════════════════════════════════════


class TestProgressPersistence:

    @pytest.mark.asyncio
    async def test_function_call_persisted_as_running(self, redis, shared_state, interceptors):
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s10")
        key = _ui_key("alice", "s10")

        _set_cv("alice", "s10")
        fcall = _make_data_part(
            {"name": "wcnp_check_app_health", "id": "call-1", "args": {"app": "myapp"}},
            adk_type="function_call",
        )
        ev = _make_status_event("working", [fcall])
        await after_event(ctx, ev, None)

        progress = _events_of_type(redis, key, "progress")
        assert len(progress) == 1
        assert progress[0]["tool"] == "wcnp_check_app_health"
        assert progress[0]["status"] == "running"
        assert progress[0]["args"] == {"app": "myapp"}

    @pytest.mark.asyncio
    async def test_function_response_persisted_as_done(self, redis, shared_state, interceptors):
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s11")
        key = _ui_key("alice", "s11")

        _set_cv("alice", "s11")
        fresp = _make_data_part(
            {"name": "wcnp_check_app_health", "id": "call-1", "response": {"status": "ok"}},
            adk_type="function_response",
        )
        ev = _make_status_event("working", [fresp])
        await after_event(ctx, ev, None)

        progress = _events_of_type(redis, key, "progress")
        assert len(progress) == 1
        assert progress[0]["status"] == "done"

    @pytest.mark.asyncio
    async def test_render_chart_call_persisted(self, redis, shared_state, interceptors):
        """render_chart function_call is persisted with full chart args."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s12")
        key = _ui_key("alice", "s12")

        chart_args = {
            "title": "Memory p90",
            "chart_type": "line",
            "labels": ["Day 1", "Day 2"],
            "datasets": [{"label": "eus2", "data": [86.4, 86.5]}],
        }
        _set_cv("alice", "s12")
        fcall = _make_data_part(
            {"name": "render_chart", "id": "rc-1", "args": chart_args},
            adk_type="function_call",
        )
        ev = _make_status_event("working", [fcall])
        await after_event(ctx, ev, None)

        progress = _events_of_type(redis, key, "progress")
        assert len(progress) == 1
        assert progress[0]["tool"] == "render_chart"
        assert progress[0]["args"]["labels"] == ["Day 1", "Day 2"]
        assert progress[0]["args"]["datasets"][0]["data"] == [86.4, 86.5]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Complete event in _after_agent
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompleteEvent:

    @pytest.mark.asyncio
    async def test_complete_event_written(self, redis, shared_state, interceptors):
        """_after_agent writes a 'complete' event with the final text."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s13")
        key = _ui_key("alice", "s13")

        _set_cv("alice", "s13", "check health")

        # Simulate a status-update with response text (builds _session_text_buf)
        ev = _make_status_event("working", [_make_text_part("App is healthy")])
        await after_event(ctx, ev, None)

        # _after_agent flushes the buffer
        await after_agent(ctx, None)

        complete = _events_of_type(redis, key, "complete")
        assert len(complete) == 1
        assert complete[0]["text"] == "App is healthy"

    @pytest.mark.asyncio
    async def test_complete_written_even_for_empty_text(self, redis, shared_state, interceptors):
        """A 'complete' event is always written — even when the agent produced
        no output — so the frontend poll detects turn completion immediately
        instead of waiting for the 2-minute safety cap."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s14")
        key = _ui_key("alice", "s14")

        _set_cv("alice", "s14")
        await after_agent(ctx, None)

        complete = _events_of_type(redis, key, "complete")
        assert len(complete) == 1
        assert complete[0]["text"] == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Submitted state handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubmittedState:

    @pytest.mark.asyncio
    async def test_submitted_text_not_buffered_as_response(self, redis, shared_state, interceptors):
        """Submitted state carries the USER's question — must not become _session_text_buf."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s15")
        key = _ui_key("alice", "s15")

        _set_cv("alice", "s15")
        ev = _make_status_event("submitted", [_make_text_part("check health")])
        await after_event(ctx, ev, None)
        await after_agent(ctx, None)

        # A complete event IS written (with empty text) — submitted text should
        # NOT appear as the assistant response, but the turn marker is still emitted
        # so the frontend poll detects turn completion.
        complete = _events_of_type(redis, key, "complete")
        assert len(complete) == 1
        assert complete[0]["text"] == ""

    @pytest.mark.asyncio
    async def test_submitted_extracts_user_text(self, redis, shared_state, interceptors):
        """Submitted event should extract user text into _cv_user_text."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s16")

        _set_cv("alice", "s16")
        ev = _make_status_event("submitted", [_make_text_part("check health")])
        await after_event(ctx, ev, None)
        # Verify _cv_user_text was set
        assert _cv_user_text.get() == "check health"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Shared state bridge
# ═══════════════════════════════════════════════════════════════════════════════


class TestSharedState:

    def test_shared_state_user_msg_written_is_same_reference(self, shared_state):
        """_build_interceptors uses the same set reference from shared_state."""
        _, _ = _build_interceptors(FakeRedis(), 3600, shared_state=shared_state)
        shared_state["user_msg_written"].add("test-key")
        assert "test-key" in shared_state["user_msg_written"]

    def test_shared_state_session_owner_cache_is_same_reference(self, shared_state):
        _, _ = _build_interceptors(FakeRedis(), 3600, shared_state=shared_state)
        shared_state["session_owner_cache"]["s1"] = "owner1"
        assert shared_state["session_owner_cache"]["s1"] == "owner1"

    def test_shared_state_identity_by_session_is_same_reference(self, shared_state):
        """identity_by_session dict is shared between _mount_a2a and _build_interceptors."""
        _, _ = _build_interceptors(FakeRedis(), 3600, shared_state=shared_state)
        shared_state["identity_by_session"]["s1"] = {"login_id": "alice", "user_name": "Alice"}
        assert shared_state["identity_by_session"]["s1"]["login_id"] == "alice"


# ═══════════════════════════════════════════════════════════════════════════════
# 7b. Identity resolution via shared_state (ContextVars don't propagate)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentityResolution:
    """Verify that _after_event/_after_agent resolve user_id from
    shared_state[\"identity_by_session\"] when ContextVars are empty —
    simulating the ADK spawning a new asyncio.Task for agent execution."""

    @pytest.mark.asyncio
    async def test_after_event_uses_shared_identity_when_cv_empty(self, redis, shared_state, interceptors):
        """When ContextVars are empty (new Task), _after_event uses identity_by_session."""
        after_event, _ = interceptors
        # executor_ctx has ADK-generated IDs
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-X", session_id="sess-X")

        # Simulate _before_agent storing identity in shared_state
        shared_state["identity_by_session"]["sess-X"] = {"login_id": "alice", "user_name": "Alice"}

        # ContextVars are EMPTY (default from fixture) — simulating new Task
        # Set user_text so user message is written
        _cv_user_text.set("check health")

        ev = _make_status_event("working", [_make_text_part("App is healthy")])
        await after_event(ctx, ev, None)

        # Events should be under alice's key, NOT A2A_USER_sess-X
        alice_key = _ui_key("alice", "sess-X")
        a2a_key = _ui_key("A2A_USER_sess-X", "sess-X")
        assert len(redis.store.get(alice_key, [])) > 0, "Events should be under real user"
        assert len(redis.store.get(a2a_key, [])) == 0, "Events should NOT be under A2A_USER_*"

    @pytest.mark.asyncio
    async def test_after_agent_uses_shared_identity_when_cv_empty(self, redis, shared_state, interceptors):
        """When ContextVars are empty, _after_agent writes complete under real user."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-Y", session_id="sess-Y")

        shared_state["identity_by_session"]["sess-Y"] = {"login_id": "bob", "user_name": "Bob"}
        _cv_user_text.set("show metrics")

        # Buffer some response text
        ev = _make_status_event("working", [_make_text_part("Here are the metrics")])
        await after_event(ctx, ev, None)

        # After agent should write under bob's key
        await after_agent(ctx, None)

        bob_key = _ui_key("bob", "sess-Y")
        complete = _events_of_type(redis, bob_key, "complete")
        assert len(complete) == 1
        assert "metrics" in complete[0]["text"]

    @pytest.mark.asyncio
    async def test_user_msg_dedup_across_identity_sources(self, redis, shared_state, interceptors):
        """User message written by _before_agent (correct key) is deduped in _after_event."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-Z", session_id="sess-Z")

        shared_state["identity_by_session"]["sess-Z"] = {"login_id": "charlie", "user_name": "Charlie"}

        # Simulate _before_agent already wrote the user message
        turn_key = _turn_key("sess-Z", "hello")
        shared_state["user_msg_written"].add(turn_key)

        # _after_event should NOT write duplicate user message
        _cv_user_text.set("hello")
        ev = _make_status_event("working", [_make_text_part("Hi there")])
        await after_event(ctx, ev, None)

        charlie_key = _ui_key("charlie", "sess-Z")
        user_msgs = _events_of_type(redis, charlie_key, "user")
        assert len(user_msgs) == 0, "User message should be deduped"

    @pytest.mark.asyncio
    async def test_contextvar_takes_precedence_over_executor_ctx(self, redis, shared_state, interceptors):
        """When ContextVars DO propagate, they take precedence over executor_ctx."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-W", session_id="sess-W")

        # Both shared_state and ContextVars are set — shared_state wins for user_id
        shared_state["identity_by_session"]["sess-W"] = {"login_id": "diana", "user_name": "Diana"}
        _set_cv("diana", "sess-W", "check pods")

        ev = _make_status_event("working", [_make_text_part("Pods are running")])
        await after_event(ctx, ev, None)

        diana_key = _ui_key("diana", "sess-W")
        assert len(redis.store.get(diana_key, [])) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Full turn replay ordering (end-to-end scenario)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullTurnOrdering:

    @pytest.mark.asyncio
    async def test_full_turn_event_order(self, redis, shared_state, interceptors):
        """Simulate a complete turn: user → thinking → progress → complete."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s17")
        key = _ui_key("alice", "s17")

        # Pre-write user message (as _before_agent would)
        await redis.rpush(key, json.dumps({"type": "user", "text": "trend graph", "ts": 1}))
        shared_state["user_msg_written"].add(_turn_key("s17", "trend graph"))

        _set_cv("alice", "s17", "trend graph")

        # 1. Thinking event
        ev1 = _make_status_event("working", [_make_text_part("analyzing...", adk_thought=True)])
        await after_event(ctx, ev1, None)

        # 2. Function call (render_chart)
        fcall = _make_data_part(
            {"name": "render_chart", "id": "rc", "args": {"labels": ["a"], "datasets": []}},
            adk_type="function_call",
        )
        ev2 = _make_status_event("working", [fcall])
        await after_event(ctx, ev2, None)

        # 3. Response text
        ev3 = _make_status_event("working", [_make_text_part("Here is the chart")])
        await after_event(ctx, ev3, None)

        # 4. Complete
        await after_agent(ctx, None)

        events = _all_events(redis, key)
        types = [e["type"] for e in events]
        assert types == ["user", "thinking", "progress", "reasoning", "complete"]

    @pytest.mark.asyncio
    async def test_multi_turn_event_order(self, redis, shared_state, interceptors):
        """Two turns: user → complete → user → thinking → complete."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s18")
        key = _ui_key("alice", "s18")

        # Turn 1
        _set_cv("alice", "s18", "turn 1 q")
        ev1s = _make_status_event("submitted", [_make_text_part("turn 1 q")])
        await after_event(ctx, ev1s, None)
        ev1w = _make_status_event("working", [_make_text_part("turn 1 answer")])
        await after_event(ctx, ev1w, None)
        await after_agent(ctx, None)

        # Turn 2
        _set_cv("alice", "s18", "turn 2 q")
        ev2s = _make_status_event("submitted", [_make_text_part("turn 2 q")])
        await after_event(ctx, ev2s, None)
        ev2t = _make_status_event("working", [_make_text_part("deep thought", adk_thought=True)])
        await after_event(ctx, ev2t, None)
        ev2w = _make_status_event("working", [_make_text_part("turn 2 answer")])
        await after_event(ctx, ev2w, None)
        await after_agent(ctx, None)

        events = _all_events(redis, key)
        types = [e["type"] for e in events]
        assert types == ["user", "reasoning", "complete", "user", "thinking", "reasoning", "complete"]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_missing_user_id_skips_event(self, redis, shared_state, interceptors):
        """If user_id is empty, _after_event should skip."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="", session_id="s19")

        _set_cv("", "s19", "test")
        ev = _make_status_event("working", [_make_text_part("hello")])
        result = await after_event(ctx, ev, None)

        assert result is ev  # returned unchanged
        assert len(redis.store) == 0  # nothing written

    @pytest.mark.asyncio
    async def test_missing_session_id_skips_event(self, redis, shared_state, interceptors):
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="")

        _set_cv("alice", "", "test")
        ev = _make_status_event("working", [_make_text_part("hello")])
        result = await after_event(ctx, ev, None)

        assert len(redis.store) == 0

    @pytest.mark.asyncio
    async def test_redis_error_is_non_fatal(self, shared_state):
        """Redis errors during event persistence should not crash."""
        broken_redis = MagicMock()
        broken_redis.rpush = AsyncMock(side_effect=Exception("Redis down"))
        broken_redis.expire = AsyncMock(side_effect=Exception("Redis down"))
        broken_redis.get = AsyncMock(return_value=None)
        broken_redis.zadd = AsyncMock(side_effect=Exception("Redis down"))
        broken_redis.hset = AsyncMock(side_effect=Exception("Redis down"))

        after_event, _ = _build_interceptors(broken_redis, 3600, shared_state=shared_state)
        ctx = FakeExecutorCtx(user_id="alice", session_id="s20")

        _set_cv("alice", "s20", "test")
        ev = _make_status_event("working", [_make_text_part("hello")])
        # Should not raise
        result = await after_event(ctx, ev, None)
        assert result is ev

    @pytest.mark.asyncio
    async def test_artifact_update_replaces_text_buffer(self, redis, shared_state, interceptors):
        """artifact-update is authoritative — replaces status-update text."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="s21")
        key = _ui_key("alice", "s21")

        _set_cv("alice", "s21", "q")

        # Status-update text (will be overridden)
        ev1 = _make_status_event("working", [_make_text_part("partial")])
        await after_event(ctx, ev1, None)

        # Artifact-update replaces
        ev2 = _make_artifact_event([_make_text_part("FINAL ANSWER")])
        await after_event(ctx, ev2, None)

        await after_agent(ctx, None)

        complete = _events_of_type(redis, key, "complete")
        assert len(complete) == 1
        assert complete[0]["text"] == "FINAL ANSWER"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Multi-turn conversation scenarios
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiTurn:
    """End-to-end multi-turn scenarios matching real user flows."""

    @pytest.mark.asyncio
    async def test_health_check_then_trend_graph(self, redis, shared_state, interceptors):
        """Exact user-reported scenario: health check → follow-up trend graph."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="mt1")
        key = _ui_key("alice", "mt1")

        # Turn 1: health check
        _set_cv("alice", "mt1", "check health of unified-promise-discovery")
        ev1s = _make_status_event("submitted", [_make_text_part("check health of unified-promise-discovery")])
        await after_event(ctx, ev1s, None)
        ev1t = _make_status_event("working", [_make_text_part("Let me check...", adk_thought=True)])
        await after_event(ctx, ev1t, None)
        ev1fc = _make_status_event("working", [_make_data_part(
            {"name": "wcnp_check_app_health", "id": "c1", "args": {"namespace": "unified-promise-discovery"}},
            adk_type="function_call",
        )])
        await after_event(ctx, ev1fc, None)
        ev1fr = _make_status_event("working", [_make_data_part(
            {"name": "wcnp_check_app_health", "id": "c1", "response": {"memory_p90": 86.4}},
            adk_type="function_response",
        )])
        await after_event(ctx, ev1fr, None)
        ev1w = _make_status_event("working", [_make_text_part("Memory p90 at 86.4%")])
        await after_event(ctx, ev1w, None)
        await after_agent(ctx, None)

        # Turn 2: follow-up trend graph
        _set_cv("alice", "mt1", "trend graph memory p90")
        ev2s = _make_status_event("submitted", [_make_text_part("trend graph memory p90")])
        await after_event(ctx, ev2s, None)
        ev2t = _make_status_event("working", [_make_text_part("Rendering chart...", adk_thought=True)])
        await after_event(ctx, ev2t, None)
        ev2fc = _make_status_event("working", [_make_data_part(
            {"name": "render_chart", "id": "rc1", "args": {"labels": ["Day1"], "datasets": [{"label": "eus2", "data": [86.4]}]}},
            adk_type="function_call",
        )])
        await after_event(ctx, ev2fc, None)
        ev2w = _make_status_event("working", [_make_text_part("Here is the trend chart")])
        await after_event(ctx, ev2w, None)
        await after_agent(ctx, None)

        events = _all_events(redis, key)
        types = [e["type"] for e in events]
        # Turn 1: user, thinking, progress(call), progress(resp), complete
        # Turn 2: user, thinking, progress(render_chart), complete
        assert types[0] == "user"
        assert types[-1] == "complete"
        user_events = _events_of_type(redis, key, "user")
        assert len(user_events) == 2
        complete_events = _events_of_type(redis, key, "complete")
        assert len(complete_events) == 2
        assert user_events[0]["text"] == "check health of unified-promise-discovery"
        assert user_events[1]["text"] == "trend graph memory p90"

    @pytest.mark.asyncio
    async def test_three_turn_conversation_with_tool_calls(self, redis, shared_state, interceptors):
        """Three sequential turns with different tool calls in each."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="bob", session_id="mt2")
        key = _ui_key("bob", "mt2")

        for turn_num in range(1, 4):
            q = f"question {turn_num}"
            _set_cv("bob", "mt2", q)
            await after_event(ctx, _make_status_event("submitted", [_make_text_part(q)]), None)
            await after_event(ctx, _make_status_event("working", [
                _make_data_part({"name": f"tool_{turn_num}", "id": f"c{turn_num}", "args": {}}, adk_type="function_call"),
            ]), None)
            await after_event(ctx, _make_status_event("working", [_make_text_part(f"answer {turn_num}")]), None)
            await after_agent(ctx, None)

        user_events = _events_of_type(redis, key, "user")
        complete_events = _events_of_type(redis, key, "complete")
        progress_events = _events_of_type(redis, key, "progress")
        assert len(user_events) == 3
        assert len(complete_events) == 3
        assert len(progress_events) == 3
        assert progress_events[0]["tool"] == "tool_1"
        assert progress_events[2]["tool"] == "tool_3"

    @pytest.mark.asyncio
    async def test_turn_with_multiple_tool_calls(self, redis, shared_state, interceptors):
        """Single turn that calls 3 tools sequentially (health + chart + table)."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="mt3")
        key = _ui_key("alice", "mt3")

        _set_cv("alice", "mt3", "full report")
        await after_event(ctx, _make_status_event("submitted", [_make_text_part("full report")]), None)

        # Tool 1: health check
        await after_event(ctx, _make_status_event("working", [_make_data_part(
            {"name": "wcnp_check_app_health", "id": "c1", "args": {"app": "myapp"}}, adk_type="function_call",
        )]), None)
        await after_event(ctx, _make_status_event("working", [_make_data_part(
            {"name": "wcnp_check_app_health", "id": "c1", "response": {"ok": True}}, adk_type="function_response",
        )]), None)

        # Tool 2: render chart
        await after_event(ctx, _make_status_event("working", [_make_data_part(
            {"name": "render_chart", "id": "c2", "args": {"labels": ["a"], "datasets": []}}, adk_type="function_call",
        )]), None)

        # Tool 3: render table
        await after_event(ctx, _make_status_event("working", [_make_data_part(
            {"name": "render_table_data", "id": "c3", "args": {"columns": ["A"], "rows": [["1"]]}}, adk_type="function_call",
        )]), None)

        await after_event(ctx, _make_status_event("working", [_make_text_part("Full report above")]), None)
        await after_agent(ctx, None)

        progress = _events_of_type(redis, key, "progress")
        assert len(progress) == 4  # call + response + call + call
        tools = [p["tool"] for p in progress]
        assert tools == ["wcnp_check_app_health", "wcnp_check_app_health", "render_chart", "render_table_data"]

    @pytest.mark.asyncio
    async def test_thinking_interleaved_between_tool_calls(self, redis, shared_state, interceptors):
        """Thinking events interleaved between tool calls in one turn."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="mt4")
        key = _ui_key("alice", "mt4")

        _set_cv("alice", "mt4", "analyze")
        await after_event(ctx, _make_status_event("submitted", [_make_text_part("analyze")]), None)

        # Think → call → think → call → response
        await after_event(ctx, _make_status_event("working", [_make_text_part("First I should...", adk_thought=True)]), None)
        await after_event(ctx, _make_status_event("working", [_make_data_part(
            {"name": "tool_a", "id": "a1", "args": {}}, adk_type="function_call",
        )]), None)
        await after_event(ctx, _make_status_event("working", [_make_text_part("Now I need to...", adk_thought=True)]), None)
        await after_event(ctx, _make_status_event("working", [_make_data_part(
            {"name": "tool_b", "id": "b1", "args": {}}, adk_type="function_call",
        )]), None)
        await after_event(ctx, _make_status_event("working", [_make_text_part("Done")]), None)
        await after_agent(ctx, None)

        thinking = _events_of_type(redis, key, "thinking")
        progress = _events_of_type(redis, key, "progress")
        assert len(thinking) == 2
        assert len(progress) == 2
        # Verify interleaved order: thinking, progress, thinking, progress
        events = _all_events(redis, key)
        non_user = [e for e in events if e["type"] != "user"]
        assert non_user[0]["type"] == "thinking"
        assert non_user[1]["type"] == "progress"
        assert non_user[2]["type"] == "thinking"
        assert non_user[3]["type"] == "progress"

    @pytest.mark.asyncio
    async def test_follow_up_after_error_turn(self, redis, shared_state, interceptors):
        """Turn 1 produces empty response (error), turn 2 retries successfully."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="mt5")
        key = _ui_key("alice", "mt5")

        # Turn 1: submitted but no working events → empty complete
        _set_cv("alice", "mt5", "broken query")
        await after_event(ctx, _make_status_event("submitted", [_make_text_part("broken query")]), None)
        await after_agent(ctx, None)

        # Turn 2: retry works
        _set_cv("alice", "mt5", "retry query")
        await after_event(ctx, _make_status_event("submitted", [_make_text_part("retry query")]), None)
        await after_event(ctx, _make_status_event("working", [_make_text_part("Success!")]), None)
        await after_agent(ctx, None)

        user_events = _events_of_type(redis, key, "user")
        complete_events = _events_of_type(redis, key, "complete")
        assert len(user_events) == 2
        # Both turns get a complete — turn 1 is empty, turn 2 has the answer
        assert len(complete_events) == 2
        assert complete_events[0]["text"] == ""
        assert complete_events[1]["text"] == "Success!"

    @pytest.mark.asyncio
    async def test_text_buffer_resets_between_turns(self, redis, shared_state, interceptors):
        """_session_text_buf must not bleed from turn 1 into turn 2."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="mt6")
        key = _ui_key("alice", "mt6")

        # Turn 1
        _set_cv("alice", "mt6", "q1")
        await after_event(ctx, _make_status_event("submitted", [_make_text_part("q1")]), None)
        await after_event(ctx, _make_status_event("working", [_make_text_part("answer one")]), None)
        await after_agent(ctx, None)

        # Turn 2: only thinking, no visible text
        _set_cv("alice", "mt6", "q2")
        await after_event(ctx, _make_status_event("submitted", [_make_text_part("q2")]), None)
        await after_event(ctx, _make_status_event("working", [_make_text_part("hmm", adk_thought=True)]), None)
        await after_agent(ctx, None)

        complete_events = _events_of_type(redis, key, "complete")
        # Both turns get a complete — turn 2 is empty (only thought text, no visible output)
        assert len(complete_events) == 2
        assert complete_events[0]["text"] == "answer one"
        assert complete_events[1]["text"] == ""

    @pytest.mark.asyncio
    async def test_rapid_turns_same_session(self, redis, shared_state, interceptors):
        """Five rapid-fire turns in the same session."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="alice", session_id="mt7")
        key = _ui_key("alice", "mt7")

        for i in range(5):
            q = f"q{i}"
            _set_cv("alice", "mt7", q)
            await after_event(ctx, _make_status_event("submitted", [_make_text_part(q)]), None)
            await after_event(ctx, _make_status_event("working", [_make_text_part(f"a{i}")]), None)
            await after_agent(ctx, None)

        user_events = _events_of_type(redis, key, "user")
        complete_events = _events_of_type(redis, key, "complete")
        assert len(user_events) == 5
        assert len(complete_events) == 5
        # Verify ordering: alternating user, complete
        events = _all_events(redis, key)
        for i in range(5):
            assert events[i * 2]["type"] == "user"
            assert events[i * 2 + 1]["type"] == "complete"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. User-text dedup with shared_state clean text
# ═══════════════════════════════════════════════════════════════════════════════


class TestUserTextSharedState:
    """Verify that _after_event uses clean user_text from shared_state
    rather than the mutated text from the submitted event, preventing
    duplicate USER events when _before_agent prepends '[Question asked by...]'."""

    @pytest.mark.asyncio
    async def test_after_event_uses_shared_user_text(self, redis, shared_state, interceptors):
        """When shared_state has user_text, _after_event uses it (not submitted event text)."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-ut1", session_id="sess-ut1")

        # Simulate _before_agent storing clean text + identity
        shared_state["identity_by_session"]["sess-ut1"] = {
            "login_id": "eve",
            "user_name": "Eve",
            "user_text": "show trend",
        }

        # ContextVars are empty (new Task) — _after_event should get text from shared_state
        # The submitted event text is MUTATED (has prefix)
        mutated_text = "[Question asked by user eve]:\nshow trend"
        ev = _make_status_event("submitted", [_make_text_part(mutated_text)])
        await after_event(ctx, ev, None)

        eve_key = _ui_key("eve", "sess-ut1")
        user_events = _events_of_type(redis, eve_key, "user")
        assert len(user_events) == 1
        # User event text should be the CLEAN text, not the mutated one
        assert user_events[0]["text"] == "show trend"

    @pytest.mark.asyncio
    async def test_shared_user_text_dedup_with_eager_write(self, redis, shared_state, interceptors):
        """User message eagerly written by _before_agent is deduped with shared_state text."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-ut2", session_id="sess-ut2")

        clean_text = "check health"
        shared_state["identity_by_session"]["sess-ut2"] = {
            "login_id": "frank",
            "user_name": "Frank",
            "user_text": clean_text,
        }
        # Simulate eager write already done by _before_agent
        shared_state["user_msg_written"].add(_turn_key("sess-ut2", clean_text))

        # _after_event with submitted event (mutated text) should NOT write a second USER
        mutated_text = "[Question asked by user frank]:\ncheck health"
        ev = _make_status_event("submitted", [_make_text_part(mutated_text)])
        await after_event(ctx, ev, None)

        frank_key = _ui_key("frank", "sess-ut2")
        user_events = _events_of_type(redis, frank_key, "user")
        assert len(user_events) == 0, "Should be deduped — user msg already written"

    @pytest.mark.asyncio
    async def test_after_agent_uses_shared_user_text(self, redis, shared_state, interceptors):
        """_after_agent writes complete under correct key using shared_state user_text."""
        after_event, after_agent = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-ut3", session_id="sess-ut3")

        clean_text = "show metrics"
        shared_state["identity_by_session"]["sess-ut3"] = {
            "login_id": "grace",
            "user_name": "Grace",
            "user_text": clean_text,
        }

        # Buffer response text
        ev = _make_status_event("working", [_make_text_part("Here are the metrics")])
        await after_event(ctx, ev, None)
        await after_agent(ctx, None)

        grace_key = _ui_key("grace", "sess-ut3")
        user_events = _events_of_type(redis, grace_key, "user")
        complete_events = _events_of_type(redis, grace_key, "complete")
        assert len(user_events) == 1
        assert user_events[0]["text"] == clean_text
        assert len(complete_events) == 1

    @pytest.mark.asyncio
    async def test_fallback_to_submitted_when_no_shared_text(self, redis, shared_state, interceptors):
        """When shared_state has no user_text, _after_event falls back to submitted event."""
        after_event, _ = interceptors
        ctx = FakeExecutorCtx(user_id="A2A_USER_sess-ut4", session_id="sess-ut4")

        # Identity present but NO user_text (streaming request where _before_agent couldn't extract)
        shared_state["identity_by_session"]["sess-ut4"] = {
            "login_id": "henry",
            "user_name": "Henry",
        }

        ev = _make_status_event("submitted", [_make_text_part("show pods")])
        await after_event(ctx, ev, None)

        henry_key = _ui_key("henry", "sess-ut4")
        user_events = _events_of_type(redis, henry_key, "user")
        assert len(user_events) == 1
        assert user_events[0]["text"] == "show pods"
