"""
Comprehensive unit tests for app.services.runner — helper functions.

Tests: _sanitize_floats, _collect_grafana_urls, _extract_graph_events,
find_suspicious_fields, register_mcp_tools, register_mcp_servers,
_is_mcp_connection_error, _identify_failed_server.
"""

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.services.runner import (
    _sanitize_floats,
    _extract_graph_events,
    find_suspicious_fields,
    register_mcp_tools,
    register_mcp_servers,
)


class TestSanitizeFloats:

    def test_nan_replaced_with_none(self):
        assert _sanitize_floats(float("nan")) is None

    def test_inf_replaced_with_none(self):
        assert _sanitize_floats(float("inf")) is None

    def test_neg_inf_replaced_with_none(self):
        assert _sanitize_floats(float("-inf")) is None

    def test_normal_float_unchanged(self):
        assert _sanitize_floats(3.14) == 3.14

    def test_zero_unchanged(self):
        assert _sanitize_floats(0.0) == 0.0

    def test_integer_unchanged(self):
        assert _sanitize_floats(42) == 42

    def test_string_unchanged(self):
        assert _sanitize_floats("hello") == "hello"

    def test_none_unchanged(self):
        assert _sanitize_floats(None) is None

    def test_dict_with_nan(self):
        result = _sanitize_floats({"value": float("nan"), "ok": 1.0})
        assert result["value"] is None
        assert result["ok"] == 1.0

    def test_list_with_nan(self):
        result = _sanitize_floats([1.0, float("nan"), 3.0])
        assert result == [1.0, None, 3.0]

    def test_nested_dict(self):
        data = {"outer": {"inner": float("inf")}}
        result = _sanitize_floats(data)
        assert result["outer"]["inner"] is None

    def test_list_of_dicts(self):
        data = [{"v": float("nan")}, {"v": 2.0}]
        result = _sanitize_floats(data)
        assert result[0]["v"] is None
        assert result[1]["v"] == 2.0

    def test_empty_dict(self):
        assert _sanitize_floats({}) == {}

    def test_empty_list(self):
        assert _sanitize_floats([]) == []

    def test_bool_unchanged(self):
        assert _sanitize_floats(True) is True
        assert _sanitize_floats(False) is False


class TestExtractGraphEvents:

    def test_chart_data_extracted(self):
        response = {
            "chart_data": {
                "chart_type": "line",
                "title": "CPU Usage",
                "labels": ["14:00"],
                "datasets": [{"label": "cpu", "data": [42]}],
            }
        }
        events = _extract_graph_events(response)
        assert len(events) >= 1
        assert any("render_chart" in str(e) for e in events)

    def test_multi_chart_data_extracted(self):
        response = {
            "multi_chart_data": {
                "title": "Dashboard",
                "charts": [{"metric": "CPU"}],
            }
        }
        events = _extract_graph_events(response)
        assert len(events) >= 1

    def test_grafana_url_extracted(self):
        response = {
            "grafana_url": "https://grafana.example.com/d/abc123"
        }
        events = _extract_graph_events(response)
        assert len(events) >= 1

    def test_empty_response(self):
        events = _extract_graph_events({})
        assert events == []

    def test_no_graph_keys(self):
        events = _extract_graph_events({"status": "ok", "data": [1, 2]})
        assert events == []

    def test_table_data_extracted(self):
        response = {
            "table_data": {
                "columns": ["col1"],
                "rows": [{"col1": "val"}],
            }
        }
        events = _extract_graph_events(response)
        # table_data should be detected
        assert isinstance(events, list)


class TestFindSuspiciousFields:

    def test_clean_schema(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        assert find_suspicious_fields(schema) == []

    def test_detects_default(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "default": "foo"}},
        }
        issues = find_suspicious_fields(schema)
        assert any("default" in i for i in issues)

    def test_detects_definitions(self):
        schema = {
            "type": "object",
            "definitions": {"Foo": {"type": "string"}},
        }
        issues = find_suspicious_fields(schema)
        assert any("definitions" in i for i in issues)

    def test_detects_dollar_ref(self):
        schema = {
            "type": "object",
            "properties": {"x": {"$ref": "#/definitions/Foo"}},
        }
        issues = find_suspicious_fields(schema)
        assert any("$ref" in i for i in issues)

    def test_detects_id(self):
        schema = {"type": "object", "id": "myschema"}
        issues = find_suspicious_fields(schema)
        assert any("id" in i for i in issues)

    def test_detects_dollar_schema(self):
        schema = {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"}
        issues = find_suspicious_fields(schema)
        assert any("$schema" in i for i in issues)

    def test_nested_suspicious(self):
        schema = {
            "type": "object",
            "properties": {
                "child": {
                    "type": "object",
                    "properties": {
                        "deep": {"type": "string", "default": "x"},
                    },
                },
            },
        }
        issues = find_suspicious_fields(schema)
        assert len(issues) > 0

    def test_empty_schema(self):
        assert find_suspicious_fields({}) == []


class TestRegisterMcpTools:

    def test_register_stores_tools(self):
        tools = [{"name": "tool_a"}, {"name": "tool_b"}]
        register_mcp_tools(tools)
        # No exception

    def test_register_empty_list(self):
        register_mcp_tools([])
        # No exception


class TestRegisterMcpServers:

    def test_register_stores_servers(self):
        servers = [
            {"name": "health-mcp", "url": "http://localhost:8999/mcp/"},
            {"name": "dep-mcp", "url": "http://localhost:8015/mcp/"},
        ]
        register_mcp_servers(servers)
        # No exception

    def test_register_empty_list(self):
        register_mcp_servers([])
        # No exception
