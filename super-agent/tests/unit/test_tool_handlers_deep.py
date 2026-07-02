"""
Comprehensive tests for on_tool_error_handler, after_tool_handler,
_classify_error, _save_args_to_state, _strip_large_table_rows, and
_strip_chart_data in src/app/hooks/session_hooks.py.
"""

import asyncio
import json
import sys
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helper mocks
# ---------------------------------------------------------------------------

class FakeTool:
    def __init__(self, name="test_tool"):
        self.name = name


class FakeToolContext:
    def __init__(self, state=None, call_id="call_123"):
        self.state = state if state is not None else {}
        self.function_call_id = call_id
        self._invocation_context = type(
            "obj", (object,),
            {"session": type("s", (object,), {"id": "sess_1"})()},
        )()


def _make_tool_response(result_dict: dict) -> dict:
    """Build a well-formed ADK tool response dict."""
    return {"content": [{"text": json.dumps(result_dict)}]}


# ---------------------------------------------------------------------------
# Imports under test (done AFTER sys.path manipulation)
# ---------------------------------------------------------------------------
from app.hooks.session_hooks import (  # noqa: E402
    TABLE_ROW_CACHE,
    CHART_DATA_CACHE,
    _classify_error,
    _ERROR_LABELS,
    _ERROR_MSG_MAX_LEN,
    _save_args_to_state,
    _STATE_SAVE_SKIP_TOOLS,
    _SUMMARY_EXCLUDE,
    _strip_chart_data,
    _strip_large_table_rows,
    _TABLE_ROW_STRIP_THRESHOLD,
    _CACHE_MAX_ENTRIES,
    after_tool_handler,
    on_tool_error_handler,
    table_row_cache_key,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_caches():
    """Ensure caches are empty before and after each test."""
    TABLE_ROW_CACHE.clear()
    CHART_DATA_CACHE.clear()
    yield
    TABLE_ROW_CACHE.clear()
    CHART_DATA_CACHE.clear()


# ===========================================================================
# on_tool_error_handler tests (1-25)
# ===========================================================================

class TestOnToolErrorHandler:
    """Tests for on_tool_error_handler."""

    # -- tool.name edge cases -----------------------------------------------

    def test_01_tool_name_none_falls_back(self):
        tool = FakeTool(name=None)
        result = on_tool_error_handler(tool, {}, FakeToolContext(), RuntimeError("boom"))
        assert result["tool_name"] == "unknown_tool"

    def test_02_tool_name_empty_string_falls_back(self):
        tool = FakeTool(name="")
        result = on_tool_error_handler(tool, {}, FakeToolContext(), RuntimeError("boom"))
        assert result["tool_name"] == "unknown_tool"

    def test_03_tool_no_name_attribute_falls_back(self):
        tool = object()  # no .name attr
        result = on_tool_error_handler(tool, {}, FakeToolContext(), RuntimeError("boom"))
        assert result["tool_name"] == "unknown_tool"

    # -- args normalisation -------------------------------------------------

    def test_04_args_none_normalised(self):
        result = on_tool_error_handler(FakeTool(), None, FakeToolContext(), RuntimeError("x"))
        assert result["status"] == "error"  # handler did not crash

    def test_05_args_not_dict_normalised(self):
        result = on_tool_error_handler(FakeTool(), "bad_args", FakeToolContext(), RuntimeError("x"))
        assert result["status"] == "error"

    # -- error classification -----------------------------------------------

    def test_06_connection_error(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), ConnectionError("refused"))
        assert result["error_type"] == "connection_error"

    def test_07_timeout_error(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), TimeoutError("timed out"))
        assert result["error_type"] == "timeout"

    def test_08_os_error(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), OSError("net err"))
        assert result["error_type"] == "network_error"

    def test_09_connection_refused_subclass(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), ConnectionRefusedError("no"))
        assert result["error_type"] == "connection_error"

    def test_10_connection_reset_subclass(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), ConnectionResetError("rst"))
        assert result["error_type"] == "connection_error"

    def test_11_asyncio_timeout_error(self):
        # asyncio.TimeoutError is a subclass of TimeoutError in Python 3.11+
        err = asyncio.TimeoutError()
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), err)
        assert result["error_type"] == "timeout"

    def test_12_value_error_class_name(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), ValueError("bad"))
        assert result["error_type"] == "ValueError"

    def test_13_runtime_error_class_name(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError("rt"))
        assert result["error_type"] == "RuntimeError"

    def test_14_custom_exception_class_name(self):
        class MySpecialError(Exception):
            pass
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), MySpecialError("oops"))
        assert result["error_type"] == "MySpecialError"

    # -- error message handling ---------------------------------------------

    def test_15_empty_error_message_uses_class_name(self):
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError(""))
        assert "RuntimeError" in result["message"]

    def test_16_error_message_exactly_500_no_truncation(self):
        msg = "a" * 500
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError(msg))
        # The full 500-char message should appear without the ellipsis
        assert msg in result["message"]
        assert "\u2026" not in result["message"]

    def test_17_error_message_501_truncated(self):
        msg = "b" * 501
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError(msg))
        assert "\u2026" in result["message"]
        assert "b" * 500 in result["message"]

    def test_18_error_message_10000_truncated(self):
        msg = "c" * 10000
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError(msg))
        assert "\u2026" in result["message"]
        assert len(result["message"]) < 10000

    def test_19_unicode_in_error_message(self):
        msg = "Error: \u2603 snowman \u00e9\u00e8\u00ea"
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError(msg))
        assert "\u2603" in result["message"]

    def test_20_newlines_in_error_message(self):
        msg = "line1\nline2\nline3"
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError(msg))
        assert "line1" in result["message"]
        assert "line2" in result["message"]

    # -- FALLBACK path (inner handler crashes) ------------------------------

    def test_21_fallback_tool_name_raises(self):
        """When getattr succeeds but something else in the try block fails,
        the outer except catches it and returns the minimal fallback dict."""
        class BadTool:
            name = "ok_tool"

        tool = BadTool()
        # Force _classify_error AND str(error) to raise so the try body crashes
        bad_err = RuntimeError("x")
        with patch("app.hooks.session_hooks._classify_error", side_effect=TypeError("inner boom")):
            result = on_tool_error_handler(tool, {}, FakeToolContext(), bad_err)
        assert result["status"] == "error"
        assert result["error_type"] == "handler_internal_error"
        assert result["tool_name"] == "unknown"

    def test_22_fallback_classify_error_raises(self):
        with patch("app.hooks.session_hooks._classify_error", side_effect=Exception("boom")):
            result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), RuntimeError("x"))
        assert result["error_type"] == "handler_internal_error"

    def test_23_fallback_str_error_raises(self):
        class BadError(Exception):
            def __str__(self):
                raise RuntimeError("cannot stringify")
        result = on_tool_error_handler(FakeTool(), {}, FakeToolContext(), BadError())
        assert result["status"] == "error"
        assert result["error_type"] == "handler_internal_error"

    # -- return structure ---------------------------------------------------

    def test_24_return_dict_has_correct_keys(self):
        result = on_tool_error_handler(FakeTool("my_tool"), {}, FakeToolContext(), RuntimeError("oops"))
        assert set(result.keys()) == {"status", "error_type", "tool_name", "message"}

    def test_25_return_message_contains_tool_and_type(self):
        result = on_tool_error_handler(FakeTool("my_tool"), {}, FakeToolContext(), TimeoutError("slow"))
        assert "my_tool" in result["message"]
        assert "timeout" in result["message"]


