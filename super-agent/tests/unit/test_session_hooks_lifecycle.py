"""Unit tests for session_hooks lifecycle injection, chart/table stripping, and stream ID comparison."""

import json
import sys
import time as _time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub ADK if needed
def _ensure_stub(dotted_name: str):
    parts = dotted_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
            if depth > 1:
                parent_name = ".".join(parts[:depth - 1])
                setattr(sys.modules[parent_name], parts[depth - 1], mod)

try:
    import google.adk
except ImportError:
    for _stub in (
        "google", "google.adk", "google.adk.agents",
        "google.adk.agents.callback_context",
        "google.genai", "google.genai.types",
    ):
        _ensure_stub(_stub)
    sys.modules["google.adk.agents.callback_context"].CallbackContext = MagicMock
    sys.modules["google.genai.types"].Content = MagicMock

import app.hooks.session_hooks as session_hooks


# ── Tests: _stream_id_lt ─────────────────────────────────────────────────────

class TestStreamIdLt:
    def test_a_is_older(self):
        assert session_hooks._stream_id_lt("100-0", "200-0") is True

    def test_a_is_newer(self):
        assert session_hooks._stream_id_lt("300-0", "200-0") is False

    def test_equal_ids(self):
        assert session_hooks._stream_id_lt("100-0", "100-0") is False

    def test_same_millis_different_seq(self):
        assert session_hooks._stream_id_lt("100-0", "100-1") is True

    def test_malformed_id_returns_false(self):
        assert session_hooks._stream_id_lt("bad", "100-0") is False

    def test_both_malformed_returns_false(self):
        assert session_hooks._stream_id_lt("x", "y") is False

    def test_empty_strings_returns_false(self):
        assert session_hooks._stream_id_lt("", "") is False


# ── Tests: inject_pending_observations ───────────────────────────────────────

def _make_lifecycle_ctx(
    entries=None,
    redis=None,
    session_id="sid-1",
    user_id="uid-1",
    hwm="0-0",
    xrange_error=None,
):
    """Build a mock CallbackContext for inject_pending_observations."""
    ctx = MagicMock()
    ctx.state = {session_hooks._LIFECYCLE_HWM_STATE_KEY: hwm}

    invocation = MagicMock()
    invocation.session.id = session_id
    invocation.session.user_id = user_id
    invocation.session.app_name = "test-app"
    invocation.session.events = []
    invocation.invocation_id = "inv-1"

    if redis is None:
        redis = AsyncMock()
        if xrange_error:
            redis.xrange = AsyncMock(side_effect=xrange_error)
        else:
            redis.xrange = AsyncMock(return_value=entries or [])

    invocation.session_service = MagicMock()
    invocation.session_service._redis = redis

    ctx._invocation_context = invocation
    return ctx


class TestInjectPendingObservations:
    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self):
        ctx = MagicMock()
        ctx._invocation_context.session.id = "sid"
        ctx._invocation_context.session.user_id = "uid"
        ctx._invocation_context.session.app_name = "app"
        ctx._invocation_context.session_service = None
        ctx.state = {}

        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_entries_clears_pending_marker(self):
        ctx = _make_lifecycle_ctx(entries=[])
        ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] = "stale"

        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == ""

    @pytest.mark.asyncio
    async def test_xrange_failure_returns_none(self):
        ctx = _make_lifecycle_ctx(xrange_error=ConnectionError("redis down"))
        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_entries_with_valid_content_are_injected(self):
        entries = [
            ("100-0", {b"data": json.dumps({"content": "Alert: CPU spike"}).encode()}),
            ("200-0", {"data": json.dumps({"content": "Update: resolved"})}),
        ]
        ctx = _make_lifecycle_ctx(entries=entries)
        # Add a current user event for the insert-at logic
        user_event = MagicMock()
        user_event.content = MagicMock()
        user_event.content.role = "user"
        ctx._invocation_context.session.events = [user_event]

        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None
        # HWM should be staged
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == "200-0"
        # Synthetic event should be inserted before the user event
        assert len(ctx._invocation_context.session.events) == 2

    @pytest.mark.asyncio
    async def test_entries_with_no_parseable_content_stages_hwm(self):
        entries = [
            ("150-0", {b"data": b"not-json-content"}),
        ]
        ctx = _make_lifecycle_ctx(entries=entries)

        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None
        # raw content treated as observation string
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == "150-0"

    @pytest.mark.asyncio
    async def test_entries_with_no_data_field_stages_hwm(self):
        entries = [
            ("150-0", {"other_field": "value"}),
        ]
        ctx = _make_lifecycle_ctx(entries=entries)

        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None
        # No observations, but HWM should still be staged
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == "150-0"

    @pytest.mark.asyncio
    async def test_outer_exception_is_swallowed(self):
        """A totally broken context must not raise."""
        ctx = MagicMock(spec=[])  # no attributes
        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_bytes_entry_id_decoded(self):
        entries = [
            (b"300-0", {b"data": json.dumps({"content": "test"}).encode()}),
        ]
        ctx = _make_lifecycle_ctx(entries=entries)
        ctx._invocation_context.session.events = []

        result = await session_hooks.inject_pending_observations(ctx)
        assert result is None
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == "300-0"


