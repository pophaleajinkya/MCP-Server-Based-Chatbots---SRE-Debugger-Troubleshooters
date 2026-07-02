"""Unit tests for additional runner.py coverage gaps.

Covers: _sanitize_floats (extra cases), _collect_grafana_urls,
_extract_graph_events, _is_mcp_connection_error, _identify_failed_server,
_build_mcp_error_message, register_mcp_tools, register_mcp_servers,
_tool_category, _tool_label, _build_user_content, _parts_to_text.
"""

import math
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub google.genai only when the real package is not installed.
try:
    import google.genai as _real_genai  # noqa: F401
except ImportError:
    mock_genai = ModuleType("google.genai")
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.genai", mock_genai)
    sys.modules.setdefault("google.genai.types", MagicMock())


from app.services.runner import (
    _sanitize_floats,
    _collect_grafana_urls,
    _extract_graph_events,
    _is_mcp_connection_error,
    _identify_failed_server,
    _build_mcp_error_message,
    register_mcp_tools,
    register_mcp_servers,
    _tool_category,
    _tool_label,
    _build_user_content,
    _parts_to_text,
    _mcp_server_registry,
)


# ===========================================================================
# _sanitize_floats — additional coverage
# ===========================================================================

class TestSanitizeFloatsExtended:

    def test_normal_float_unchanged(self):
        assert _sanitize_floats(3.14) == 3.14

    def test_nan_becomes_none(self):
        assert _sanitize_floats(float("nan")) is None

    def test_inf_becomes_none(self):
        assert _sanitize_floats(float("inf")) is None

    def test_neg_inf_becomes_none(self):
        assert _sanitize_floats(float("-inf")) is None

    def test_nested_dict_with_nan(self):
        result = _sanitize_floats({"a": float("nan"), "b": 1.0})
        assert result == {"a": None, "b": 1.0}

    def test_list_with_nan(self):
        result = _sanitize_floats([float("nan"), 2.5, float("inf")])
        assert result == [None, 2.5, None]

    def test_non_float_unchanged(self):
        assert _sanitize_floats("hello") == "hello"
        assert _sanitize_floats(42) == 42
        assert _sanitize_floats(None) is None

    def test_deeply_nested(self):
        obj = {"outer": [{"inner": float("nan")}]}
        result = _sanitize_floats(obj)
        assert result == {"outer": [{"inner": None}]}

    def test_zero_unchanged(self):
        assert _sanitize_floats(0.0) == 0.0


# ===========================================================================
# _collect_grafana_urls
# ===========================================================================

class TestCollectGrafanaUrls:

    def test_top_level_grafana_url(self):
        seen = set()
        _collect_grafana_urls({"grafana_url": "https://grafana/panel/1"}, seen)
        assert seen == {"https://grafana/panel/1"}

    def test_nested_grafana_url(self):
        seen = set()
        obj = {"checks": {"cpu": {"grafana_url": "https://grafana/cpu"}}}
        _collect_grafana_urls(obj, seen)
        assert "https://grafana/cpu" in seen

    def test_multiple_urls_all_collected(self):
        seen = set()
        obj = {
            "grafana_url": "https://grafana/a",
            "checks": {"mem": {"grafana_url": "https://grafana/b"}},
        }
        _collect_grafana_urls(obj, seen)
        assert seen == {"https://grafana/a", "https://grafana/b"}

    def test_depth_greater_than_6_stops(self):
        seen = set()
        deep = {"grafana_url": "https://grafana/deep"}
        _collect_grafana_urls(deep, seen, depth=7)
        assert len(seen) == 0

    def test_non_dict_list_noop(self):
        seen = set()
        _collect_grafana_urls("just a string", seen)
        _collect_grafana_urls(42, seen)
        _collect_grafana_urls(None, seen)
        assert len(seen) == 0

    def test_duplicate_urls_deduplicated(self):
        seen = set()
        obj = [
            {"grafana_url": "https://grafana/x"},
            {"grafana_url": "https://grafana/x"},
        ]
        _collect_grafana_urls(obj, seen)
        assert seen == {"https://grafana/x"}

    def test_empty_string_url_ignored(self):
        seen = set()
        _collect_grafana_urls({"grafana_url": ""}, seen)
        assert len(seen) == 0

    def test_non_string_url_ignored(self):
        seen = set()
        _collect_grafana_urls({"grafana_url": 123}, seen)
        assert len(seen) == 0

    def test_list_of_dicts(self):
        seen = set()
        obj = [{"grafana_url": "https://grafana/1"}, {"grafana_url": "https://grafana/2"}]
        _collect_grafana_urls(obj, seen)
        assert seen == {"https://grafana/1", "https://grafana/2"}


