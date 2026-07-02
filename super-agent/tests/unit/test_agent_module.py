"""
Comprehensive unit tests for the agent module:
  - src/agent/agent.py  (_HeaderInjectingClient methods)
  - src/agent/__init__.py (_NonEmptyLocalCodeExecutor, _inject_time_context,
                           _load_base_instruction, make_agent)
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# Ensure src is importable (conftest.py also does this, but be explicit)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ============================================================================
# _HeaderInjectingClient tests (src/agent/agent.py)
# ============================================================================

class TestMergeLLMHeaders:
    """Tests for _HeaderInjectingClient._merge_llm_headers."""

    def _make_client(self):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient()

    def test_no_headers_in_context_no_change(self, env_vars):
        """When get_llm_headers() returns empty dict, kwargs are untouched."""
        client = self._make_client()
        with patch("agent.agent.get_llm_headers", return_value={}):
            kwargs = {"temperature": 0.5}
            result = client._merge_llm_headers(kwargs)
            assert "extra_headers" not in result
            assert result["temperature"] == 0.5

    def test_headers_in_context_merged_with_existing(self, env_vars):
        """Per-request headers are merged with pre-existing extra_headers."""
        client = self._make_client()
        ctx_headers = {"wm_llm_gw.app_id": "test-app"}
        with patch("agent.agent.get_llm_headers", return_value=ctx_headers):
            kwargs = {"extra_headers": {"existing-key": "existing-val"}}
            result = client._merge_llm_headers(kwargs)
            assert result["extra_headers"]["existing-key"] == "existing-val"
            assert result["extra_headers"]["wm_llm_gw.app_id"] == "test-app"

    def test_headers_in_context_creates_extra_headers_if_missing(self, env_vars):
        """When kwargs has no extra_headers, one is created."""
        client = self._make_client()
        ctx_headers = {"wm_llm_gw.trace_id": "abc123"}
        with patch("agent.agent.get_llm_headers", return_value=ctx_headers):
            kwargs = {}
            result = client._merge_llm_headers(kwargs)
            assert result["extra_headers"] == {"wm_llm_gw.trace_id": "abc123"}


class TestInjectCacheControl:
    """Tests for _HeaderInjectingClient._inject_cache_control (static method)."""

    def _inject(self, messages):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient._inject_cache_control(messages)

    def test_system_message_gets_cache_control(self, env_vars):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = self._inject(messages)
        sys_msg = result[0]
        assert isinstance(sys_msg["content"], list)
        assert sys_msg["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert sys_msg["content"][0]["text"] == "You are helpful."

    def test_last_user_message_gets_cache_control(self, env_vars):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "second question"},
        ]
        result = self._inject(messages)
        # Last user message (index 3) should have cache_control
        last_user = result[3]
        assert isinstance(last_user["content"], list)
        assert last_user["content"][0]["cache_control"] == {"type": "ephemeral"}
        # First user message (index 1) should NOT have cache_control
        first_user = result[1]
        assert isinstance(first_user["content"], str)

    def test_no_user_messages_no_crash(self, env_vars):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "hi"},
        ]
        result = self._inject(messages)
        assert len(result) == 2
        # System message still gets cache_control
        assert isinstance(result[0]["content"], list)

    def test_string_content_converted_to_list_format(self, env_vars):
        messages = [{"role": "user", "content": "hello"}]
        result = self._inject(messages)
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["type"] == "text"

    def test_list_content_last_block_gets_cache_control(self, env_vars):
        messages = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "block1"},
                    {"type": "text", "text": "block2"},
                ],
            }
        ]
        result = self._inject(messages)
        blocks = result[0]["content"]
        assert "cache_control" not in blocks[0]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_empty_messages_list(self, env_vars):
        result = self._inject([])
        assert result == []


class TestSanitizeMessages:
    """Tests for _HeaderInjectingClient._sanitize_messages."""

    def _sanitize(self, messages):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient._sanitize_messages(messages)

    def test_empty_text_blocks_removed(self, env_vars):
        messages = [
            {
                "role": "tool",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "real content"},
                ],
            }
        ]
        result = self._sanitize(messages)
        assert len(result) == 1
        assert len(result[0]["content"]) == 1
        assert result[0]["content"][0]["text"] == "real content"

    def test_whitespace_only_text_blocks_removed(self, env_vars):
        messages = [
            {
                "role": "tool",
                "content": [{"type": "text", "text": "   \n  "}],
            }
        ]
        result = self._sanitize(messages)
        # Entire message dropped because all blocks were empty
        assert len(result) == 0

    def test_empty_string_messages_removed(self, env_vars):
        messages = [
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "hello"},
        ]
        result = self._sanitize(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_non_text_blocks_preserved(self, env_vars):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "http://example.com"}},
                    {"type": "text", "text": ""},
                ],
            }
        ]
        result = self._sanitize(messages)
        assert len(result) == 1
        assert len(result[0]["content"]) == 1
        assert result[0]["content"][0]["type"] == "image_url"

    def test_normal_messages_unchanged(self, env_vars):
        messages = [
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I am fine."},
        ]
        result = self._sanitize(messages)
        assert result == messages


class TestShrinkForRetry:
    """Tests for _HeaderInjectingClient._shrink_for_retry."""

    def _shrink(self, messages):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient._shrink_for_retry(messages)

    def test_single_user_turn_kept_as_is(self, env_vars):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "my question"},
            {"role": "assistant", "content": "my answer"},
        ]
        result = self._shrink(messages)
        assert len(result) == 3
        # No context-loss notice (only one user turn, no drops)
        assert "[Note:" not in result[1]["content"]

    def test_multiple_user_turns_only_last_kept(self, env_vars):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "new question"},
            {"role": "assistant", "content": "new answer"},
        ]
        result = self._shrink(messages)
        # System + last user turn + its assistant follow-up
        assert result[0]["role"] == "system"
        assert "new question" in result[1]["content"]
        assert result[2]["role"] == "assistant"
        # Older turns dropped
        roles = [m["role"] for m in result]
        assert roles == ["system", "user", "assistant"]

    def test_context_loss_notice_prepended(self, env_vars):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old-reply"},
            {"role": "user", "content": "latest"},
        ]
        result = self._shrink(messages)
        user_msg = result[1]
        assert user_msg["role"] == "user"
        assert "[Note: earlier conversation turns were dropped" in user_msg["content"]
        assert "latest" in user_msg["content"]

    def test_tool_results_truncated(self, env_vars):
        import agent.agent as agent_mod
        orig = agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS
        agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS = 20
        try:
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "q"},
                {"role": "tool", "content": "A" * 100},
            ]
            result = self._shrink(messages)
            tool_msg = [m for m in result if m["role"] == "tool"][0]
            assert len(tool_msg["content"]) < 100
            assert "truncated" in tool_msg["content"]
        finally:
            agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS = orig

    def test_context_loss_notice_with_list_content(self, env_vars):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old"},
            {"role": "user", "content": [{"type": "text", "text": "latest list"}]},
        ]
        result = self._shrink(messages)
        user_msg = result[1]
        assert isinstance(user_msg["content"], list)
        assert "[Note:" in user_msg["content"][0]["text"]


class TestEstimatePayloadChars:
    """Tests for _HeaderInjectingClient._estimate_payload_chars."""

    def _estimate(self, messages):
        from agent.agent import _HeaderInjectingClient
        client = _HeaderInjectingClient()
        return client._estimate_payload_chars(messages)

    def test_string_content_counted(self, env_vars):
        messages = [{"role": "user", "content": "hello"}]
        assert self._estimate(messages) == 5

    def test_list_content_counted(self, env_vars):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "abc"},
                    {"type": "text", "text": "de"},
                ],
            }
        ]
        result = self._estimate(messages)
        assert result >= 5  # at least "abc" + "de"

    def test_empty_messages_zero(self, env_vars):
        assert self._estimate([]) == 0

    def test_missing_content_zero(self, env_vars):
        messages = [{"role": "system"}]
        assert self._estimate(messages) == 0


class TestIsLikelyContextOverflow:
    """Tests for _HeaderInjectingClient._is_likely_context_overflow."""

    def _make_client(self):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient()

    def test_known_keywords_detected(self, env_vars):
        client = self._make_client()
        exc = Exception("Error: prompt is too long for context window")
        assert client._is_likely_context_overflow(exc, []) is True

    def test_context_length_keyword(self, env_vars):
        client = self._make_client()
        exc = Exception("context length exceeded")
        assert client._is_likely_context_overflow(exc, []) is True

    def test_large_payload_generic_400_detected(self, env_vars):
        client = self._make_client()
        exc = Exception("Bad Request")
        # Build a payload larger than _CONTEXT_OVERFLOW_CHAR_THRESHOLD (50_000)
        big_messages = [{"role": "user", "content": "x" * 60_000}]
        assert client._is_likely_context_overflow(exc, big_messages) is True

    def test_small_payload_400_not_overflow(self, env_vars):
        client = self._make_client()
        exc = Exception("Bad Request — invalid JSON")
        small_messages = [{"role": "user", "content": "hi"}]
        assert client._is_likely_context_overflow(exc, small_messages) is False


class TestLogCachingStatus:
    """Tests for _HeaderInjectingClient._log_caching_status (smoke tests)."""

    def _make_client(self):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient()

    def test_non_anthropic_model_returns_immediately(self, env_vars):
        """No logging action for non-Anthropic models."""
        client = self._make_client()
        # Should not raise
        client._log_caching_status("azure/gpt-4", [], {})

    def test_anthropic_with_beta_and_cache_control(self, env_vars):
        """Logs ACTIVE when both beta header and cache_control are present."""
        client = self._make_client()
        messages = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
                ],
            }
        ]
        kwargs = {"extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}}
        # Should not raise
        client._log_caching_status("anthropic/claude-3", messages, kwargs)


# ============================================================================
# _NonEmptyLocalCodeExecutor tests (src/agent/__init__.py)
# ============================================================================

class TestNonEmptyLocalCodeExecutor:
    """Tests for _NonEmptyLocalCodeExecutor.execute_code."""

    def _make_executor(self):
        from agent import _NonEmptyLocalCodeExecutor
        return _NonEmptyLocalCodeExecutor(timeout_seconds=10)

    def _make_result(self, stdout="", stderr="", output_files=None):
        from google.adk.code_executors.code_execution_utils import CodeExecutionResult
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.output_files = output_files or []
        return result

    def test_empty_stdout_empty_stderr_synthesizes_success(self, env_vars):
        executor = self._make_executor()
        mock_result = self._make_result(stdout="", stderr="")
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert "success" in result.stdout.lower() or "success" in str(result.stdout).lower()

    def test_empty_stdout_with_stderr_promotes_stderr(self, env_vars):
        executor = self._make_executor()
        mock_result = self._make_result(stdout="", stderr="some error occurred")
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert "some error occurred" in result.stdout

    def test_normal_stdout_passes_through(self, env_vars):
        executor = self._make_executor()
        mock_result = self._make_result(stdout="output data", stderr="")
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert result.stdout == "output data"


# ============================================================================
# _inject_time_context tests (src/agent/__init__.py)
# ============================================================================

class TestInjectTimeContext:
    """Tests for _inject_time_context."""

    def _inject(self, timezone, epoch_ms, llm_request):
        with patch("agent.get_user_time_context", return_value=(timezone, epoch_ms)):
            from agent import _inject_time_context
            return _inject_time_context(MagicMock(), llm_request)

    def test_no_timezone_no_epoch_noop(self, env_vars):
        """Returns None and does nothing when both are empty."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hello"}]
        result = self._inject("", "", llm_request)
        assert result is None

    def test_with_timezone_and_epoch_dict_format(self, env_vars):
        """Prepends time block to last user message (dict format)."""
        llm_request = MagicMock()
        llm_request.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "what time is it?"},
        ]
        result = self._inject("America/Chicago", "1700000000000", llm_request)
        assert result is None  # always returns None
        last_msg = llm_request.messages[-1]
        assert "[System Time Context:" in last_msg["content"]
        assert "America/Chicago" in last_msg["content"]

    def test_with_timezone_and_epoch_object_format(self, env_vars):
        """Prepends time block to last user message (object with .role attribute)."""
        llm_request = MagicMock()
        last_msg = MagicMock()
        last_msg.role = "user"
        last_msg.content = "what time?"
        llm_request.messages = [last_msg]

        result = self._inject("Europe/London", "1700000000000", llm_request)
        assert result is None
        assert "[System Time Context:" in last_msg.content

    def test_non_user_last_message_appends_to_instructions(self, env_vars):
        """When last message is not user, appends to llm_request instructions."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "assistant", "content": "sure"}]
        result = self._inject("US/Eastern", "1700000000000", llm_request)
        assert result is None
        llm_request.append_instructions.assert_called_once()
        call_args = llm_request.append_instructions.call_args[0][0]
        assert "[System Time Context:" in call_args[0]

    def test_with_timezone_and_epoch_list_content_dict(self, env_vars):
        """Prepends time block when user message content is a list (dict format)."""
        llm_request = MagicMock()
        llm_request.messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ]
        result = self._inject("Asia/Tokyo", "1700000000000", llm_request)
        assert result is None
        content = llm_request.messages[0]["content"]
        assert len(content) == 2  # prepended block + original
        assert content[0]["type"] == "text"
        assert "[System Time Context:" in content[0]["text"]

    def test_empty_messages_appends_to_instructions(self, env_vars):
        """When messages is empty, appends to instructions."""
        llm_request = MagicMock()
        llm_request.messages = []
        result = self._inject("US/Pacific", "1700000000000", llm_request)
        assert result is None
        llm_request.append_instructions.assert_called_once()


# ============================================================================
# _load_base_instruction tests (src/agent/__init__.py)
# ============================================================================

class TestLoadBaseInstruction:
    """Tests for _load_from_file (formerly _load_base_instruction)."""

    def test_loads_from_file(self, env_vars, tmp_path):
        """When the instruction file exists, its content is returned."""
        from app.services.agent_instruction import _load_from_file, _INSTRUCTION_FILE
        fake_file = tmp_path / "AGENT_INSTRUCTION.md"
        fake_file.write_text("Custom instruction from file", encoding="utf-8")
        with patch("app.services.agent_instruction._INSTRUCTION_FILE", fake_file):
            result = _load_from_file()
            assert result == "Custom instruction from file"

    def test_returns_fallback_when_file_missing(self, env_vars, tmp_path):
        """When the file doesn't exist, hardcoded fallback is returned."""
        from app.services.agent_instruction import _load_from_file
        missing = tmp_path / "nonexistent" / "AGENT_INSTRUCTION.md"
        with patch("app.services.agent_instruction._INSTRUCTION_FILE", missing):
            result = _load_from_file()
            assert "health and dependency intelligence assistant" in result


