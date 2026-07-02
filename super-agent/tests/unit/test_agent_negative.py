"""Negative and edge-case tests for agent.py, a2ui.py, and caching_mcp_toolset.py.

Covers malformed inputs, missing configs, concurrency, error propagation,
boundary conditions, and other adversarial scenarios.
"""

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Stub a2ui package when real package is absent
# ---------------------------------------------------------------------------

class _StubResponsePart:
    """Minimal stand-in for a2ui.core.parser.response_part.ResponsePart."""
    def __init__(self, text="", a2ui_json=None):
        self.text = text
        self.a2ui_json = a2ui_json


try:
    from a2ui.core.parser.parser import has_a2ui_parts as _real_has  # noqa: F401
    _HAS_A2UI = True
except (ImportError, ModuleNotFoundError):
    _HAS_A2UI = False

if not _HAS_A2UI:
    def _ensure_a2ui_stubs():
        _a2ui_modules = [
            "a2ui", "a2ui.basic_catalog", "a2ui.basic_catalog.provider",
            "a2ui.core", "a2ui.core.parser", "a2ui.core.parser.parser",
            "a2ui.core.parser.response_part", "a2ui.core.schema",
            "a2ui.core.schema.constants", "a2ui.core.schema.manager",
        ]
        for dotted in _a2ui_modules:
            parts = dotted.split(".")
            for depth in range(1, len(parts) + 1):
                name = ".".join(parts[:depth])
                if name not in sys.modules:
                    mod = types.ModuleType(name)
                    sys.modules[name] = mod
                    if depth > 1:
                        parent = ".".join(parts[:depth - 1])
                        setattr(sys.modules[parent], parts[depth - 1], mod)

    _ensure_a2ui_stubs()
    sys.modules["a2ui.basic_catalog.provider"].BasicCatalog = MagicMock()
    sys.modules["a2ui.core.parser.parser"].has_a2ui_parts = MagicMock(return_value=False)
    sys.modules["a2ui.core.parser.parser"].parse_response = MagicMock(return_value=[])
    sys.modules["a2ui.core.parser.response_part"].ResponsePart = _StubResponsePart
    sys.modules["a2ui.core.schema.constants"].VERSION_0_9 = "0.9"
    sys.modules["a2ui.core.schema.manager"].A2uiSchemaManager = MagicMock


# Import modules under test
import agent.a2ui as a2ui_mod  # noqa: E402
from agent.caching_mcp_toolset import CachingMCPToolset  # noqa: E402


# ---------------------------------------------------------------------------
# Helper to build a mock schema manager chain
# ---------------------------------------------------------------------------

def _mock_schema_manager(validate_side_effect=None):
    mock_validator = MagicMock()
    if validate_side_effect:
        mock_validator.validate.side_effect = validate_side_effect
    mock_catalog = MagicMock()
    mock_catalog.validator = mock_validator
    mock_mgr = MagicMock()
    mock_mgr.get_selected_catalog.return_value = mock_catalog
    return mock_mgr, mock_validator


# ===========================================================================
# A2UI negative tests
# ===========================================================================


class TestA2UIValidateEmpty:
    """validate_a2ui_response with empty / blank input."""

    def test_empty_string_returns_single_text_part(self):
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=False):
            parts = a2ui_mod.validate_a2ui_response("")
        assert len(parts) == 1
        assert parts[0].text == ""
        assert parts[0].a2ui_json is None

    def test_whitespace_only_returns_text_part(self):
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=False):
            parts = a2ui_mod.validate_a2ui_response("   \n\t  ")
        assert len(parts) == 1
        assert parts[0].text == "   \n\t  "


class TestA2UIValidatePlainText:
    """validate_a2ui_response with plain text (no A2UI blocks)."""

    def test_plain_text_no_tags(self):
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=False):
            parts = a2ui_mod.validate_a2ui_response("Just some plain text")
        assert len(parts) == 1
        assert parts[0].a2ui_json is None

    def test_text_with_angle_brackets_not_a2ui(self):
        text = "Use <b>bold</b> and <i>italic</i> formatting"
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=False):
            parts = a2ui_mod.validate_a2ui_response(text)
        assert parts[0].text == text


