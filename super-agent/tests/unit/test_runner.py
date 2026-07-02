"""Unit tests for app.services.runner — ADK runner helper."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# Stub google.genai only when the real package is not installed.
# When the real package IS present (as in the current venv) we must not
# overwrite sys.modules — doing so corrupts google.adk imports for every
# test that runs after this file is collected.
try:
    import google.genai as _real_genai  # noqa: F401
except ImportError:
    mock_genai = ModuleType("google.genai")
    sys.modules.setdefault("google", ModuleType("google"))
    sys.modules.setdefault("google.genai", mock_genai)
    sys.modules.setdefault("google.genai.some_submodule", MagicMock())
    sys.modules.setdefault("google.genai.types", MagicMock())


def _make_runner_with_final_response(text: str):
    """Build a mock Runner that produces one final-response event."""
    mock_part = MagicMock()
    mock_part.text = text

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content = mock_content

    async def _run_async(**kwargs):
        yield mock_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _make_runner_with_no_final_response():
    """Build a mock Runner that produces an event that is NOT a final response."""
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = False
    mock_event.content = None

    async def _run_async(**kwargs):
        yield mock_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _make_runner_with_no_events():
    """Build a mock Runner that yields no events."""
    async def _run_async(**kwargs):
        if False:
            yield  # make it an async generator

    runner = MagicMock()
    runner.run_async = _run_async
    # Fix: session_service methods must be AsyncMock for await
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _make_runner_with_empty_content():
    """Build a mock Runner whose event has content but no parts."""
    mock_content = MagicMock()
    mock_content.parts = []

    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content = mock_content

    async def _run_async(**kwargs):
        yield mock_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _make_runner_with_multiple_parts(texts: list):
    """Build a mock Runner whose final-response event has multiple text parts."""
    parts = []
    for t in texts:
        p = MagicMock()
        p.text = t
        parts.append(p)

    mock_content = MagicMock()
    mock_content.parts = parts

    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content = mock_content

    async def _run_async(**kwargs):
        yield mock_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _make_runner_with_none_content():
    """Build a mock Runner whose final-response event has content=None."""
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content = None

    async def _run_async(**kwargs):
        yield mock_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner


def _make_runner_non_final_then_final(text: str):
    """Build a mock Runner that yields a non-final event, then a final event."""
    non_final = MagicMock()
    non_final.is_final_response.return_value = False
    non_final.content = None

    mock_part = MagicMock()
    mock_part.text = text

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    final_event = MagicMock()
    final_event.is_final_response.return_value = True
    final_event.content = mock_content

    async def _run_async(**kwargs):
        yield non_final
        yield final_event

    runner = MagicMock()
    runner.run_async = _run_async
    runner.session_service = MagicMock()
    runner.session_service.get_session = AsyncMock(return_value=None)
    runner.session_service.create_session = AsyncMock()
    return runner



class TestRunAgent:
    """Tests for the run_agent() helper function."""

    @pytest.mark.asyncio
    async def test_returns_final_response_text(self):
        """run_agent should return the answer text (tuple first element)."""
        from app.services.runner import run_agent
        runner = _make_runner_with_final_response("Namespace is healthy.")
        answer = await run_agent(runner, "admin", "session-1", "Check health")
        assert answer == "Namespace is healthy."

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_events(self):
        """run_agent should return '' when runner yields no events."""
        from app.services.runner import run_agent
        runner = _make_runner_with_no_events()
        answer = await run_agent(runner, "admin", "session-1", "query")
        assert answer == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_final_response(self):
        """run_agent should return '' when no final response event."""
        from app.services.runner import run_agent
        runner = _make_runner_with_no_final_response()
        answer = await run_agent(runner, "admin", "session-1", "query")
        assert answer == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_content_is_none(self):
        """run_agent should return '' when event.content is None."""
        from app.services.runner import run_agent
        runner = _make_runner_with_none_content()
        answer = await run_agent(runner, "admin", "session-1", "query")
        assert answer == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_parts_empty(self):
        """run_agent should return '' when content.parts is empty."""
        from app.services.runner import run_agent
        runner = _make_runner_with_empty_content()
        answer = await run_agent(runner, "admin", "session-1", "query")
        assert answer == ""

    @pytest.mark.asyncio
    async def test_concatenates_multiple_parts(self):
        """run_agent should join multiple text parts with newlines."""
        from app.services.runner import run_agent
        runner = _make_runner_with_multiple_parts(["Part one", "Part two", "Part three"])
        answer = await run_agent(runner, "admin", "session-1", "query")
        assert answer == "Part one\nPart two\nPart three"

    @pytest.mark.asyncio
    async def test_skips_non_final_events(self):
        """run_agent should skip non-final events and use the final one."""
        from app.services.runner import run_agent
        runner = _make_runner_non_final_then_final("Final answer here.")
        answer = await run_agent(runner, "admin", "session-1", "query")
        assert answer == "Final answer here."

    @pytest.mark.asyncio
    async def test_passes_session_id_to_runner(self):
        """run_agent should pass the session_id to runner.run_async."""
        from app.services.runner import run_agent

        captured_kwargs = {}

        mock_part = MagicMock()
        mock_part.text = "answer"
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = mock_content

        async def _run_async(**kwargs):
            captured_kwargs.update(kwargs)
            yield mock_event

        runner = MagicMock()
        runner.run_async = _run_async
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        await run_agent(runner, "admin", "my-session-42", "query")
        assert captured_kwargs.get("session_id") == "my-session-42"

    @pytest.mark.asyncio
    async def test_passes_user_id_to_runner(self):
        """run_agent should pass the supplied user_id to runner.run_async."""
        from app.services.runner import run_agent

        captured_kwargs = {}

        mock_part = MagicMock()
        mock_part.text = "answer"
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = mock_content

        async def _run_async(**kwargs):
            captured_kwargs.update(kwargs)
            yield mock_event

        runner = MagicMock()
        runner.run_async = _run_async
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        await run_agent(runner, "admin", "session-x", "query text")
        assert captured_kwargs.get("user_id") == "admin"

    @pytest.mark.asyncio
    async def test_skips_parts_without_text_attribute(self):
        """run_agent should skip parts that have no .text attribute or empty text."""
        from app.services.runner import run_agent

        part_with_text = MagicMock()
        part_with_text.text = "Real answer"

        part_empty_text = MagicMock()
        part_empty_text.text = ""  # falsy text → skip

        mock_content = MagicMock()
        mock_content.parts = [part_with_text, part_empty_text]

        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = mock_content

        async def _run_async(**kwargs):
            yield mock_event

        runner = MagicMock()
        runner.run_async = _run_async
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        answer = await run_agent(runner, "admin", "s", "q")
        assert answer == "Real answer"

    @pytest.mark.asyncio
    async def test_returns_after_first_final_response(self):
        """run_agent returns after the FIRST final response event (doesn't continue)."""
        from app.services.runner import run_agent

        def _make_part(text):
            p = MagicMock()
            p.text = text
            return p

        def _make_final_event(text):
            c = MagicMock()
            c.parts = [_make_part(text)]
            e = MagicMock()
            e.is_final_response.return_value = True
            e.content = c
            return e

        async def _run_async(**kwargs):
            yield _make_final_event("First final")
            yield _make_final_event("Second final")  # should never be reached

        runner = MagicMock()
        runner.run_async = _run_async
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        answer = await run_agent(runner, "admin", "s", "q")
        assert answer == "First final"

    @pytest.mark.asyncio
    async def test_different_queries_produce_different_results(self):
        """Different queries should be handled independently."""
        from app.services.runner import run_agent

        answers = {"check health": "all healthy", "get metrics": "uptime 99.9%"}

        async def _run_async(**kwargs):
            text = answers.get(kwargs.get("new_message", {}).text if hasattr(kwargs.get("new_message", {}), "text") else "check health", "default")
            p = MagicMock()
            p.text = text
            c = MagicMock()
            c.parts = [p]
            e = MagicMock()
            e.is_final_response.return_value = True
            e.content = c
            yield e

        runner = MagicMock()
        runner.run_async = _run_async
        runner.session_service = MagicMock()
        runner.session_service.get_session = AsyncMock(return_value=None)
        runner.session_service.create_session = AsyncMock()
        # Both calls should succeed without interference
        answer1 = await run_agent(runner, "admin", "s1", "check health")
        answer2 = await run_agent(runner, "admin", "s2", "get metrics")
        assert isinstance(answer1, str)
        assert isinstance(answer2, str)