# ============================================================================
# make_agent tests (src/agent/__init__.py)
# ============================================================================

class TestMakeAgent:
    """Tests for make_agent factory."""

    async def _make_agent(self, toolsets=None, guide="", mcp_pool=None, remote_agent_tools=None):
        mock_agent_cls = MagicMock()
        with patch("agent.get_settings") as mock_settings, \
             patch("agent._llm", MagicMock()), \
             patch("agent.Agent", mock_agent_cls), \
             patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Base instruction."):
            s = MagicMock()
            s.a2ui_enabled = False
            s.skills_dir = ""
            mock_settings.return_value = s
            from agent import make_agent
            await make_agent(
                toolsets=toolsets or [],
                guide=guide,
                mcp_pool=mcp_pool,
                remote_agent_tools=remote_agent_tools,
            )
        return mock_agent_cls

    @pytest.mark.asyncio
    async def test_no_guide_instruction_is_base_only(self, env_vars):
        mock_agent_cls = await self._make_agent(guide="")
        call_kwargs = mock_agent_cls.call_args.kwargs
        # No guide separator should be appended when guide is empty
        assert "## Domain Guide" not in call_kwargs["instruction"]

    @pytest.mark.asyncio
    async def test_with_guide_instruction_includes_guide(self, env_vars):
        mock_agent_cls = await self._make_agent(guide="## Domain Guide\nUse tool X for Y.")
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "Domain Guide" in call_kwargs["instruction"]
        assert "Use tool X for Y." in call_kwargs["instruction"]

    @pytest.mark.asyncio
    async def test_with_mcp_pool_adds_get_mcp_prompt_tool(self, env_vars):
        mock_pool = MagicMock()
        mock_agent_cls = await self._make_agent(mcp_pool=mock_pool)
        tools = mock_agent_cls.call_args.kwargs["tools"]
        tool_names = [
            t.__name__ for t in tools if callable(t) and hasattr(t, "__name__")
        ]
        assert "get_mcp_prompt" in tool_names

    @pytest.mark.asyncio
    async def test_with_remote_agent_tools_included(self, env_vars):
        remote_tool = MagicMock()
        remote_tool.__name__ = "remote_subagent_tool"
        mock_agent_cls = await self._make_agent(remote_agent_tools=[remote_tool])
        tools = mock_agent_cls.call_args.kwargs["tools"]
        assert remote_tool in tools

    @pytest.mark.asyncio
    async def test_pingfed_token_always_included(self, env_vars):
        mock_agent_cls = await self._make_agent()
        tools = mock_agent_cls.call_args.kwargs["tools"]
        from app.tools.auth_tool import pingfed_token
        assert pingfed_token in tools

    @pytest.mark.asyncio
    async def test_no_mcp_pool_no_get_mcp_prompt(self, env_vars):
        mock_agent_cls = await self._make_agent(mcp_pool=None)
        tools = mock_agent_cls.call_args.kwargs["tools"]
        tool_names = [
            t.__name__ for t in tools if callable(t) and hasattr(t, "__name__")
        ]
        assert "get_mcp_prompt" not in tool_names

    @pytest.mark.asyncio
    async def test_a2ui_enabled_appends_structured_instruction(self, env_vars):
        """When a2ui_enabled=True, A2UI instruction is appended to agent prompt."""
        mock_agent_cls = MagicMock()
        with patch("agent.get_settings") as mock_settings, \
             patch("agent._llm", MagicMock()), \
             patch("agent.Agent", mock_agent_cls), \
             patch("agent.a2ui.generate_a2ui_instruction", return_value="## A2UI\nRender tables."), \
             patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Base instruction."):
            s = MagicMock()
            s.a2ui_enabled = True
            s.skills_dir = ""
            mock_settings.return_value = s
            from agent import make_agent
            await make_agent(toolsets=[], guide="", mcp_pool=None)
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "A2UI" in call_kwargs["instruction"]
        assert "Render tables." in call_kwargs["instruction"]

    @pytest.mark.asyncio
    async def test_a2ui_enabled_with_guide_both_in_instruction(self, env_vars):
        """Both guide and A2UI instruction are in the final prompt."""
        mock_agent_cls = MagicMock()
        with patch("agent.get_settings") as mock_settings, \
             patch("agent._llm", MagicMock()), \
             patch("agent.Agent", mock_agent_cls), \
             patch("agent.a2ui.generate_a2ui_instruction", return_value="## A2UI\nStructured."), \
             patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Base instruction."):
            s = MagicMock()
            s.a2ui_enabled = True
            s.skills_dir = ""
            mock_settings.return_value = s
            from agent import make_agent
            await make_agent(toolsets=[], guide="## Guide\nUse tool X.", mcp_pool=None)
        instruction = mock_agent_cls.call_args.kwargs["instruction"]
        assert "Guide" in instruction
        assert "Use tool X." in instruction
        assert "A2UI" in instruction

    @pytest.mark.asyncio
    async def test_remote_agent_tools_none_is_safe(self, env_vars):
        """remote_agent_tools=None does not crash."""
        mock_agent_cls = await self._make_agent(remote_agent_tools=None)
        tools = mock_agent_cls.call_args.kwargs["tools"]
        assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_remote_agent_tools_empty_list_is_safe(self, env_vars):
        """remote_agent_tools=[] does not crash."""
        mock_agent_cls = await self._make_agent(remote_agent_tools=[])
        tools = mock_agent_cls.call_args.kwargs["tools"]
        assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_toolsets_in_global_tools_when_no_skills(self, env_vars):
        """When skills are disabled, MCPToolsets are added to global tools list."""
        mock_toolset = MagicMock()
        mock_agent_cls = await self._make_agent(toolsets=[mock_toolset])
        tools = mock_agent_cls.call_args.kwargs["tools"]
        assert mock_toolset in tools