# ===========================================================================
# _classify_error tests (26-29)
# ===========================================================================

class TestClassifyError:
    """Tests for _classify_error."""

    def test_26_each_error_label_individually(self):
        for exc_type, label in _ERROR_LABELS.items():
            assert _classify_error(exc_type("test")) == label

    def test_27_subclass_catches_via_isinstance(self):
        # ConnectionRefusedError is a subclass of ConnectionError
        assert _classify_error(ConnectionRefusedError("x")) == "connection_error"
        # ConnectionResetError is also a subclass of ConnectionError
        assert _classify_error(ConnectionResetError("x")) == "connection_error"

    def test_28_unmapped_type_returns_class_name(self):
        assert _classify_error(KeyError("k")) == "KeyError"
        assert _classify_error(ZeroDivisionError("z")) == "ZeroDivisionError"

    def test_29_exception_with_no_args(self):
        assert _classify_error(Exception()) == "Exception"


# ===========================================================================
# after_tool_handler tests (30-50)
# ===========================================================================

class TestAfterToolHandler:
    """Tests for after_tool_handler."""

    # -- tool_response structure edge cases ---------------------------------

    def test_30_tool_response_not_dict(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), "not_a_dict") is None

    def test_31_no_content_key(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), {"other": 1}) is None

    def test_32_content_not_list(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), {"content": "str"}) is None

    def test_33_content_empty_list(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), {"content": []}) is None

    def test_34_content_first_not_dict(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), {"content": [42]}) is None

    def test_35_content_first_no_text(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), {"content": [{"type": "image"}]}) is None

    def test_36_text_empty_string(self):
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), {"content": [{"text": ""}]}) is None

    def test_37_text_not_valid_json(self):
        resp = {"content": [{"text": "not json at all {{{"}]}
        assert after_tool_handler(FakeTool(), {}, FakeToolContext(), resp) is None

    def test_38_json_parses_to_non_dict(self):
        for val in ([1, 2], '"hello"', "42"):
            resp = {"content": [{"text": val if isinstance(val, str) else json.dumps(val)}]}
            assert after_tool_handler(FakeTool(), {}, FakeToolContext(), resp) is None

    # -- _save_args_to_state called via after_tool_handler -------------------

    def test_39_save_args_to_state_raises_caught(self):
        with patch("app.hooks.session_hooks._save_args_to_state", side_effect=RuntimeError("boom")):
            resp = _make_tool_response({"status": "ok"})
            # Should not raise — the exception is caught
            result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
            assert result is None  # nothing stripped

    def test_40_args_none_passed_as_empty_dict(self):
        ctx = FakeToolContext()
        resp = _make_tool_response({"status": "ok"})
        # Should not crash even though args is None
        result = after_tool_handler(FakeTool(), None, ctx, resp)
        assert result is None

    # -- table stripping via after_tool_handler -----------------------------

    def test_41_table_data_below_threshold_no_strip(self):
        data = {"table_data": {"rows": list(range(_TABLE_ROW_STRIP_THRESHOLD)), "columns": ["a"]}}
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is None

    def test_42_table_data_above_threshold_strips(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 10)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is not None
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["table_data"]["rows"] == []
        assert parsed["table_data"]["_rows_stripped"] is True

    def test_43_chart_data_stripped(self):
        data = {
            "chart_data": {
                "title": "Latency",
                "labels": ["t1", "t2", "t3"],
                "datasets": [{"label": "p99", "data": [1.0, 2.0, 3.0]}],
            }
        }
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is not None
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["chart_data"]["_chart_rendered"] is True

    def test_44_multi_chart_data_stripped(self):
        data = {
            "multi_chart_data": {
                "title": "Overview",
                "charts": [
                    {"metric": "cpu", "labels": ["t1"], "datasets": [{"data": [1]}]},
                    {"metric": "mem", "labels": ["t1"], "datasets": [{"data": [2]}]},
                ],
            }
        }
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is not None
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["multi_chart_data"]["_chart_rendered"] is True
        assert parsed["multi_chart_data"]["chart_count"] == 2

    def test_45_both_table_and_chart_stripped(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 5)]
        data = {
            "table_data": {"rows": rows, "columns": ["a"]},
            "chart_data": {
                "title": "T",
                "labels": ["x"],
                "datasets": [{"label": "y", "data": [1]}],
            },
        }
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is not None
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["table_data"]["_rows_stripped"] is True
        assert parsed["chart_data"]["_chart_rendered"] is True

    def test_46_cache_key_with_call_id(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 1)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        resp = _make_tool_response(data)
        ctx = FakeToolContext(call_id="call_abc")
        after_tool_handler(FakeTool(), {}, ctx, resp)
        expected_key = table_row_cache_key("sess_1", "call_abc")
        assert expected_key in TABLE_ROW_CACHE

    def test_47_no_call_id_no_stripping(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 1)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        resp = _make_tool_response(data)
        ctx = FakeToolContext(call_id=None)
        ctx.function_call_id = None
        result = after_tool_handler(FakeTool(), {}, ctx, resp)
        assert result is None  # no cache_key → no stripping

    def test_48_session_id_extraction_failure_fallback(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 1)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        resp = _make_tool_response(data)
        ctx = FakeToolContext(call_id="call_xyz")
        # Break session access
        ctx._invocation_context = type("obj", (object,), {"session": None})()
        result = after_tool_handler(FakeTool(), {}, ctx, resp)
        # Fallback: cache_key = call_id alone
        assert result is not None
        assert "call_xyz" in TABLE_ROW_CACHE

    def test_49_double_strip_table_protection(self):
        data = {
            "table_data": {"rows": [], "_rows_stripped": True, "columns": ["a"]},
        }
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is None  # rows already stripped, nothing to do

    def test_50_double_strip_chart_protection(self):
        data = {
            "chart_data": {"_chart_rendered": True, "title": "T", "series_count": 1},
        }
        resp = _make_tool_response(data)
        result = after_tool_handler(FakeTool(), {}, FakeToolContext(), resp)
        assert result is None  # already rendered


