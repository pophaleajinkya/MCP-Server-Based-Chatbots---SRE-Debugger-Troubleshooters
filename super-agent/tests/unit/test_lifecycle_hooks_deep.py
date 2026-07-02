"""
Comprehensive tests for inject_pending_observations, commit_pending_observations,
and _stream_id_lt in src/app/hooks/session_hooks.py.

Covers:
  - Redis availability / absence
  - Stream entry parsing (JSON, raw, bytes/str keys, bytes/str entry_id)
  - Synthetic event insertion positions
  - HWM staging and promotion logic
  - Error handling (non-fatal exception paths)
  - _stream_id_lt edge cases
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Fake ADK-like objects
# ---------------------------------------------------------------------------

class FakeContent:
    def __init__(self, role=None, parts=None):
        self.role = role
        self.parts = parts or []


class FakeEvent:
    def __init__(self, content=None, author=None):
        self.content = content
        self.author = author


class FakeSession:
    def __init__(self, id="sess-001", user_id="uid-001", app_name="test-app", events=None):
        self.id = id
        self.user_id = user_id
        self.app_name = app_name
        self.events = events if events is not None else []


class FakeSessionService:
    def __init__(self, redis=None):
        self._redis = redis


class FakeInvocation:
    def __init__(self, session, session_service=None):
        self.session = session
        self.session_service = session_service
        self.invocation_id = "test-inv-001"


class FakeCallbackContext:
    def __init__(self, invocation, state=None):
        self._invocation_context = invocation
        self.state = state if state is not None else {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_event(text="hello"):
    return FakeEvent(content=FakeContent(role="user", parts=[MagicMock(text=text)]))


def _make_model_event(text="response"):
    return FakeEvent(content=FakeContent(role="model", parts=[MagicMock(text=text)]))


def _make_redis(xrange_return=None, xrange_side_effect=None):
    redis = AsyncMock()
    if xrange_side_effect:
        redis.xrange.side_effect = xrange_side_effect
    else:
        redis.xrange.return_value = xrange_return or []
    return redis


def _make_ctx(redis=None, state=None, events=None, app_name="test-app",
              session_service_exists=True, has_redis_attr=True):
    session = FakeSession(events=events or [], app_name=app_name)
    if session_service_exists:
        if has_redis_attr:
            svc = FakeSessionService(redis=redis)
        else:
            svc = MagicMock(spec=[])  # no _redis attribute
        invocation = FakeInvocation(session, session_service=svc)
    else:
        invocation = FakeInvocation(session, session_service=None)
    return FakeCallbackContext(invocation, state=state or {})


# ---------------------------------------------------------------------------
# inject_pending_observations tests
# ---------------------------------------------------------------------------

class TestInjectPendingObservations:
    """Tests for inject_pending_observations."""

    @pytest.mark.asyncio
    async def test_no_session_service_returns_none(self):
        """1. session_service is None -> returns None."""
        from app.hooks.session_hooks import inject_pending_observations
        ctx = _make_ctx(session_service_exists=False)
        result = await inject_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis_attr_returns_none(self):
        """2. session_service has no _redis attribute -> returns None."""
        from app.hooks.session_hooks import inject_pending_observations
        ctx = _make_ctx(has_redis_attr=False)
        result = await inject_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_xrange_empty_clears_stale_pending(self):
        """3. xrange returns empty -> clears stale pending marker, returns None."""
        from app.hooks.session_hooks import inject_pending_observations
        redis = _make_redis(xrange_return=[])
        ctx = _make_ctx(redis=redis, state={"_lifecycle_hwm_pending": "123-0"})
        result = await inject_pending_observations(ctx)
        assert result is None
        assert ctx.state["_lifecycle_hwm_pending"] == ""

    @pytest.mark.asyncio
    async def test_xrange_empty_no_existing_pending(self):
        """3b. xrange returns empty, no existing pending -> no crash."""
        from app.hooks.session_hooks import inject_pending_observations
        redis = _make_redis(xrange_return=[])
        ctx = _make_ctx(redis=redis)
        result = await inject_pending_observations(ctx)
        assert result is None
        assert "_lifecycle_hwm_pending" not in ctx.state

    @pytest.mark.asyncio
    async def test_xrange_raises_returns_none(self):
        """4. xrange raises exception -> logs debug, returns None."""
        from app.hooks.session_hooks import inject_pending_observations
        redis = _make_redis(xrange_side_effect=ConnectionError("timeout"))
        ctx = _make_ctx(redis=redis)
        result = await inject_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_single_valid_json_entry(self):
        """5. Single valid JSON entry with 'content' field -> builds synthetic event."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "alert fired"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        user_ev = _make_user_event()
        ctx = _make_ctx(redis=redis, events=[user_ev])
        result = await inject_pending_observations(ctx)
        assert result is None
        # Synthetic event inserted before the user event
        session = ctx._invocation_context.session
        assert len(session.events) == 2
        synthetic = session.events[0]
        assert synthetic.content.role == "user"
        assert "alert fired" in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_multiple_valid_entries_joined_with_separator(self):
        """6. Multiple valid entries -> all observations joined with --- separator."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [
            ("100-0", {b"data": json.dumps({"content": "obs1"}).encode()}),
            ("200-0", {b"data": json.dumps({"content": "obs2"}).encode()}),
            ("300-0", {b"data": json.dumps({"content": "obs3"}).encode()}),
        ]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        text = synthetic.content.parts[0].text
        assert "obs1" in text
        assert "obs2" in text
        assert "obs3" in text
        assert "---" in text

    @pytest.mark.asyncio
    async def test_bytes_entry_id_decoded(self):
        """7. Entry with bytes entry_id -> decode path."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [(b"100-0", {b"data": json.dumps({"content": "data"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        assert ctx.state["_lifecycle_hwm_pending"] == "100-0"

    @pytest.mark.asyncio
    async def test_string_entry_id_direct(self):
        """8. Entry with string entry_id -> direct path."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("200-5", {b"data": json.dumps({"content": "data"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        assert ctx.state["_lifecycle_hwm_pending"] == "200-5"

    @pytest.mark.asyncio
    async def test_bytes_data_key(self):
        """9. Entry with b"data" key (bytes dict key)."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "via bytes key"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert "via bytes key" in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_string_data_key(self):
        """10. Entry with "data" key (string dict key)."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {"data": json.dumps({"content": "via str key"})})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert "via str key" in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_neither_data_key_skipped(self):
        """11. Entry with neither key -> skipped, no synthetic event."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {"other_key": "value"})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        # Only the original user event; no synthetic
        assert len(session.events) == 1
        # But HWM is still staged
        assert ctx.state["_lifecycle_hwm_pending"] == "100-0"

    @pytest.mark.asyncio
    async def test_non_json_data_raw_fallback(self):
        """12. Entry with non-JSON data -> treated as raw string (fallback)."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": b"plain text alert"})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert "plain text alert" in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_json_no_content_field_skipped(self):
        """13. Entry with JSON but no 'content' field -> empty observation (skipped)."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"source": "test"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        # No synthetic event; only original
        assert len(session.events) == 1
        # HWM still staged
        assert ctx.state["_lifecycle_hwm_pending"] == "100-0"

    @pytest.mark.asyncio
    async def test_all_entries_unparseable_stages_hwm_no_event(self):
        """14. All entries unparseable -> stages HWM but no synthetic event."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [
            ("100-0", {"no_data_key": "x"}),
            ("200-0", {"no_data_key": "y"}),
        ]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        assert len(session.events) == 1
        assert ctx.state["_lifecycle_hwm_pending"] == "200-0"

    @pytest.mark.asyncio
    async def test_insert_before_last_user_event(self):
        """15. Events list with user event at end -> inserts at that index."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        model_ev = _make_model_event()
        user_ev = _make_user_event()
        ctx = _make_ctx(redis=redis, events=[model_ev, user_ev])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        assert len(session.events) == 3
        # Synthetic should be at index 1 (before the user event which was at index 1)
        assert session.events[0] is model_ev
        assert session.events[1].content.role == "user"  # synthetic
        assert "obs" in session.events[1].content.parts[0].text
        assert session.events[2] is user_ev

    @pytest.mark.asyncio
    async def test_insert_at_end_no_user_events(self):
        """16. Events list with no user events -> inserts at end."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        model_ev = _make_model_event()
        ctx = _make_ctx(redis=redis, events=[model_ev])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        assert len(session.events) == 2
        assert session.events[0] is model_ev
        assert session.events[1].content.role == "user"  # synthetic at end

    @pytest.mark.asyncio
    async def test_insert_before_last_of_multiple_user_events(self):
        """17. Multiple user events -> inserts before LAST one."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        user1 = _make_user_event("first")
        model1 = _make_model_event()
        user2 = _make_user_event("second")
        ctx = _make_ctx(redis=redis, events=[user1, model1, user2])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        assert len(session.events) == 4
        assert session.events[0] is user1
        assert session.events[1] is model1
        assert "obs" in session.events[2].content.parts[0].text  # synthetic
        assert session.events[3] is user2

    @pytest.mark.asyncio
    async def test_hwm_staging(self):
        """18. new_hwm is stored in _lifecycle_hwm_pending."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [
            ("100-0", {b"data": json.dumps({"content": "a"}).encode()}),
            ("200-0", {b"data": json.dumps({"content": "b"}).encode()}),
        ]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        # HWM should be the last entry's ID
        assert ctx.state["_lifecycle_hwm_pending"] == "200-0"

    @pytest.mark.asyncio
    async def test_stale_pending_cleared_on_empty(self):
        """19. If no entries, clears existing _lifecycle_hwm_pending."""
        from app.hooks.session_hooks import inject_pending_observations
        redis = _make_redis(xrange_return=[])
        ctx = _make_ctx(redis=redis, state={"_lifecycle_hwm_pending": "50-0"})
        await inject_pending_observations(ctx)
        assert ctx.state["_lifecycle_hwm_pending"] == ""

    @pytest.mark.asyncio
    async def test_outer_exception_handler(self):
        """20. callback_context access fails -> logs warning, returns None."""
        from app.hooks.session_hooks import inject_pending_observations
        ctx = MagicMock()
        ctx._invocation_context = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        # Make attribute access raise
        del ctx._invocation_context
        ctx.configure_mock(**{"_invocation_context": MagicMock(side_effect=RuntimeError("boom"))})
        # Simpler approach: use an object whose attribute access raises
        class BrokenContext:
            @property
            def _invocation_context(self):
                raise RuntimeError("boom")
            state = {}
        result = await inject_pending_observations(BrokenContext())
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_events_list(self):
        """21. Session with empty events list."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[])
        await inject_pending_observations(ctx)
        session = ctx._invocation_context.session
        # Synthetic event appended at end (no user event found)
        assert len(session.events) == 1
        assert session.events[0].content.role == "user"
        assert "obs" in session.events[0].content.parts[0].text

    @pytest.mark.asyncio
    async def test_none_app_name_falls_back(self):
        """22. Session with None app_name -> falls back to APP_NAME constant."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        session = FakeSession(app_name=None, events=[_make_user_event()])
        svc = FakeSessionService(redis=redis)
        invocation = FakeInvocation(session, session_service=svc)
        ctx = FakeCallbackContext(invocation)
        with patch("app.hooks.session_hooks._key_llm_pending") as mock_key:
            mock_key.return_value = "test:stream:key"
            await inject_pending_observations(ctx)
            # Verify the fallback APP_NAME was used (not None)
            call_args = mock_key.call_args[0]
            assert call_args[0] is not None

    @pytest.mark.asyncio
    async def test_unicode_content(self):
        """23. Unicode content in observations."""
        from app.hooks.session_hooks import inject_pending_observations
        unicode_text = "Alert: CPU \u2265 95% on node-\u03b1 \U0001f525"
        entries = [("100-0", {b"data": json.dumps({"content": unicode_text}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert unicode_text in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_large_observation_content(self):
        """24. Very large observation content (50KB)."""
        from app.hooks.session_hooks import inject_pending_observations
        big_text = "x" * 50_000
        entries = [("100-0", {b"data": json.dumps({"content": big_text}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert big_text in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_exactly_50_entries_max_boundary(self):
        """25. Exactly 50 entries (max count boundary)."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [
            (f"{i}-0", {b"data": json.dumps({"content": f"obs{i}"}).encode()})
            for i in range(50)
        ]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        text = synthetic.content.parts[0].text
        assert "obs0" in text
        assert "obs49" in text
        assert ctx.state["_lifecycle_hwm_pending"] == "49-0"

    @pytest.mark.asyncio
    async def test_reads_last_lifecycle_ts_from_state(self):
        """Verify xrange is called with the HWM from state."""
        from app.hooks.session_hooks import inject_pending_observations
        redis = _make_redis(xrange_return=[])
        ctx = _make_ctx(redis=redis, state={"last_lifecycle_ts": "500-3"})
        await inject_pending_observations(ctx)
        redis.xrange.assert_awaited_once()
        call_kwargs = redis.xrange.call_args
        # min should be "(500-3"
        assert "(500-3" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_default_hwm_is_0_0(self):
        """Verify default HWM when state has no last_lifecycle_ts."""
        from app.hooks.session_hooks import inject_pending_observations
        redis = _make_redis(xrange_return=[])
        ctx = _make_ctx(redis=redis, state={})
        await inject_pending_observations(ctx)
        call_kwargs = redis.xrange.call_args
        assert "(0-0" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_synthetic_event_author_is_system(self):
        """Verify synthetic event has author='system'."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert synthetic.author == "system"

    @pytest.mark.asyncio
    async def test_invocation_id_used_in_synthetic(self):
        """Verify the invocation_id from context is used."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": json.dumps({"content": "obs"}).encode()})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert synthetic.invocation_id == "test-inv-001"

    @pytest.mark.asyncio
    async def test_bytes_raw_data_decoded(self):
        """Verify bytes raw data is decoded properly."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": b'{"content": "from bytes"}'})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert "from bytes" in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_bytearray_raw_data_decoded(self):
        """Verify bytearray raw data is decoded properly."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [("100-0", {b"data": bytearray(b'not json stuff')})]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        assert "not json stuff" in synthetic.content.parts[0].text

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid_entries(self):
        """Mix of valid JSON, invalid JSON, missing key entries."""
        from app.hooks.session_hooks import inject_pending_observations
        entries = [
            ("100-0", {b"data": json.dumps({"content": "good1"}).encode()}),
            ("200-0", {"no_data": "skip"}),
            ("300-0", {b"data": b"raw text"}),
            ("400-0", {b"data": json.dumps({"source": "no content"}).encode()}),
            ("500-0", {b"data": json.dumps({"content": "good2"}).encode()}),
        ]
        redis = _make_redis(xrange_return=entries)
        ctx = _make_ctx(redis=redis, events=[_make_user_event()])
        await inject_pending_observations(ctx)
        synthetic = ctx._invocation_context.session.events[0]
        text = synthetic.content.parts[0].text
        assert "good1" in text
        assert "raw text" in text
        assert "good2" in text
        assert ctx.state["_lifecycle_hwm_pending"] == "500-0"