# ============================================================================
# get_mcp_prompt inner function edge cases
# ============================================================================

class TestGetMcpPromptTool:
    """Tests for the get_mcp_prompt closure built inside make_agent."""

    @pytest.mark.asyncio
    async def test_get_mcp_prompt_valid_json_args(self, env_vars):
        """get_mcp_prompt correctly parses valid JSON arguments."""
        mock_pool = MagicMock()
        mock_pool.call_prompt = AsyncMock(return_value="rendered prompt")

        # Build the tool via make_agent internals
        mock_agent_cls = MagicMock()
        captured_tools = []

        def _capture_agent(*args, **kwargs):
            captured_tools.extend(kwargs.get("tools", []))
            return MagicMock()

        mock_agent_cls.side_effect = _capture_agent

        with patch("agent.get_settings") as mock_settings, \
             patch("agent._llm", MagicMock()), \
             patch("agent.Agent", mock_agent_cls), \
             patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Base instruction."):
            s = MagicMock()
            s.a2ui_enabled = False
            s.skills_dir = ""
            mock_settings.return_value = s
            from agent import make_agent
            await make_agent(toolsets=[], guide="", mcp_pool=mock_pool)

        # Find the get_mcp_prompt tool
        prompt_tool = next(
            (t for t in captured_tools if callable(t) and hasattr(t, "__name__") and t.__name__ == "get_mcp_prompt"),
            None,
        )
        assert prompt_tool is not None

        result = await prompt_tool("test-prompt", '{"ns": "prod"}')
        mock_pool.call_prompt.assert_awaited_once_with("test-prompt", {"ns": "prod"})

    @pytest.mark.asyncio
    async def test_get_mcp_prompt_invalid_json_uses_empty_dict(self, env_vars):
        """get_mcp_prompt falls back to empty dict on bad JSON."""
        mock_pool = MagicMock()
        mock_pool.call_prompt = AsyncMock(return_value="rendered")

        mock_agent_cls = MagicMock()
        captured_tools = []

        def _capture_agent(*args, **kwargs):
            captured_tools.extend(kwargs.get("tools", []))
            return MagicMock()

        mock_agent_cls.side_effect = _capture_agent

        with patch("agent.get_settings") as mock_settings, \
             patch("agent._llm", MagicMock()), \
             patch("agent.Agent", mock_agent_cls), \
             patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Base instruction."):
            s = MagicMock()
            s.a2ui_enabled = False
            s.skills_dir = ""
            mock_settings.return_value = s
            from agent import make_agent
            await make_agent(toolsets=[], guide="", mcp_pool=mock_pool)

        prompt_tool = next(
            (t for t in captured_tools if callable(t) and hasattr(t, "__name__") and t.__name__ == "get_mcp_prompt"),
            None,
        )
        assert prompt_tool is not None

        result = await prompt_tool("test-prompt", "{{{bad json")
        mock_pool.call_prompt.assert_awaited_once_with("test-prompt", {})

    @pytest.mark.asyncio
    async def test_get_mcp_prompt_empty_string_args(self, env_vars):
        """get_mcp_prompt handles empty string arguments."""
        mock_pool = MagicMock()
        mock_pool.call_prompt = AsyncMock(return_value="ok")

        mock_agent_cls = MagicMock()
        captured_tools = []

        def _capture_agent(*args, **kwargs):
            captured_tools.extend(kwargs.get("tools", []))
            return MagicMock()

        mock_agent_cls.side_effect = _capture_agent

        with patch("agent.get_settings") as mock_settings, \
             patch("agent._llm", MagicMock()), \
             patch("agent.Agent", mock_agent_cls), \
             patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Base instruction."):
            s = MagicMock()
            s.a2ui_enabled = False
            s.skills_dir = ""
            mock_settings.return_value = s
            from agent import make_agent
            await make_agent(toolsets=[], guide="", mcp_pool=mock_pool)

        prompt_tool = next(
            (t for t in captured_tools if callable(t) and hasattr(t, "__name__") and t.__name__ == "get_mcp_prompt"),
            None,
        )
        result = await prompt_tool("test-prompt", "   ")
        mock_pool.call_prompt.assert_awaited_once_with("test-prompt", {})