# ===========================================================================
# _save_args_to_state tests (51-56)
# ===========================================================================

class TestSaveArgsToState:
    """Tests for _save_args_to_state."""

    def test_51_skip_tool_in_skip_list(self):
        ctx = FakeToolContext()
        _save_args_to_state({"app": "myapp"}, ctx, "get_mcp_prompt")
        assert "app" not in ctx.state

    def test_52_scalar_args_saved(self):
        ctx = FakeToolContext()
        _save_args_to_state(
            {"app": "myapp", "port": 8080, "ratio": 0.5, "active": True},
            ctx, "check_health",
        )
        assert ctx.state["app"] == "myapp"
        assert ctx.state["port"] == 8080
        assert ctx.state["ratio"] == 0.5
        assert ctx.state["active"] is True

    def test_53_non_scalar_args_skipped(self):
        ctx = FakeToolContext()
        _save_args_to_state(
            {"items": [1, 2], "meta": {"k": "v"}, "nothing": None, "name": "ok"},
            ctx, "tool_x",
        )
        assert "items" not in ctx.state
        assert "meta" not in ctx.state
        assert "nothing" not in ctx.state
        assert ctx.state["name"] == "ok"

    def test_54_empty_string_value_skipped(self):
        ctx = FakeToolContext()
        _save_args_to_state({"app": "", "ns": "prod"}, ctx, "tool_y")
        assert "app" not in ctx.state
        assert ctx.state["ns"] == "prod"

    def test_55_summary_exclude_keys(self):
        ctx = FakeToolContext()
        exclude_key = next(iter(_SUMMARY_EXCLUDE))  # pick any excluded key
        _save_args_to_state({exclude_key: 12345, "app": "myapp"}, ctx, "tool_z")
        # The key IS saved to state ...
        assert ctx.state[exclude_key] == 12345
        # ... but NOT in the active_context summary
        summary = ctx.state.get("active_context", "")
        assert exclude_key not in summary
        assert "app=myapp" in summary

    def test_56_active_context_format(self):
        ctx = FakeToolContext()
        _save_args_to_state({"app": "myapp", "ns": "prod"}, ctx, "check_health")
        ac = ctx.state["active_context"]
        assert ac.startswith("Last tool: check_health | ")
        assert "app=myapp" in ac
        assert "ns=prod" in ac