class TestA2UIMalformedJSON:
    """validate_a2ui_response with malformed A2UI JSON."""

    def test_malformed_json_raises_when_validator_rejects(self):
        bad_part = _StubResponsePart(text="", a2ui_json={"type": "INVALID"})
        mgr, _ = _mock_schema_manager(validate_side_effect=ValueError("unknown component"))

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[bad_part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            with pytest.raises(ValueError, match="unknown component"):
                a2ui_mod.validate_a2ui_response("<a2ui>{bad}</a2ui>")

    def test_parse_response_raises_on_broken_json(self):
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", side_effect=json.JSONDecodeError("err", "", 0)):
            with pytest.raises(json.JSONDecodeError):
                a2ui_mod.validate_a2ui_response("<a2ui>not json</a2ui>")


class TestA2UIInvalidComponents:
    """validate_a2ui_response with invalid / unsupported component names."""

    def test_unsupported_component_type(self):
        part = _StubResponsePart(text="", a2ui_json={"type": "UnsupportedWidget"})
        mgr, _ = _mock_schema_manager(validate_side_effect=ValueError("UnsupportedWidget not allowed"))

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            with pytest.raises(ValueError, match="UnsupportedWidget"):
                a2ui_mod.validate_a2ui_response("<a2ui>{}</a2ui>")

    def test_component_missing_required_fields(self):
        part = _StubResponsePart(text="", a2ui_json={"type": "Table"})  # missing columns, rows
        mgr, _ = _mock_schema_manager(validate_side_effect=ValueError("missing required field"))

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            with pytest.raises(ValueError, match="missing required"):
                a2ui_mod.validate_a2ui_response("<a2ui>{}</a2ui>")


class TestA2UIDeepNesting:
    """A2UI with deeply nested components."""

    def test_deeply_nested_json_validated(self):
        nested = {"type": "Card", "child": {"type": "Row", "children": [
            {"type": "Column", "children": [{"type": "Text", "text": "deep"}]}
        ]}}
        part = _StubResponsePart(text="", a2ui_json=nested)
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>nested</a2ui>")
        assert parts[0].a2ui_json["type"] == "Card"
        validator.validate.assert_called_once()


class TestA2UITryValidate:
    """try_validate_a2ui_response returns error string on failure."""

    def test_returns_error_string_on_value_error(self):
        with patch.object(a2ui_mod, "validate_a2ui_response",
                          side_effect=ValueError("schema mismatch")):
            parts, err = a2ui_mod.try_validate_a2ui_response("text")
        assert err is not None
        assert "schema mismatch" in err
        assert parts[0].text == "text"

    def test_returns_error_on_runtime_error(self):
        with patch.object(a2ui_mod, "validate_a2ui_response",
                          side_effect=RuntimeError("internal")):
            parts, err = a2ui_mod.try_validate_a2ui_response("text")
        assert "internal" in err

    def test_returns_error_on_type_error(self):
        with patch.object(a2ui_mod, "validate_a2ui_response",
                          side_effect=TypeError("bad type")):
            parts, err = a2ui_mod.try_validate_a2ui_response("text")
        assert "bad type" in err


class TestA2UIGenerateInstruction:
    """generate_a2ui_instruction edge cases."""

    def test_file_missing_returns_empty(self, tmp_path):
        missing = tmp_path / "DOES_NOT_EXIST.md"
        with patch.object(a2ui_mod, "_A2UI_PATTERNS_FILE", missing):
            assert a2ui_mod.generate_a2ui_instruction() == ""

    def test_empty_file_returns_empty(self, tmp_path):
        empty_file = tmp_path / "A2UI_PATTERNS.md"
        empty_file.write_text("", encoding="utf-8")
        with patch.object(a2ui_mod, "_A2UI_PATTERNS_FILE", empty_file):
            assert a2ui_mod.generate_a2ui_instruction() == ""

    def test_whitespace_only_file_returns_empty(self, tmp_path):
        ws_file = tmp_path / "A2UI_PATTERNS.md"
        ws_file.write_text("   \n\n   ", encoding="utf-8")
        with patch.object(a2ui_mod, "_A2UI_PATTERNS_FILE", ws_file):
            assert a2ui_mod.generate_a2ui_instruction() == ""


class TestA2UISchemaManagerSingleton:
    """_get_schema_manager singleton behavior."""

    def test_singleton_returns_same_instance(self):
        a2ui_mod._schema_manager = None
        m1 = a2ui_mod._get_schema_manager()
        m2 = a2ui_mod._get_schema_manager()
        assert m1 is m2

    def test_singleton_resets_when_cleared(self):
        a2ui_mod._schema_manager = None
        m1 = a2ui_mod._get_schema_manager()
        a2ui_mod._schema_manager = None
        m2 = a2ui_mod._get_schema_manager()
        # After clearing, a new instance is created
        assert m2 is not None


class TestA2UIEmptyTags:
    """A2UI with empty <a2ui></a2ui> tags."""

    def test_empty_a2ui_tags(self):
        part = _StubResponsePart(text="", a2ui_json=None)
        mgr, _ = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui></a2ui>")
        assert len(parts) == 1
        assert parts[0].a2ui_json is None


class TestA2UIMultipleBlocks:
    """A2UI with multiple a2ui blocks."""

    def test_multiple_blocks_all_validated(self):
        p1 = _StubResponsePart(text="intro", a2ui_json=None)
        p2 = _StubResponsePart(text="", a2ui_json={"type": "Table", "columns": ["A"]})
        p3 = _StubResponsePart(text="", a2ui_json={"type": "Chart", "chartType": "bar"})
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[p1, p2, p3]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("intro<a2ui>a</a2ui>mid<a2ui>b</a2ui>")
        assert len(parts) == 3
        assert validator.validate.call_count == 2


class TestA2UINestedTags:
    """A2UI with nested a2ui tags (should be handled by parser)."""

    def test_nested_tags_handled_by_parser(self):
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response",
                          side_effect=ValueError("nested a2ui tags not allowed")):
            with pytest.raises(ValueError, match="nested"):
                a2ui_mod.validate_a2ui_response("<a2ui><a2ui>inner</a2ui></a2ui>")