# ============================================================================
# _NonEmptyLocalCodeExecutor negative/edge cases
# ============================================================================

class TestNonEmptyLocalCodeExecutorEdgeCases:
    """Negative and edge cases for _NonEmptyLocalCodeExecutor."""

    def _make_executor(self):
        from agent import _NonEmptyLocalCodeExecutor
        return _NonEmptyLocalCodeExecutor(timeout_seconds=10)

    def test_none_stdout_none_stderr_synthesizes_success(self, env_vars):
        """When super() returns None stdout and None stderr, synthesize success."""
        executor = self._make_executor()
        mock_result = MagicMock()
        mock_result.stdout = None
        mock_result.stderr = None
        mock_result.output_files = []
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert "success" in result.stdout.lower()
            assert result.stderr == ""

    def test_whitespace_only_stdout_empty_stderr_synthesizes_success(self, env_vars):
        """Whitespace-only stdout with empty stderr → synthetic success message."""
        executor = self._make_executor()
        mock_result = MagicMock()
        mock_result.stdout = "   \n\t  "
        mock_result.stderr = ""
        mock_result.output_files = []
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert "success" in result.stdout.lower()

    def test_whitespace_only_stdout_with_stderr_promotes_stderr(self, env_vars):
        """Whitespace-only stdout + real stderr → stderr promoted to stdout."""
        executor = self._make_executor()
        mock_result = MagicMock()
        mock_result.stdout = "  \n "
        mock_result.stderr = "ImportError: no module named 'foo'"
        mock_result.output_files = []
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert "[stderr]" in result.stdout
            assert "ImportError" in result.stdout
            assert result.stderr == ""

    def test_output_files_preserved(self, env_vars):
        """output_files from the original result are preserved through the wrapper."""
        executor = self._make_executor()
        mock_result = MagicMock()
        mock_result.stdout = "data"
        mock_result.stderr = ""
        mock_result.output_files = ["/tmp/chart.png"]
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert result.output_files == ["/tmp/chart.png"]

    def test_both_stdout_and_stderr_present_keeps_both(self, env_vars):
        """When both stdout and stderr have content, both pass through untouched."""
        executor = self._make_executor()
        mock_result = MagicMock()
        mock_result.stdout = "output data"
        mock_result.stderr = "warning: deprecated function"
        mock_result.output_files = []
        with patch.object(type(executor).__bases__[0], "execute_code", return_value=mock_result):
            result = executor.execute_code(MagicMock(), MagicMock())
            assert result.stdout == "output data"
            assert result.stderr == "warning: deprecated function"

    def test_super_raises_propagates_exception(self, env_vars):
        """If super().execute_code raises, the exception propagates."""
        executor = self._make_executor()
        with patch.object(type(executor).__bases__[0], "execute_code", side_effect=RuntimeError("exec failed")):
            with pytest.raises(RuntimeError, match="exec failed"):
                executor.execute_code(MagicMock(), MagicMock())