# ===========================================================================
# _strip_large_table_rows tests (57-59)
# ===========================================================================

class TestStripLargeTableRows:
    """Tests for _strip_large_table_rows."""

    def test_57_rows_at_threshold_no_strip(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        text = json.dumps(data)
        result, out_text, stripped = _strip_large_table_rows(data, text, "key_57", "tool")
        assert stripped is False

    def test_58_rows_above_threshold_strips_and_caches(self):
        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 1)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        text = json.dumps(data)
        result, out_text, stripped = _strip_large_table_rows(data, text, "key_58", "tool")
        assert stripped is True
        assert result["table_data"]["rows"] == []
        assert result["table_data"]["_rows_stripped"] is True
        assert "key_58" in TABLE_ROW_CACHE

    def test_59_cache_at_max_evicts_oldest(self):
        # Fill cache to max
        for i in range(_CACHE_MAX_ENTRIES):
            TABLE_ROW_CACHE[f"fill_{i}"] = {"table_data": {}, "_ts": _time.monotonic() - 1000 + i}
        assert len(TABLE_ROW_CACHE) == _CACHE_MAX_ENTRIES

        rows = [{"a": i} for i in range(_TABLE_ROW_STRIP_THRESHOLD + 1)]
        data = {"table_data": {"rows": rows, "columns": ["a"]}}
        text = json.dumps(data)
        _strip_large_table_rows(data, text, "new_key", "tool")
        # Should have evicted at least one to make room
        assert "new_key" in TABLE_ROW_CACHE
        assert len(TABLE_ROW_CACHE) <= _CACHE_MAX_ENTRIES


