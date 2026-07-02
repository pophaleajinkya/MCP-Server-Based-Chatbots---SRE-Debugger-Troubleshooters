"""Unit tests for agent.a2ui — A2UI integration for structured UI responses.

NOTE: The a2ui package may not be installed in the test environment,
so all a2ui imports are stubbed before importing the module under test.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Stub a2ui package before importing the module under test — only when the
# real a2ui package is NOT installed to avoid corrupting sys.modules.
# ---------------------------------------------------------------------------

# Create a real-ish ResponsePart class for tests
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
        """Install lightweight stubs for all a2ui sub-packages/modules."""
        _a2ui_modules = [
            "a2ui",
            "a2ui.basic_catalog",
            "a2ui.basic_catalog.provider",
            "a2ui.core",
            "a2ui.core.parser",
            "a2ui.core.parser.parser",
            "a2ui.core.parser.response_part",
            "a2ui.core.schema",
            "a2ui.core.schema.constants",
            "a2ui.core.schema.manager",
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

    # Install stubs
    _ensure_a2ui_stubs()

    # Populate stub attributes
    sys.modules["a2ui.basic_catalog.provider"].BasicCatalog = MagicMock()
    sys.modules["a2ui.core.parser.parser"].has_a2ui_parts = MagicMock(return_value=False)
    sys.modules["a2ui.core.parser.parser"].parse_response = MagicMock(return_value=[])
    sys.modules["a2ui.core.parser.response_part"].ResponsePart = _StubResponsePart
    sys.modules["a2ui.core.schema.constants"].VERSION_0_9 = "0.9"
    sys.modules["a2ui.core.schema.manager"].A2uiSchemaManager = MagicMock


# Now import the module under test
import agent.a2ui as a2ui_mod  # noqa: E402


# ---------------------------------------------------------------------------
# TestGetSchemaManager
# ---------------------------------------------------------------------------

class TestGetSchemaManager:
    """Tests for _get_schema_manager() — singleton pattern."""

    def test_returns_instance(self):
        """_get_schema_manager should return an A2uiSchemaManager instance."""
        # Reset singleton
        a2ui_mod._schema_manager = None
        mgr = a2ui_mod._get_schema_manager()
        assert mgr is not None

    def test_returns_same_instance_on_second_call(self):
        """_get_schema_manager should return the same object on subsequent calls."""
        a2ui_mod._schema_manager = None
        first = a2ui_mod._get_schema_manager()
        second = a2ui_mod._get_schema_manager()
        assert first is second


# ---------------------------------------------------------------------------
# TestGenerateA2uiInstruction
# ---------------------------------------------------------------------------

class TestGenerateA2uiInstruction:
    """Tests for generate_a2ui_instruction()."""

    def test_file_exists_returns_content(self, tmp_path):
        """When the patterns file exists, its content is returned."""
        patterns = "# A2UI Patterns\n\nUse Table for tabular data."
        fake_file = tmp_path / "A2UI_PATTERNS.md"
        fake_file.write_text(patterns, encoding="utf-8")

        with patch.object(a2ui_mod, "_A2UI_PATTERNS_FILE", fake_file):
            result = a2ui_mod.generate_a2ui_instruction()

        assert result == patterns.strip()

    def test_file_missing_returns_empty_string(self, tmp_path):
        """When the patterns file does not exist, return empty string."""
        missing = tmp_path / "nonexistent.md"

        with patch.object(a2ui_mod, "_A2UI_PATTERNS_FILE", missing):
            result = a2ui_mod.generate_a2ui_instruction()

        assert result == ""


# ---------------------------------------------------------------------------
# TestValidateA2uiResponse
# ---------------------------------------------------------------------------

class TestValidateA2uiResponse:
    """Tests for validate_a2ui_response()."""

    def test_plain_text_no_a2ui_returns_single_part(self):
        """Plain text without A2UI tags returns a single ResponsePart with text."""
        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=False):
            parts = a2ui_mod.validate_a2ui_response("Hello, world!")

        assert len(parts) == 1
        assert parts[0].text == "Hello, world!"
        assert parts[0].a2ui_json is None

    def test_text_with_valid_a2ui_blocks_returns_parsed_parts(self):
        """Text with A2UI blocks returns parsed and validated parts."""
        text_part = _StubResponsePart(text="Here is a table:")
        a2ui_part = _StubResponsePart(text="", a2ui_json={"type": "Table", "columns": ["A"]})

        # Mock the schema manager chain
        mock_validator = MagicMock()
        mock_catalog = MagicMock()
        mock_catalog.validator = mock_validator
        mock_mgr = MagicMock()
        mock_mgr.get_selected_catalog.return_value = mock_catalog

        a2ui_mod._schema_manager = None  # reset singleton

        with patch.object(a2ui_mod, "has_a2ui_parts", return_value=True), \
             patch.object(a2ui_mod, "parse_response", return_value=[text_part, a2ui_part]), \
             patch.object(a2ui_mod, "_get_schema_manager", return_value=mock_mgr):
            parts = a2ui_mod.validate_a2ui_response("Here is a table:\n<a2ui>...</a2ui>")

        assert len(parts) == 2
        assert parts[0].text == "Here is a table:"
        assert parts[1].a2ui_json == {"type": "Table", "columns": ["A"]}
        mock_validator.validate.assert_called_once_with({"type": "Table", "columns": ["A"]})


# ---------------------------------------------------------------------------
# TestTryValidateA2uiResponse
# ---------------------------------------------------------------------------

class TestTryValidateA2uiResponse:
    """Tests for try_validate_a2ui_response() — graceful degradation wrapper."""

    def test_valid_input_returns_parts_and_none_error(self):
        """On valid input, returns (parts, None)."""
        expected_parts = [_StubResponsePart(text="OK")]

        with patch.object(a2ui_mod, "validate_a2ui_response", return_value=expected_parts):
            parts, error = a2ui_mod.try_validate_a2ui_response("OK")

        assert parts == expected_parts
        assert error is None

    def test_invalid_a2ui_returns_fallback_and_error_string(self):
        """On validation failure, returns fallback plain-text part and error string."""
        with patch.object(
            a2ui_mod,
            "validate_a2ui_response",
            side_effect=ValueError("Invalid A2UI: unknown component 'Foo'"),
        ):
            parts, error = a2ui_mod.try_validate_a2ui_response("bad <a2ui>stuff</a2ui>")

        assert len(parts) == 1
        assert parts[0].text == "bad <a2ui>stuff</a2ui>"
        assert parts[0].a2ui_json is None
        assert "Invalid A2UI" in error
        assert "Foo" in error

    def test_generic_exception_returns_fallback(self):
        """Any exception (not just ValueError) is caught and returned as error."""
        with patch.object(
            a2ui_mod,
            "validate_a2ui_response",
            side_effect=RuntimeError("unexpected"),
        ):
            parts, error = a2ui_mod.try_validate_a2ui_response("some text")

        assert len(parts) == 1
        assert parts[0].text == "some text"
        assert "unexpected" in error