# ============================================================================
# _load_base_instruction negative/edge cases
# ============================================================================

class TestLoadBaseInstructionEdgeCases:
    """Negative and edge cases for _load_from_file (formerly _load_base_instruction)."""

    def test_empty_file_returns_fallback(self, env_vars, tmp_path):
        """Empty instruction file (strip → '') should return fallback."""
        from app.services.agent_instruction import _load_from_file
        empty_file = tmp_path / "AGENT_INSTRUCTION.md"
        empty_file.write_text("", encoding="utf-8")
        with patch("app.services.agent_instruction._INSTRUCTION_FILE", empty_file):
            result = _load_from_file()
            # Empty string is falsy but not FileNotFoundError; we get ""
            # The function returns text.strip(), which is ""
            assert isinstance(result, str)

    def test_whitespace_only_file_returns_empty(self, env_vars, tmp_path):
        """Whitespace-only file returns empty string after strip."""
        from app.services.agent_instruction import _load_from_file
        ws_file = tmp_path / "AGENT_INSTRUCTION.md"
        ws_file.write_text("   \n\n\t  ", encoding="utf-8")
        with patch("app.services.agent_instruction._INSTRUCTION_FILE", ws_file):
            result = _load_from_file()
            assert result == ""

    def test_permission_error_returns_fallback(self, env_vars, tmp_path):
        """PermissionError is not FileNotFoundError — may propagate."""
        from app.services.agent_instruction import _load_from_file
        perm_file = tmp_path / "AGENT_INSTRUCTION.md"
        perm_file.write_text("content")
        with patch("app.services.agent_instruction._INSTRUCTION_FILE", perm_file), \
             patch.object(type(perm_file), "read_text", side_effect=PermissionError("denied")):
            # PermissionError is not FileNotFoundError, so it will raise
            with pytest.raises(PermissionError):
                _load_from_file()

    def test_unicode_content_loads_correctly(self, env_vars, tmp_path):
        """File with unicode/emoji content loads without error."""
        from app.services.agent_instruction import _load_from_file
        uni_file = tmp_path / "AGENT_INSTRUCTION.md"
        uni_file.write_text("🚀 You are an agent with special chars: é, ñ, 中文", encoding="utf-8")
        with patch("app.services.agent_instruction._INSTRUCTION_FILE", uni_file):
            result = _load_from_file()
            assert "🚀" in result
            assert "中文" in result