class TestA2UIHTMLInjection:
    """A2UI with HTML injection in component text."""

    def test_html_in_text_passes_through(self):
        malicious = {"type": "Text", "text": '<script>alert("xss")</script>'}
        part = _StubResponsePart(text="", a2ui_json=malicious)
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>{}</a2ui>")
        assert "<script>" in parts[0].a2ui_json["text"]
        validator.validate.assert_called_once()


class TestA2UILargeJSON:
    """A2UI with extremely large JSON (100KB+)."""

    def test_large_json_validated(self):
        large_data = {"type": "Table", "columns": ["col"], "rows": [["x" * 100] for _ in range(1100)]}
        assert len(json.dumps(large_data)) > 100_000
        part = _StubResponsePart(text="", a2ui_json=large_data)
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>big</a2ui>")
        validator.validate.assert_called_once()
        assert len(parts[0].a2ui_json["rows"]) == 1100


class TestA2UIUnicodeContent:
    """A2UI with unicode content (emoji, RTL, CJK)."""

    def test_unicode_emoji_rtl_cjk(self):
        unicode_json = {"type": "Text", "text": "Hello \U0001f600 \u0645\u0631\u062d\u0628\u0627 \u4f60\u597d"}
        part = _StubResponsePart(text="", a2ui_json=unicode_json)
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>unicode</a2ui>")
        assert "\U0001f600" in parts[0].a2ui_json["text"]
        assert "\u4f60\u597d" in parts[0].a2ui_json["text"]


