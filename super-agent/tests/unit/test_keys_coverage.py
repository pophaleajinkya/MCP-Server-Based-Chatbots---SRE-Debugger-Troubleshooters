"""Additional unit tests for app.store.keys — covers key_ui_stream, key_llm_pending, key_idem_inject."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.store.keys import key_ui_stream, key_llm_pending, key_idem_inject


class TestKeyUiStream:
    def test_format(self):
        result = key_ui_stream("myapp", "user1", "session1")
        assert result == "agent:ui_stream:myapp:user1:session1"

    def test_with_special_chars(self):
        result = key_ui_stream("app", "user@corp.com", "sid-123")
        assert "user@corp.com" in result
        assert "sid-123" in result


class TestKeyLlmPending:
    def test_format(self):
        result = key_llm_pending("myapp", "user1", "session1")
        assert result == "agent:llm_pending:myapp:user1:session1"


class TestKeyIdemInject:
    def test_format(self):
        result = key_idem_inject("myapp", "user1", "session1", "lc:INC123:v1")
        assert result == "agent:idem_inject:myapp:user1:session1:lc:INC123:v1"

    def test_different_idem_keys(self):
        k1 = key_idem_inject("app", "u", "s", "key1")
        k2 = key_idem_inject("app", "u", "s", "key2")
        assert k1 != k2