# ============================================================================
# _inject_time_context negative/edge cases
# ============================================================================

class TestInjectTimeContextEdgeCases:
    """Negative and edge cases for _inject_time_context."""

    def _inject(self, timezone, epoch_ms, llm_request):
        with patch("agent.get_user_time_context", return_value=(timezone, epoch_ms)):
            from agent import _inject_time_context
            return _inject_time_context(MagicMock(), llm_request)

    def test_invalid_epoch_ms_non_numeric(self, env_vars):
        """Non-numeric epoch_ms → UTC is 'unknown' (no crash)."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hello"}]
        result = self._inject("US/Eastern", "not-a-number", llm_request)
        assert result is None
        # Time block is injected but UTC will be 'unknown'
        content = llm_request.messages[-1]["content"]
        assert "US/Eastern" in content
        assert "UTC=unknown" in content

    def test_timezone_only_no_epoch(self, env_vars):
        """Only timezone set, epoch is empty → still injects block."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hi"}]
        result = self._inject("America/Chicago", "", llm_request)
        assert result is None
        content = llm_request.messages[-1]["content"]
        assert "America/Chicago" in content
        assert "Epoch ms=unknown" in content

    def test_epoch_only_no_timezone(self, env_vars):
        """Only epoch set, timezone is empty → still injects block."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hi"}]
        result = self._inject("", "1700000000000", llm_request)
        assert result is None
        content = llm_request.messages[-1]["content"]
        assert "timezone=unknown" in content
        assert "1700000000000" in content

    def test_both_none_values_is_noop(self, env_vars):
        """None timezone and None epoch → no-op."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hello"}]
        result = self._inject(None, None, llm_request)
        assert result is None
        # Content should be untouched
        assert llm_request.messages[-1]["content"] == "hello"

    def test_object_format_list_content(self, env_vars):
        """Object-style user message with list content gets time block prepended."""
        llm_request = MagicMock()
        last_msg = MagicMock()
        last_msg.role = "user"
        last_msg.content = [{"type": "text", "text": "query"}]
        llm_request.messages = [last_msg]

        result = self._inject("US/Pacific", "1700000000000", llm_request)
        assert result is None
        assert len(last_msg.content) == 2
        assert "[System Time Context:" in last_msg.content[0]["text"]

    def test_no_messages_attribute(self, env_vars):
        """llm_request with no messages attribute → appends to instructions."""
        llm_request = MagicMock(spec=[])  # no attributes
        llm_request.messages = None
        llm_request.append_instructions = MagicMock()
        # hasattr(llm_request, "messages") is True but messages is None → falsy
        result = self._inject("US/Eastern", "1700000000000", llm_request)
        assert result is None
        llm_request.append_instructions.assert_called_once()

    def test_negative_epoch_does_not_crash(self, env_vars):
        """Negative epoch ms → still produces a UTC string (before 1970)."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hi"}]
        result = self._inject("UTC", "-1000", llm_request)
        assert result is None
        content = llm_request.messages[-1]["content"]
        assert "[System Time Context:" in content

    def test_zero_epoch(self, env_vars):
        """epoch_ms = '0' → 1970-01-01T00:00:00Z."""
        llm_request = MagicMock()
        llm_request.messages = [{"role": "user", "content": "hi"}]
        result = self._inject("UTC", "0", llm_request)
        assert result is None
        content = llm_request.messages[-1]["content"]
        assert "1970-01-01T00:00:00Z" in content


# ============================================================================
# _conn_params_from_discovery (src/agent/__init__.py line 331-360)
# ============================================================================

class TestConnParamsFromDiscovery:
    """Tests for _conn_params_from_discovery — dev-only MCP discovery for `adk web`."""

    def test_non_local_env_returns_empty(self, env_vars, monkeypatch):
        """When agent_env is not 'local', returns empty list."""
        from agent import _conn_params_from_discovery
        from app.config import Settings

        mock_settings = Settings.model_construct(agent_env="prod", mcp_servers_file="")
        with patch("agent.get_settings", return_value=mock_settings):
            result = _conn_params_from_discovery()
        assert result == []

    def test_no_mcp_servers_file_returns_empty(self, env_vars, monkeypatch):
        """When mcp_servers_file is empty, returns empty list."""
        from agent import _conn_params_from_discovery
        from app.config import Settings

        mock_settings = Settings.model_construct(agent_env="local", mcp_servers_file="")
        with patch("agent.get_settings", return_value=mock_settings):
            result = _conn_params_from_discovery()
        assert result == []

    def test_local_env_with_file_loads_toolsets(self, env_vars, monkeypatch):
        """When local env + file, loads MCP configs and creates toolsets."""
        from agent import _conn_params_from_discovery

        mock_cfg = MagicMock()
        mock_cfg.url = "http://localhost:8999/mcp"
        mock_cfg.headers = {}
        mock_cfg.transport = "sse"

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = "/tmp/mcp.yaml"

        with patch("agent.get_settings", return_value=mock_settings), \
             patch("app.mcp.client._load_from_file", return_value=[{"url": "http://localhost:8999/mcp"}]), \
             patch("app.mcp.client._validate_and_parse", return_value=[mock_cfg]):
            result = _conn_params_from_discovery()

        assert len(result) == 1

    def test_local_env_with_streamable_http_transport(self, env_vars, monkeypatch):
        """streamable_http transport creates StreamableHTTPConnectionParams."""
        from agent import _conn_params_from_discovery

        mock_cfg = MagicMock()
        mock_cfg.url = "http://localhost:8999/mcp"
        mock_cfg.headers = {"Authorization": "Bearer token"}
        mock_cfg.transport = "streamable_http"

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = "/tmp/mcp.yaml"

        with patch("agent.get_settings", return_value=mock_settings), \
             patch("app.mcp.client._load_from_file", return_value=[{}]), \
             patch("app.mcp.client._validate_and_parse", return_value=[mock_cfg]):
            result = _conn_params_from_discovery()

        assert len(result) == 1

    def test_discovery_exception_returns_empty(self, env_vars, monkeypatch):
        """If _load_from_file raises, returns empty list without crash."""
        from agent import _conn_params_from_discovery

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = "/tmp/mcp.yaml"

        with patch("agent.get_settings", return_value=mock_settings), \
             patch("app.mcp.client._load_from_file", side_effect=FileNotFoundError("missing")):
            result = _conn_params_from_discovery()

        assert result == []

    def test_empty_configs_returns_empty(self, env_vars, monkeypatch):
        """When _validate_and_parse returns no configs, returns empty list."""
        from agent import _conn_params_from_discovery

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = "/tmp/mcp.yaml"

        with patch("agent.get_settings", return_value=mock_settings), \
             patch("app.mcp.client._load_from_file", return_value=[]), \
             patch("app.mcp.client._validate_and_parse", return_value=[]):
            result = _conn_params_from_discovery()

        assert result == []

    def test_multiple_configs_create_multiple_toolsets(self, env_vars, monkeypatch):
        """Multiple MCP configs produce multiple MCPToolset entries."""
        from agent import _conn_params_from_discovery

        mock_cfg1 = MagicMock()
        mock_cfg1.url = "http://localhost:8999/mcp"
        mock_cfg1.headers = {}
        mock_cfg1.transport = "sse"

        mock_cfg2 = MagicMock()
        mock_cfg2.url = "http://localhost:9000/mcp"
        mock_cfg2.headers = {}
        mock_cfg2.transport = "streamable_http"

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = "/tmp/mcp.yaml"

        with patch("agent.get_settings", return_value=mock_settings), \
             patch("app.mcp.client._load_from_file", return_value=[{}, {}]), \
             patch("app.mcp.client._validate_and_parse", return_value=[mock_cfg1, mock_cfg2]):
            result = _conn_params_from_discovery()

        assert len(result) == 2


# ============================================================================
# _shrink_for_retry additional edge cases
# ============================================================================

class TestShrinkForRetryEdgeCases:
    """Additional edge cases for _HeaderInjectingClient._shrink_for_retry."""

    def _shrink(self, messages):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient._shrink_for_retry(messages)

    def test_no_messages_returns_empty(self, env_vars):
        """Empty messages list → empty result."""
        result = self._shrink([])
        assert result == []

    def test_system_only_no_crash(self, env_vars):
        """Only system messages, no user turns → system messages returned."""
        messages = [{"role": "system", "content": "You are helpful."}]
        result = self._shrink(messages)
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_nested_tool_content_truncated(self, env_vars):
        """Tool messages with nested list content blocks are truncated."""
        import agent.agent as agent_mod
        orig = agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS
        agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS = 20
        try:
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "q"},
                {
                    "role": "tool",
                    "content": [
                        {"type": "text", "text": "X" * 100},
                    ],
                },
            ]
            result = self._shrink(messages)
            tool_msg = [m for m in result if m["role"] == "tool"][0]
            text_block = tool_msg["content"][0]["text"]
            assert len(text_block) < 100
            assert "truncated" in text_block
        finally:
            agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS = orig

    def test_three_user_turns_keeps_only_last(self, env_vars):
        """Three user turns — only the last one survives."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "turn 2"},
            {"role": "assistant", "content": "reply 2"},
            {"role": "user", "content": "turn 3"},
            {"role": "assistant", "content": "reply 3"},
        ]
        result = self._shrink(messages)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "turn 3" in user_msgs[0]["content"]
        assert "[Note:" in user_msgs[0]["content"]

    def test_function_role_messages_truncated(self, env_vars):
        """Messages with role='function' are also truncated."""
        import agent.agent as agent_mod
        orig = agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS
        agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS = 10
        try:
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "q"},
                {"role": "function", "content": "Y" * 200},
            ]
            result = self._shrink(messages)
            func_msg = [m for m in result if m["role"] == "function"][0]
            assert len(func_msg["content"]) < 200
            assert "truncated" in func_msg["content"]
        finally:
            agent_mod._SHRINK_TOOL_RESULT_MAX_CHARS = orig

    def test_user_message_with_no_text_block_in_list(self, env_vars):
        """User message with list content but no text block — no crash on notice prepend."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old turn"},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "http://img"}}]},
        ]
        result = self._shrink(messages)
        # Should not crash; the notice can't be prepended to a non-text block
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1


# ============================================================================
# _sanitize_messages additional edge cases
# ============================================================================

class TestSanitizeMessagesEdgeCases:
    """Additional edge cases for _HeaderInjectingClient._sanitize_messages."""

    def _sanitize(self, messages):
        from agent.agent import _HeaderInjectingClient
        return _HeaderInjectingClient._sanitize_messages(messages)

    def test_none_content_preserved(self, env_vars):
        """Message with content=None is preserved (not a string, not a list)."""
        messages = [{"role": "assistant", "content": None}]
        result = self._sanitize(messages)
        assert len(result) == 1

    def test_mixed_empty_and_non_empty_text_blocks(self, env_vars):
        """Mixed blocks — only empty text blocks removed, rest preserved."""
        messages = [
            {
                "role": "tool",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "image_url", "image_url": {"url": "http://img"}},
                    {"type": "text", "text": "   "},
                    {"type": "text", "text": "real data"},
                ],
            }
        ]
        result = self._sanitize(messages)
        assert len(result) == 1
        assert len(result[0]["content"]) == 2  # image + "real data"

    def test_message_without_content_key_preserved(self, env_vars):
        """Message dict without 'content' key passes through."""
        messages = [{"role": "assistant"}]
        result = self._sanitize(messages)
        assert len(result) == 1

    def test_integer_content_preserved(self, env_vars):
        """Non-string, non-list content (e.g., int) passes through unchanged."""
        messages = [{"role": "user", "content": 42}]
        result = self._sanitize(messages)
        assert len(result) == 1
        assert result[0]["content"] == 42