class TestA2UINullValues:
    """A2UI with null values in JSON."""

    def test_null_values_in_json(self):
        null_json = {"type": "Card", "child": None, "title": None}
        part = _StubResponsePart(text="", a2ui_json=null_json)
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>null</a2ui>")
        assert parts[0].a2ui_json["child"] is None
        validator.validate.assert_called_once()


class TestA2UIExtraFields:
    """A2UI with extra unexpected fields."""

    def test_extra_fields_pass_to_validator(self):
        extra_json = {"type": "Text", "text": "hi", "unknownField": 42, "foo": "bar"}
        part = _StubResponsePart(text="", a2ui_json=extra_json)
        mgr, validator = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>extra</a2ui>")
        validator.validate.assert_called_once_with(extra_json)


class TestA2UIOpeningTagOnly:
    """A2UI with just opening tag, no closing tag."""

    def test_opening_tag_only(self):
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response",
                          side_effect=ValueError("unclosed a2ui tag")):
            with pytest.raises(ValueError, match="unclosed"):
                a2ui_mod.validate_a2ui_response("<a2ui>no closing tag")


class TestA2UIWhitespaceBetweenTags:
    """A2UI with whitespace between tags."""

    def test_whitespace_between_tags(self):
        part = _StubResponsePart(text="", a2ui_json=None)
        mgr, _ = _mock_schema_manager()

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mgr):
            parts = a2ui_mod.validate_a2ui_response("<a2ui>  \n\t  </a2ui>")
        assert len(parts) == 1


class TestA2UIBinaryContent:
    """validate_a2ui_response with binary content mixed in."""

    def test_binary_content_mixed(self):
        binary_text = "Some text \x00\x01\x02 with binary"
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=False):
            parts = a2ui_mod.validate_a2ui_response(binary_text)
        assert parts[0].text == binary_text


class TestA2UIAllowedComponentsBoundary:
    """_ALLOWED_COMPONENTS list boundary (first and last component)."""

    def test_first_allowed_component_is_text(self):
        assert a2ui_mod._ALLOWED_COMPONENTS[0] == "Text"

    def test_last_allowed_component_is_icon(self):
        assert a2ui_mod._ALLOWED_COMPONENTS[-1] == "Icon"

    def test_allowed_components_count(self):
        assert len(a2ui_mod._ALLOWED_COMPONENTS) == 11


# ===========================================================================
# CachingMCPToolset negative tests
# ===========================================================================


