"""
Unit tests for CHART_DATA_CACHE eviction logic in session_hooks._strip_chart_data.

Covers:
  - Line 596: stale entry eviction (entries older than _CACHE_TTL_SECONDS)
  - Lines 598-599: hard-cap eviction when cache reaches _CACHE_MAX_ENTRIES
"""

import json
import sys
import time as _time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.hooks.session_hooks import (
    CHART_DATA_CACHE,
    _CACHE_MAX_ENTRIES,
    _CACHE_TTL_SECONDS,
    _strip_chart_data,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure a clean cache before and after every test."""
    CHART_DATA_CACHE.clear()
    yield
    CHART_DATA_CACHE.clear()


def _make_chart_result(title="cpu", series_count=1, data_points=10):
    """Return a result dict with a chart_data payload that _strip_chart_data will strip."""
    return {
        "chart_data": {
            "title": title,
            "series": [{"values": [1.0] * data_points}] * series_count,
        }
    }


# ── Line 596: stale entry eviction ──────────────────────────────────────────


def test_stale_entries_are_evicted():
    """Populate CHART_DATA_CACHE with entries whose _ts is older than TTL.

    When _strip_chart_data runs, it should evict those stale entries
    before inserting the new one (line 596).
    """
    now = _time.monotonic()
    stale_ts = now - _CACHE_TTL_SECONDS - 100  # well past TTL

    # Seed 3 stale entries
    for i in range(3):
        CHART_DATA_CACHE[f"stale-key-{i}"] = {"_ts": stale_ts, "chart_data": {"x": i}}

    assert len(CHART_DATA_CACHE) == 3

    result = _make_chart_result()
    _strip_chart_data(result, json.dumps(result), "fresh-key", "my_tool")

    # Stale entries should have been evicted; only the fresh one remains
    assert "stale-key-0" not in CHART_DATA_CACHE
    assert "stale-key-1" not in CHART_DATA_CACHE
    assert "stale-key-2" not in CHART_DATA_CACHE
    assert "fresh-key" in CHART_DATA_CACHE


# ── Lines 598-599: hard-cap eviction ────────────────────────────────────────


def test_hard_cap_eviction():
    """Fill CHART_DATA_CACHE to _CACHE_MAX_ENTRIES so the while-loop evicts
    the oldest entry to make room (lines 598-599).
    """
    now = _time.monotonic()

    # Fill cache to exactly _CACHE_MAX_ENTRIES with non-stale entries
    for i in range(_CACHE_MAX_ENTRIES):
        CHART_DATA_CACHE[f"cap-key-{i}"] = {"_ts": now + i, "chart_data": {"x": i}}

    assert len(CHART_DATA_CACHE) == _CACHE_MAX_ENTRIES

    result = _make_chart_result()
    _strip_chart_data(result, json.dumps(result), "overflow-key", "my_tool")

    # The oldest entry (cap-key-0, lowest _ts) should have been evicted
    assert "cap-key-0" not in CHART_DATA_CACHE
    # The new entry should be present
    assert "overflow-key" in CHART_DATA_CACHE
    # Total size should be at most _CACHE_MAX_ENTRIES
    assert len(CHART_DATA_CACHE) <= _CACHE_MAX_ENTRIES


def test_stale_eviction_plus_hard_cap():
    """Combine stale eviction AND hard-cap eviction in a single call."""
    now = _time.monotonic()
    stale_ts = now - _CACHE_TTL_SECONDS - 50

    # 2 stale entries
    CHART_DATA_CACHE["stale-a"] = {"_ts": stale_ts, "chart_data": {"x": 0}}
    CHART_DATA_CACHE["stale-b"] = {"_ts": stale_ts, "chart_data": {"x": 1}}

    # Fill remaining capacity with fresh entries so total == _CACHE_MAX_ENTRIES
    remaining = _CACHE_MAX_ENTRIES - 2
    for i in range(remaining):
        CHART_DATA_CACHE[f"fresh-{i}"] = {"_ts": now + i, "chart_data": {"x": i}}

    assert len(CHART_DATA_CACHE) == _CACHE_MAX_ENTRIES

    result = _make_chart_result()
    _strip_chart_data(result, json.dumps(result), "new-key", "my_tool")

    # Stale entries removed
    assert "stale-a" not in CHART_DATA_CACHE
    assert "stale-b" not in CHART_DATA_CACHE
    # New entry present
    assert "new-key" in CHART_DATA_CACHE