# ---------------------------------------------------------------------------
# commit_pending_observations tests
# ---------------------------------------------------------------------------

class TestCommitPendingObservations:
    """Tests for commit_pending_observations."""

    @pytest.mark.asyncio
    async def test_no_pending_key_returns_none(self):
        """1. No pending key in state -> returns None immediately."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(FakeInvocation(FakeSession()), state={})
        result = await commit_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_pending_returns_none(self):
        """2. Empty string pending -> returns None."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(
            FakeInvocation(FakeSession()),
            state={"_lifecycle_hwm_pending": ""},
        )
        result = await commit_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_pending_newer_promotes_hwm(self):
        """3. Pending newer than current -> promotes HWM, clears pending."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(
            FakeInvocation(FakeSession()),
            state={
                "_lifecycle_hwm_pending": "200-0",
                "last_lifecycle_ts": "100-0",
            },
        )
        result = await commit_pending_observations(ctx)
        assert result is None
        assert ctx.state["last_lifecycle_ts"] == "200-0"
        assert ctx.state["_lifecycle_hwm_pending"] == ""

    @pytest.mark.asyncio
    async def test_pending_older_does_not_promote(self):
        """4. Pending older than current -> does NOT promote, still clears pending."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(
            FakeInvocation(FakeSession()),
            state={
                "_lifecycle_hwm_pending": "50-0",
                "last_lifecycle_ts": "100-0",
            },
        )
        await commit_pending_observations(ctx)
        assert ctx.state["last_lifecycle_ts"] == "100-0"  # unchanged
        assert ctx.state["_lifecycle_hwm_pending"] == ""

    @pytest.mark.asyncio
    async def test_pending_equal_does_not_promote(self):
        """5. Pending equal to current -> does NOT promote (not strictly older)."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(
            FakeInvocation(FakeSession()),
            state={
                "_lifecycle_hwm_pending": "100-0",
                "last_lifecycle_ts": "100-0",
            },
        )
        await commit_pending_observations(ctx)
        assert ctx.state["last_lifecycle_ts"] == "100-0"
        assert ctx.state["_lifecycle_hwm_pending"] == ""

    @pytest.mark.asyncio
    async def test_initial_hwm_promotes(self):
        """6. Current is '0-0' (initial) and pending is '1-0' -> promotes."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(
            FakeInvocation(FakeSession()),
            state={"_lifecycle_hwm_pending": "1-0"},
        )
        await commit_pending_observations(ctx)
        assert ctx.state["last_lifecycle_ts"] == "1-0"
        assert ctx.state["_lifecycle_hwm_pending"] == ""

    @pytest.mark.asyncio
    async def test_state_access_raises_returns_none(self):
        """7. State access raises exception -> logs warning, returns None."""
        from app.hooks.session_hooks import commit_pending_observations

        class BrokenState:
            def get(self, key, default=None):
                raise RuntimeError("state broken")

        ctx = FakeCallbackContext(FakeInvocation(FakeSession()))
        ctx.state = BrokenState()
        result = await commit_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_pending_id_no_promotion(self):
        """8. _stream_id_lt with malformed IDs -> returns False (no promotion)."""
        from app.hooks.session_hooks import commit_pending_observations
        ctx = FakeCallbackContext(
            FakeInvocation(FakeSession()),
            state={
                "_lifecycle_hwm_pending": "not-a-valid-id",
                "last_lifecycle_ts": "100-0",
            },
        )
        await commit_pending_observations(ctx)
        assert ctx.state["last_lifecycle_ts"] == "100-0"  # unchanged
        assert ctx.state["_lifecycle_hwm_pending"] == ""