class TestCachingMCPToolsetParentException:
    """get_tools when parent class raises exception."""

    @pytest.mark.asyncio
    async def test_get_tools_parent_raises(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()

        with patch.object(
            CachingMCPToolset.__bases__[0], "get_tools",
            new_callable=AsyncMock,
            side_effect=ConnectionError("MCP server unreachable"),
        ):
            with pytest.raises(ConnectionError, match="MCP server unreachable"):
                await toolset.get_tools()

    @pytest.mark.asyncio
    async def test_cache_remains_none_after_exception(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()

        with patch.object(
            CachingMCPToolset.__bases__[0], "get_tools",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ):
            with pytest.raises(RuntimeError):
                await toolset.get_tools()
        assert toolset._cached_tools is None


class TestCachingMCPToolsetConcurrency:
    """Concurrent get_tools calls (lock contention)."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_only_fetch_once(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()
        toolset._connection_params = MagicMock(url="http://test")

        mock_tool = MagicMock()
        mock_tool.name = "tool1"
        call_count = 0

        async def _slow_get_tools(self_inner, readonly_context=None):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return [mock_tool]

        with patch.object(
            CachingMCPToolset.__bases__[0], "get_tools",
            new=_slow_get_tools,
        ):
            results = await asyncio.gather(
                toolset.get_tools(), toolset.get_tools(), toolset.get_tools()
            )

        assert call_count == 1
        for r in results:
            assert r == [mock_tool]


class TestCachingMCPToolsetInvalidateAndRefetch:
    """invalidate_cache then get_tools (re-fetches)."""

    @pytest.mark.asyncio
    async def test_invalidate_then_refetch(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()
        toolset._connection_params = MagicMock(url="http://test")

        tool_v1 = MagicMock(); tool_v1.name = "v1"
        tool_v2 = MagicMock(); tool_v2.name = "v2"
        call_sequence = iter([[tool_v1], [tool_v2]])

        async def _get(*a, **kw):
            return next(call_sequence)

        with patch.object(CachingMCPToolset.__bases__[0], "get_tools", new=_get):
            first = await toolset.get_tools()
            assert first[0].name == "v1"

            toolset.invalidate_cache()
            assert toolset._cached_tools is None

            second = await toolset.get_tools()
            assert second[0].name == "v2"


class TestCachingMCPToolsetCacheWithNone:
    """Cache with None value should not be confused with 'not cached'."""

    @pytest.mark.asyncio
    async def test_empty_list_is_cached(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()
        toolset._connection_params = MagicMock(url="http://test")

        call_count = 0

        async def _get(*a, **kw):
            nonlocal call_count
            call_count += 1
            return []

        with patch.object(CachingMCPToolset.__bases__[0], "get_tools", new=_get):
            r1 = await toolset.get_tools()
            r2 = await toolset.get_tools()

        assert r1 == []
        assert r2 == []
        assert call_count == 1


class TestCachingMCPToolsetTimeout:
    """Timeout during tool fetch."""

    @pytest.mark.asyncio
    async def test_timeout_during_fetch(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()

        with patch.object(
            CachingMCPToolset.__bases__[0], "get_tools",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError("timed out"),
        ):
            with pytest.raises(asyncio.TimeoutError):
                await toolset.get_tools()
        assert toolset._cached_tools is None


class TestCachingMCPToolsetLargeToolList:
    """Very large tool list (1000+ tools)."""

    @pytest.mark.asyncio
    async def test_large_tool_list_cached(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()
        toolset._connection_params = MagicMock(url="http://test")

        big_list = []
        for i in range(1200):
            t = MagicMock()
            t.name = f"tool_{i}"
            big_list.append(t)

        async def _get(*a, **kw):
            return big_list

        with patch.object(CachingMCPToolset.__bases__[0], "get_tools", new=_get):
            result = await toolset.get_tools()
        assert len(result) == 1200
        assert toolset._cached_tools is result


class TestCachingMCPToolsetConnectionFailure:
    """Connection failure during tool fetch."""

    @pytest.mark.asyncio
    async def test_connection_refused(self):
        toolset = CachingMCPToolset.__new__(CachingMCPToolset)
        toolset._cached_tools = None
        toolset._cache_lock = asyncio.Lock()

        with patch.object(
            CachingMCPToolset.__bases__[0], "get_tools",
            new_callable=AsyncMock,
            side_effect=OSError("Connection refused"),
        ):
            with pytest.raises(OSError, match="Connection refused"):
                await toolset.get_tools()


# ===========================================================================
# agent.py negative tests (_HeaderInjectingClient)
# ===========================================================================

# Import _HeaderInjectingClient — agent.py runs module-level code that
# requires settings, so we must patch get_settings before import.
from agent.agent import _HeaderInjectingClient  # noqa: E402


class TestHeaderInjectingClientMissingHeaders:
    """_HeaderInjectingClient with missing headers."""

    def test_no_llm_headers_returns_kwargs_unchanged(self):
        client = _HeaderInjectingClient()
        kwargs = {"temperature": 0.7}
        with patch("agent.agent.get_llm_headers", return_value={}):
            result = client._merge_llm_headers(kwargs)
        assert "extra_headers" not in result
        assert result["temperature"] == 0.7

    def test_empty_context_headers(self):
        client = _HeaderInjectingClient()
        kwargs = {}
        with patch("agent.agent.get_llm_headers", return_value={}):
            result = client._merge_llm_headers(kwargs)
        assert result == {}


class TestHeaderInjectingClientSpecialChars:
    """Header injection with special characters."""

    def test_special_chars_in_header_values(self):
        client = _HeaderInjectingClient()
        special_headers = {"wm_llm_gw.token": "abc=+/\u00e9\u00f1"}
        kwargs = {}
        with patch("agent.agent.get_llm_headers", return_value=special_headers):
            result = client._merge_llm_headers(kwargs)
        assert result["extra_headers"]["wm_llm_gw.token"] == "abc=+/\u00e9\u00f1"

    def test_header_with_newline(self):
        client = _HeaderInjectingClient()
        headers = {"wm_llm_gw.key": "value\ninjection"}
        kwargs = {}
        with patch("agent.agent.get_llm_headers", return_value=headers):
            result = client._merge_llm_headers(kwargs)
        assert "\n" in result["extra_headers"]["wm_llm_gw.key"]


class TestHeaderInjectingClientLongValues:
    """Header injection with very long header values."""

    def test_very_long_header_value(self):
        client = _HeaderInjectingClient()
        long_val = "x" * 100_000
        kwargs = {}
        with patch("agent.agent.get_llm_headers", return_value={"wm_llm_gw.big": long_val}):
            result = client._merge_llm_headers(kwargs)
        assert len(result["extra_headers"]["wm_llm_gw.big"]) == 100_000


class TestHeaderInjectingClientPreservesExisting:
    """_HeaderInjectingClient preserves existing headers."""

    def test_existing_headers_preserved(self):
        client = _HeaderInjectingClient()
        kwargs = {"extra_headers": {"existing-key": "existing-val"}}
        new_headers = {"wm_llm_gw.new": "new-val"}
        with patch("agent.agent.get_llm_headers", return_value=new_headers):
            result = client._merge_llm_headers(kwargs)
        assert result["extra_headers"]["existing-key"] == "existing-val"
        assert result["extra_headers"]["wm_llm_gw.new"] == "new-val"

    def test_new_headers_override_existing_same_key(self):
        client = _HeaderInjectingClient()
        kwargs = {"extra_headers": {"wm_llm_gw.key": "old"}}
        with patch("agent.agent.get_llm_headers", return_value={"wm_llm_gw.key": "new"}):
            result = client._merge_llm_headers(kwargs)
        assert result["extra_headers"]["wm_llm_gw.key"] == "new"


class TestSanitizeMessages:
    """_sanitize_messages edge cases."""

    def test_empty_messages_list(self):
        result = _HeaderInjectingClient._sanitize_messages([])
        assert result == []

    def test_drops_empty_string_content(self):
        msgs = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": ""}]
        result = _HeaderInjectingClient._sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "hello"

    def test_drops_whitespace_only_text_blocks(self):
        msgs = [{"role": "assistant", "content": [
            {"type": "text", "text": "  \n  "}
        ]}]
        result = _HeaderInjectingClient._sanitize_messages(msgs)
        assert len(result) == 0

    def test_keeps_non_text_blocks(self):
        msgs = [{"role": "assistant", "content": [
            {"type": "image", "url": "http://example.com/img.png"},
            {"type": "text", "text": ""},
        ]}]
        result = _HeaderInjectingClient._sanitize_messages(msgs)
        assert len(result) == 1
        assert len(result[0]["content"]) == 1
        assert result[0]["content"][0]["type"] == "image"


class TestInjectCacheControl:
    """_inject_cache_control edge cases."""

    def test_empty_messages(self):
        result = _HeaderInjectingClient._inject_cache_control([])
        assert result == []

    def test_no_user_message(self):
        msgs = [{"role": "system", "content": "sys prompt"}]
        result = _HeaderInjectingClient._inject_cache_control(msgs)
        assert len(result) == 1
        # system message should get cache_control
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["cache_control"] == {"type": "ephemeral"}

    def test_empty_content_string_not_wrapped(self):
        msgs = [{"role": "system", "content": ""}]
        result = _HeaderInjectingClient._inject_cache_control(msgs)
        # Empty string content should not be wrapped
        assert result[0]["content"] == ""


class TestShrinkForRetry:
    """_shrink_for_retry edge cases."""

    def test_single_user_message_preserved(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "query"},
        ]
        result = _HeaderInjectingClient._shrink_for_retry(msgs)
        assert len(result) == 2

    def test_tool_messages_truncated(self):
        long_text = "x" * 10000
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "tool", "content": long_text},
        ]
        result = _HeaderInjectingClient._shrink_for_retry(msgs)
        tool_msg = [m for m in result if m["role"] == "tool"][0]
        assert len(tool_msg["content"]) < len(long_text)

    def test_multiple_user_turns_drops_older(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old query"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "new query"},
        ]
        result = _HeaderInjectingClient._shrink_for_retry(msgs)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "context window" in user_msgs[0]["content"].lower() or "new query" in user_msgs[0]["content"]


class TestEstimatePayloadChars:
    """_estimate_payload_chars edge cases."""

    def test_empty_messages(self):
        client = _HeaderInjectingClient()
        assert client._estimate_payload_chars([]) == 0

    def test_mixed_content_types(self):
        client = _HeaderInjectingClient()
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "world"},
                {"type": "tool_use", "content": "data"},
            ]},
        ]
        total = client._estimate_payload_chars(msgs)
        assert total > 0


class TestIsLikelyContextOverflow:
    """_is_likely_context_overflow detection."""

    def test_keyword_match(self):
        client = _HeaderInjectingClient()
        exc = Exception("prompt is too long for this model")
        assert client._is_likely_context_overflow(exc, []) is True

    def test_large_payload_generic_400(self):
        client = _HeaderInjectingClient()
        exc = Exception("Bad Request")
        big_msgs = [{"role": "user", "content": "x" * 60_000}]
        assert client._is_likely_context_overflow(exc, big_msgs) is True

    def test_small_payload_not_overflow(self):
        client = _HeaderInjectingClient()
        exc = Exception("Bad Request")
        small_msgs = [{"role": "user", "content": "hi"}]
        assert client._is_likely_context_overflow(exc, small_msgs) is False


class TestLogCachingStatus:
    """_log_caching_status edge cases."""

    def test_non_anthropic_model_returns_early(self):
        client = _HeaderInjectingClient()
        # Should not raise, just return early
        client._log_caching_status("gpt-4", [], {})

    def test_anthropic_with_cache_active(self):
        client = _HeaderInjectingClient()
        msgs = [{"role": "system", "content": [
            {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
        ]}]
        kwargs = {"extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}}
        # Should not raise
        client._log_caching_status("anthropic/claude-3", msgs, kwargs)

    def test_non_string_model_skipped(self):
        client = _HeaderInjectingClient()
        client._log_caching_status(None, [], {})
        client._log_caching_status(123, [], {})


# ===========================================================================
# make_agent negative tests (via agent/__init__.py)
# ===========================================================================

from agent import make_agent  # noqa: E402


class TestMakeAgentEdgeCases:
    """make_agent with various edge cases."""

    def test_empty_toolsets_list(self):
        agent = make_agent([])
        assert agent is not None

    def test_with_guide_appended_to_instruction(self):
        agent = make_agent([], guide="Custom guide text")
        # Agent is a MagicMock from conftest stubs, but make_agent should not crash
        assert agent is not None

    def test_with_none_remote_agent_tools(self):
        agent = make_agent([], remote_agent_tools=None)
        assert agent is not None

    def test_with_empty_remote_agent_tools(self):
        agent = make_agent([], remote_agent_tools=[])
        assert agent is not None

    def test_with_mcp_pool(self):
        mock_pool = MagicMock()
        mock_pool.call_prompt = AsyncMock(return_value="prompt result")
        agent = make_agent([], mcp_pool=mock_pool)
        assert agent is not None

    def test_with_all_optional_params(self):
        mock_pool = MagicMock()
        mock_pool.call_prompt = AsyncMock(return_value="result")
        remote_tools = [MagicMock()]
        agent = make_agent(
            [MagicMock()],
            guide="full guide",
            mcp_pool=mock_pool,
            remote_agent_tools=remote_tools,
        )
        assert agent is not None

    def test_with_minimal_params(self):
        agent = make_agent([])
        assert agent is not None