# ── Tests: commit_pending_observations ───────────────────────────────────────

class TestCommitPendingObservations:
    @pytest.mark.asyncio
    async def test_no_pending_returns_none(self):
        ctx = MagicMock()
        ctx.state = {}
        result = await session_hooks.commit_pending_observations(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_promotes_hwm_forward(self):
        ctx = MagicMock()
        ctx.state = {
            session_hooks._LIFECYCLE_HWM_PENDING_KEY: "200-0",
            session_hooks._LIFECYCLE_HWM_STATE_KEY: "100-0",
        }
        result = await session_hooks.commit_pending_observations(ctx)
        assert result is None
        assert ctx.state[session_hooks._LIFECYCLE_HWM_STATE_KEY] == "200-0"
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == ""

    @pytest.mark.asyncio
    async def test_does_not_regress_hwm(self):
        ctx = MagicMock()
        ctx.state = {
            session_hooks._LIFECYCLE_HWM_PENDING_KEY: "50-0",
            session_hooks._LIFECYCLE_HWM_STATE_KEY: "100-0",
        }
        result = await session_hooks.commit_pending_observations(ctx)
        assert result is None
        # HWM should NOT regress
        assert ctx.state[session_hooks._LIFECYCLE_HWM_STATE_KEY] == "100-0"
        # Pending key should still be cleared
        assert ctx.state[session_hooks._LIFECYCLE_HWM_PENDING_KEY] == ""

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        ctx = MagicMock()
        ctx.state = MagicMock()
        ctx.state.get = MagicMock(side_effect=RuntimeError("boom"))
        result = await session_hooks.commit_pending_observations(ctx)
        assert result is None


# ── Tests: _strip_large_table_rows ───────────────────────────────────────────

class TestStripLargeTableRows:
    def test_no_table_data_returns_unchanged(self):
        result = {"answer": "ok"}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_large_table_rows(result, text, "key1", "tool1")
        assert stripped is False
        assert out_r is result

    def test_small_table_not_stripped(self):
        result = {"table_data": {"rows": [{"a": 1}], "columns": ["a"]}}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_large_table_rows(result, text, "key1", "tool1")
        assert stripped is False

    def test_no_cache_key_skips_stripping(self):
        rows = [{"a": i} for i in range(200)]
        result = {"table_data": {"rows": rows, "columns": ["a"]}}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_large_table_rows(result, text, None, "tool1")
        assert stripped is False

    def test_large_table_stripped_and_cached(self):
        rows = [{"a": i} for i in range(200)]
        result = {"table_data": {"rows": rows, "columns": ["a"]}}
        text = json.dumps(result)
        cache_key = "test-cache-key"

        # Clear cache before test
        session_hooks.TABLE_ROW_CACHE.clear()

        out_r, out_t, stripped = session_hooks._strip_large_table_rows(result, text, cache_key, "tool1")
        assert stripped is True
        assert out_r["table_data"]["rows"] == []
        assert out_r["table_data"]["_rows_stripped"] is True
        assert cache_key in session_hooks.TABLE_ROW_CACHE

        # Cleanup
        session_hooks.TABLE_ROW_CACHE.pop(cache_key, None)


# ── Tests: _strip_chart_data ─────────────────────────────────────────────────

class TestStripChartData:
    def test_no_chart_data_returns_unchanged(self):
        result = {"answer": "ok"}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, "key1", "tool1")
        assert stripped is False

    def test_already_rendered_chart_skipped(self):
        result = {"chart_data": {"_chart_rendered": True}}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, "key1", "tool1")
        assert stripped is False

    def test_no_cache_key_skips(self):
        result = {"chart_data": {"labels": [1, 2], "datasets": [{"data": [3, 4]}]}}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, None, "tool1")
        assert stripped is False

    def test_chart_data_stripped_and_cached(self):
        result = {
            "chart_data": {
                "title": "CPU Usage",
                "chart_type": "line",
                "labels": [1, 2, 3],
                "datasets": [{"data": [10, 20, 30]}, {"data": [5, 15, 25]}],
            }
        }
        text = json.dumps(result)
        cache_key = "chart-test-key"

        session_hooks.CHART_DATA_CACHE.clear()

        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, cache_key, "tool1")
        assert stripped is True
        assert out_r["chart_data"]["_chart_rendered"] is True
        assert out_r["chart_data"]["series_count"] == 2
        assert out_r["chart_data"]["data_points"] == 3
        assert cache_key in session_hooks.CHART_DATA_CACHE

        session_hooks.CHART_DATA_CACHE.pop(cache_key, None)

    def test_multi_chart_data_stripped(self):
        result = {
            "multi_chart_data": {
                "title": "Multi Metrics",
                "charts": [
                    {"metric": "cpu", "labels": [1, 2], "data": [10, 20]},
                    {"metric": "mem", "labels": [1, 2], "data": [30, 40]},
                ],
            }
        }
        text = json.dumps(result)
        cache_key = "multi-chart-key"

        session_hooks.CHART_DATA_CACHE.clear()

        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, cache_key, "tool1")
        assert stripped is True
        assert out_r["multi_chart_data"]["_chart_rendered"] is True
        assert out_r["multi_chart_data"]["chart_count"] == 2
        assert out_r["multi_chart_data"]["metrics"] == ["cpu", "mem"]

        session_hooks.CHART_DATA_CACHE.pop(cache_key, None)

    def test_chart_with_empty_labels_and_series(self):
        """Chart with no labels/series — nothing actually stripped."""
        result = {"chart_data": {"title": "Empty", "labels": [], "datasets": []}}
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, "key", "tool1")
        assert stripped is False

    def test_chart_cache_eviction_stale(self, monkeypatch):
        """Stale entries are evicted before inserting new ones."""
        session_hooks.CHART_DATA_CACHE.clear()
        # Insert a stale entry (old timestamp)
        session_hooks.CHART_DATA_CACHE["stale-key"] = {"_ts": 0, "chart_data": {}}

        result = {
            "chart_data": {
                "title": "New",
                "labels": [1],
                "datasets": [{"data": [1]}],
            }
        }
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, "new-key", "tool1")
        assert stripped is True
        # Stale entry should have been evicted
        assert "stale-key" not in session_hooks.CHART_DATA_CACHE
        assert "new-key" in session_hooks.CHART_DATA_CACHE

        session_hooks.CHART_DATA_CACHE.clear()

    def test_chart_cache_max_entries_eviction(self, monkeypatch):
        """When cache is full, oldest entry is evicted."""
        session_hooks.CHART_DATA_CACHE.clear()
        monkeypatch.setattr(session_hooks, "_CACHE_MAX_ENTRIES", 2)

        # Fill cache to max
        now = _time.monotonic()
        session_hooks.CHART_DATA_CACHE["old-1"] = {"_ts": now - 100, "chart_data": {}}
        session_hooks.CHART_DATA_CACHE["old-2"] = {"_ts": now - 50, "chart_data": {}}

        result = {
            "chart_data": {
                "title": "New",
                "labels": [1],
                "datasets": [{"data": [1]}],
            }
        }
        text = json.dumps(result)
        out_r, out_t, stripped = session_hooks._strip_chart_data(result, text, "new-key", "tool1")
        assert stripped is True
        assert "new-key" in session_hooks.CHART_DATA_CACHE
        # At least one old entry should have been evicted
        assert len(session_hooks.CHART_DATA_CACHE) <= 2

        session_hooks.CHART_DATA_CACHE.clear()