# ===========================================================================
# _strip_chart_data tests (60-63)
# ===========================================================================

class TestStripChartData:
    """Tests for _strip_chart_data."""

    def test_60_chart_with_labels_and_datasets(self):
        data = {
            "chart_data": {
                "title": "CPU",
                "chart_type": "line",
                "labels": ["t1", "t2"],
                "datasets": [{"label": "cpu", "data": [10, 20]}],
            }
        }
        text = json.dumps(data)
        result, out_text, stripped = _strip_chart_data(data, text, "key_60", "tool")
        assert stripped is True
        cd = result["chart_data"]
        assert cd["_chart_rendered"] is True
        assert cd["series_count"] == 1
        assert cd["data_points"] == 2

    def test_61_multi_chart_strips_to_summary(self):
        data = {
            "multi_chart_data": {
                "title": "Metrics",
                "charts": [
                    {"metric": "cpu", "labels": ["t1", "t2"], "datasets": [{"data": [1, 2]}]},
                    {"metric": "mem", "labels": ["t1", "t2"], "datasets": [{"data": [3, 4]}]},
                ],
            }
        }
        text = json.dumps(data)
        result, out_text, stripped = _strip_chart_data(data, text, "key_61", "tool")
        assert stripped is True
        mcd = result["multi_chart_data"]
        assert mcd["_chart_rendered"] is True
        assert mcd["chart_count"] == 2
        assert mcd["metrics"] == ["cpu", "mem"]
        assert mcd["data_points"] == 2

    def test_62_chart_already_rendered_skipped(self):
        data = {"chart_data": {"_chart_rendered": True, "title": "T"}}
        text = json.dumps(data)
        result, out_text, stripped = _strip_chart_data(data, text, "key_62", "tool")
        assert stripped is False

    def test_63_stale_chart_cache_eviction(self):
        # Insert a stale entry
        from app.hooks.session_hooks import _CACHE_TTL_SECONDS
        CHART_DATA_CACHE["stale_key"] = {"_ts": _time.monotonic() - _CACHE_TTL_SECONDS - 10}

        data = {
            "chart_data": {
                "title": "T",
                "labels": ["a"],
                "datasets": [{"data": [1]}],
            }
        }
        text = json.dumps(data)
        _strip_chart_data(data, text, "fresh_key", "tool")
        assert "stale_key" not in CHART_DATA_CACHE
        assert "fresh_key" in CHART_DATA_CACHE