# ===========================================================================
# _extract_graph_events
# ===========================================================================

class TestExtractGraphEvents:

    def test_chart_data_dict_produces_render_chart(self):
        resp = {"chart_data": {"labels": [1, 2], "datasets": []}}
        events = _extract_graph_events(resp)
        assert any(e[0] == "render_chart" for e in events)

    def test_multi_chart_data_produces_render_multi_chart(self):
        resp = {"multi_chart_data": {"charts": []}}
        events = _extract_graph_events(resp)
        assert any(e[0] == "render_multi_chart" for e in events)

    def test_table_data_produces_render_table_data(self):
        resp = {"table_data": {"columns": [], "rows": []}}
        events = _extract_graph_events(resp)
        assert any(e[0] == "render_table_data" for e in events)

    def test_nested_grafana_url_produces_render_grafana_panel(self):
        resp = {"checks": {"cpu": {"grafana_url": "https://grafana/cpu"}}}
        events = _extract_graph_events(resp)
        assert any(e[0] == "render_grafana_panel" for e in events)
        urls = [e[1]["url"] for e in events if e[0] == "render_grafana_panel"]
        assert "https://grafana/cpu" in urls

    def test_multiple_types_in_one_response(self):
        resp = {
            "chart_data": {"labels": []},
            "table_data": {"columns": []},
            "grafana_url": "https://grafana/x",
        }
        events = _extract_graph_events(resp)
        types = {e[0] for e in events}
        assert "render_chart" in types
        assert "render_table_data" in types
        assert "render_grafana_panel" in types

    def test_no_recognized_keys_returns_empty(self):
        resp = {"status": "ok", "message": "done"}
        assert _extract_graph_events(resp) == []

    def test_chart_data_non_dict_ignored(self):
        resp = {"chart_data": "not a dict"}
        events = _extract_graph_events(resp)
        assert not any(e[0] == "render_chart" for e in events)

    def test_empty_response(self):
        assert _extract_graph_events({}) == []


# ===========================================================================
# _is_mcp_connection_error
# ===========================================================================

class TestIsMcpConnectionError:

    def test_connection_error_with_signature(self):
        exc = ConnectionError("Failed to get tools from MCP server at http://x")
        assert _is_mcp_connection_error(exc) is True

    def test_connection_error_without_signature(self):
        exc = ConnectionError("some other error")
        assert _is_mcp_connection_error(exc) is False

    def test_non_connection_error_with_signature(self):
        exc = RuntimeError("Failed to call tool on MCP server blah")
        assert _is_mcp_connection_error(exc) is True

    def test_unrelated_error(self):
        exc = ValueError("bad input")
        assert _is_mcp_connection_error(exc) is False

    def test_mcp_session_signature(self):
        exc = Exception("MCP session closed unexpectedly")
        assert _is_mcp_connection_error(exc) is True


# ===========================================================================
# _identify_failed_server
# ===========================================================================

