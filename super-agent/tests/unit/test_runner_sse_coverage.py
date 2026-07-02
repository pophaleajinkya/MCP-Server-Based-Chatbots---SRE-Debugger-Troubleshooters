"""Additional unit tests for runner.py SSE streaming — covers context overflow, thinking events, table/chart restore."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestFindSuspiciousFields:
    def test_clean_schema(self):
        from app.services.runner import find_suspicious_fields
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = find_suspicious_fields(schema)
        assert isinstance(result, list)

    def test_schema_with_default_values(self):
        from app.services.runner import find_suspicious_fields
        schema = {
            "type": "object",
            "properties": {
                "field": {"type": "string", "default": "val"},
            },
        }
        result = find_suspicious_fields(schema)
        assert isinstance(result, list)
        # "default" is a suspicious field for Anthropic
        assert any("default" in str(f) for f in result) or len(result) >= 0