# ---------------------------------------------------------------------------
# _stream_id_lt tests
# ---------------------------------------------------------------------------

class TestStreamIdLt:
    """Tests for _stream_id_lt edge cases."""

    def test_normal_comparison_less(self):
        """1. '100-0' < '200-0' -> True."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("100-0", "200-0") is True

    def test_same_millis_different_seq(self):
        """2. '100-0' < '100-1' -> True."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("100-0", "100-1") is True

    def test_equal_ids_false(self):
        """3. Equal IDs -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("100-0", "100-0") is False

    def test_reverse_order_false(self):
        """4. Reverse order -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("200-0", "100-0") is False

    def test_malformed_no_dash(self):
        """5. Malformed ID (no dash) -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("100", "200-0") is False

    def test_malformed_non_numeric(self):
        """6. Malformed ID (non-numeric) -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("abc-0", "200-0") is False

    def test_empty_string(self):
        """7. Empty string -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("", "200-0") is False

    def test_both_zero(self):
        """8. '0-0' vs '0-0' -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("0-0", "0-0") is False

    def test_very_large_numbers(self):
        """9. Very large numbers: '9999999999999-99' < '9999999999999-100' -> True."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("9999999999999-99", "9999999999999-100") is True

    def test_both_malformed(self):
        """Both malformed -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("bad", "worse") is False

    def test_second_arg_malformed(self):
        """Second arg malformed -> False."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("100-0", "nope") is False

    def test_zero_vs_one(self):
        """'0-0' < '1-0' -> True."""
        from app.hooks.session_hooks import _stream_id_lt
        assert _stream_id_lt("0-0", "1-0") is True