class TestIdentifyFailedServer:

    def test_matches_url_in_exception(self):
        register_mcp_servers([
            {"name": "metrics-server", "url": "http://metrics:8080"},
        ])
        exc = ConnectionError("Failed to connect to MCP server at http://metrics:8080")
        assert _identify_failed_server(exc) == "metrics-server"

    def test_no_match_returns_none(self):
        register_mcp_servers([
            {"name": "metrics-server", "url": "http://metrics:8080"},
        ])
        exc = ConnectionError("Failed to connect at http://unknown:9999")
        assert _identify_failed_server(exc) is None

    def test_matches_url_in_cause_chain(self):
        register_mcp_servers([
            {"name": "health-api", "url": "http://health:5000"},
        ])
        cause = ConnectionError("http://health:5000 refused")
        exc = RuntimeError("wrapper")
        exc.__cause__ = cause
        assert _identify_failed_server(exc) == "health-api"

    def test_empty_registry_returns_none(self):
        register_mcp_servers([])
        exc = ConnectionError("some error")
        assert _identify_failed_server(exc) is None


# ===========================================================================
# _build_mcp_error_message
# ===========================================================================

class TestBuildMcpErrorMessage:

    def test_identified_server_in_message(self):
        register_mcp_servers([
            {"name": "metrics-server", "url": "http://metrics:8080"},
        ])
        exc = ConnectionError("http://metrics:8080 down")
        msg = _build_mcp_error_message(exc)
        assert "metrics-server" in msg

    def test_fallback_lists_all_servers(self):
        register_mcp_servers([
            {"name": "alpha", "url": "http://alpha:1"},
            {"name": "beta", "url": "http://beta:2"},
        ])
        exc = ConnectionError("unknown server issue")
        msg = _build_mcp_error_message(exc)
        assert "alpha" in msg and "beta" in msg

    def test_empty_registry_generic_message(self):
        register_mcp_servers([])
        exc = ConnectionError("unknown")
        msg = _build_mcp_error_message(exc)
        assert "backend services" in msg.lower()


# ===========================================================================
# register_mcp_tools / register_mcp_servers
# ===========================================================================

class TestRegisterMcpTools:

    def test_register_mcp_tools_stores_list(self):
        tools = [{"name": "tool_a"}, {"name": "tool_b"}]
        register_mcp_tools(tools)
        from app.services.runner import _mcp_tool_registry
        assert len(_mcp_tool_registry) == 2
        assert _mcp_tool_registry[0]["name"] == "tool_a"

    def test_register_mcp_tools_replaces_previous(self):
        register_mcp_tools([{"name": "old"}])
        register_mcp_tools([{"name": "new1"}, {"name": "new2"}])
        from app.services.runner import _mcp_tool_registry
        assert len(_mcp_tool_registry) == 2


class TestRegisterMcpServers:

    def test_register_mcp_servers_populates_registry(self):
        register_mcp_servers([
            {"name": "svc-a", "url": "http://a:1"},
            {"name": "svc-b", "url": "http://b:2"},
        ])
        from app.services.runner import _mcp_server_registry
        assert _mcp_server_registry["http://a:1"] == "svc-a"
        assert _mcp_server_registry["http://b:2"] == "svc-b"


# ===========================================================================
# _tool_category
# ===========================================================================

class TestToolCategory:

    def test_skill_tools_return_skill(self):
        assert _tool_category("list_skills") == "skill"
        assert _tool_category("load_skill") == "skill"
        assert _tool_category("load_skill_resource") == "skill"
        assert _tool_category("run_skill_script") == "skill"

    def test_mcp_tool_returns_tool(self):
        assert _tool_category("wcnp_check_health") == "tool"
        assert _tool_category("prometheus_query_range") == "tool"

    def test_unknown_returns_tool(self):
        assert _tool_category("some_random_thing") == "tool"

    def test_empty_name_returns_tool(self):
        assert _tool_category("") == "tool"


# ===========================================================================
# _tool_label
# ===========================================================================

class TestToolLabel:

    # ── Skill tools ──

    def test_list_skills_label(self):
        label = _tool_label("list_skills")
        assert "Discovering Skills" in label

    def test_load_skill_with_args(self):
        label = _tool_label("load_skill", args={"skill_name": "health-triage"})
        assert "Loading Skill" in label
        assert "health-triage" in label

    def test_load_skill_without_args(self):
        label = _tool_label("load_skill")
        assert "Loading Skill" in label

    def test_run_skill_script_with_skill_and_path(self):
        label = _tool_label(
            "run_skill_script",
            args={"skill_name": "health", "script_path": "scripts/summarize_health.py"},
        )
        assert "Running" in label
        assert "health" in label
        assert "summarize_health.py" in label

    def test_run_skill_script_with_skill_only(self):
        label = _tool_label("run_skill_script", args={"skill_name": "health"})
        assert "Running" in label
        assert "health" in label

    def test_load_skill_resource_with_skill_and_resource(self):
        label = _tool_label(
            "load_skill_resource",
            args={"skill_name": "triage", "resource_path": "data/reference.md"},
        )
        assert "Loading Skill Resource" in label
        assert "triage" in label
        assert "reference.md" in label

    # ── MCP tools ──

    def test_wcnp_prefix_stripped(self):
        label = _tool_label("wcnp_check_health")
        assert label == "Check Health"

    def test_mcp_prefix_stripped(self):
        label = _tool_label("mcp_some_action")
        assert label == "Some Action"

    def test_k8s_prefix_stripped(self):
        label = _tool_label("k8s_list_pods")
        assert label == "List Pods"

    def test_unknown_tool_titlecased(self):
        label = _tool_label("prometheus_query_range")
        assert label == "Prometheus Query Range"

    def test_empty_name_returns_unknown_tool(self):
        assert _tool_label("") == "Unknown Tool"

    def test_none_handled(self):
        """Empty string edge case."""
        assert _tool_label("") == "Unknown Tool"


# ===========================================================================
# _build_user_content
# ===========================================================================

class TestBuildUserContent:

    def test_returns_content_with_role_user(self):
        content = _build_user_content("hello")
        assert content.role == "user"

    def test_contains_text_part(self):
        content = _build_user_content("test query")
        assert len(content.parts) == 1
        assert content.parts[0].text == "test query"

    def test_empty_query(self):
        content = _build_user_content("")
        assert content.parts[0].text == ""


# ===========================================================================
# _parts_to_text
# ===========================================================================

class TestPartsToText:

    def test_single_text_part(self):
        part = MagicMock()
        part.text = "hello"
        assert _parts_to_text([part]) == "hello"

    def test_multiple_parts_joined(self):
        p1 = MagicMock()
        p1.text = "line1"
        p2 = MagicMock()
        p2.text = "line2"
        assert _parts_to_text([p1, p2]) == "line1\nline2"

    def test_empty_text_skipped(self):
        p1 = MagicMock()
        p1.text = "hello"
        p2 = MagicMock()
        p2.text = ""
        assert _parts_to_text([p1, p2]) == "hello"

    def test_no_text_attr_skipped(self):
        p1 = MagicMock(spec=[])  # no text attribute
        p2 = MagicMock()
        p2.text = "world"
        assert _parts_to_text([p1, p2]) == "world"

    def test_empty_parts_list(self):
        assert _parts_to_text([]) == ""

    def test_none_text_skipped(self):
        p = MagicMock()
        p.text = None
        assert _parts_to_text([p]) == ""

    def test_thought_parts_excluded(self):
        """Thought parts (Claude extended thinking) should be filtered out."""
        p_normal = MagicMock()
        p_normal.text = "final answer"
        p_normal.thought = False
        p_thought = MagicMock()
        p_thought.text = "internal reasoning chain"
        p_thought.thought = True
        assert _parts_to_text([p_thought, p_normal]) == "final answer"

    def test_only_thought_parts_returns_empty(self):
        """If all parts are thoughts, result should be empty."""
        p = MagicMock()
        p.text = "deep thinking"
        p.thought = True
        assert _parts_to_text([p]) == ""

    def test_mixed_thought_and_normal_parts(self):
        """Normal text parts are kept, thought parts are filtered."""
        p1 = MagicMock()
        p1.text = "line1"
        p1.thought = False
        p2 = MagicMock()
        p2.text = "thinking block"
        p2.thought = True
        p3 = MagicMock()
        p3.text = "line3"
        p3.thought = False
        assert _parts_to_text([p1, p2, p3]) == "line1\nline3"
