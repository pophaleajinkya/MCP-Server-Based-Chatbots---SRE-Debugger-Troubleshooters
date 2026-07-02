"""Unit tests for app.services.llm — LLM call helpers and agentic loops."""

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    openai_url="http://openai.test/v1/chat",
    openai_model="gpt-4-test",
    openai_headers=None,
    claude_gateway_url="http://claude.test/messages",
    claude_model="claude-opus-test",
    claude_headers=None,
    llm_timeout_seconds=30,
    max_tool_rounds=5,
):
    s = MagicMock()
    s.openai_url = openai_url
    s.openai_model = openai_model
    s.openai_headers = openai_headers or {}
    s.claude_gateway_url = claude_gateway_url
    s.claude_model = claude_model
    s.claude_headers = claude_headers or {}
    s.llm_timeout_seconds = llm_timeout_seconds
    s.max_tool_rounds = max_tool_rounds
    return s


def _make_mcp_pool(guide="", oai_tools=None, claude_tools=None):
    """Return a MagicMock MCPPool suitable for agentic loop tests."""
    mcp = MagicMock()
    mcp.guide = guide
    mcp.oai_tools = oai_tools or []
    mcp.claude_tools = claude_tools or []
    mcp.call_tool = AsyncMock(return_value="tool result")
    return mcp


def _make_async_client() -> MagicMock:
    """Return a mock httpx.AsyncClient with a post() AsyncMock."""
    client = MagicMock()
    client.post = AsyncMock()
    return client


def _make_http_response(json_data: dict, status_code: int = 200):
    """Return a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    if status_code >= 400:
        import httpx
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=r,
        )
    else:
        r.raise_for_status = MagicMock()
    return r


def _openai_response(content: str, finish_reason: str = "stop", tool_calls=None):
    """Build an OpenAI-style chat completion response dict."""
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [
            {
                "message": msg,
                "finish_reason": finish_reason,
            }
        ]
    }


def _claude_response(text: str = "", stop_reason: str = "end_turn", tool_use_blocks=None):
    """Build a Claude-style messages response dict."""
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool_use_blocks:
        content.extend(tool_use_blocks)
    return {"stop_reason": stop_reason, "content": content}


# ---------------------------------------------------------------------------
# TestLlmCall
# ---------------------------------------------------------------------------

class TestLlmCall:
    """Tests for llm_call()."""

    @pytest.mark.asyncio
    async def test_sends_correct_model_messages_max_tokens(self):
        """llm_call() should POST with correct model, messages, and max_tokens."""
        from app.services.llm import llm_call

        settings = _make_settings()
        client = _make_async_client()
        resp_data = _openai_response("Hello!")
        client.post.return_value = _make_http_response(resp_data)

        messages = [{"role": "user", "content": "ping"}]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await llm_call(client, messages)

        client.post.assert_awaited_once()
        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert body["model"] == "gpt-4-test"
        assert body["messages"] == messages
        assert body["max_tokens"] == 4000
        assert result == resp_data

    @pytest.mark.asyncio
    async def test_adds_tools_when_provided(self):
        """llm_call() should include tools and tool_choice when tools list is non-empty."""
        from app.services.llm import llm_call

        settings = _make_settings()
        client = _make_async_client()
        client.post.return_value = _make_http_response(_openai_response("ok"))

        tools = [{"type": "function", "function": {"name": "my_tool"}}]

        with patch("app.services.llm.get_settings", return_value=settings):
            await llm_call(client, [{"role": "user", "content": "q"}], tools=tools)

        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert body["tools"] == tools
        assert body["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_no_tools_key_when_tools_is_none(self):
        """llm_call() should not include 'tools' in the body when tools=None."""
        from app.services.llm import llm_call

        settings = _make_settings()
        client = _make_async_client()
        client.post.return_value = _make_http_response(_openai_response("ok"))

        with patch("app.services.llm.get_settings", return_value=settings):
            await llm_call(client, [{"role": "user", "content": "q"}], tools=None)

        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert "tools" not in body
        assert "tool_choice" not in body

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        """llm_call() should propagate HTTP errors from raise_for_status."""
        import httpx
        from app.services.llm import llm_call

        settings = _make_settings()
        client = _make_async_client()
        client.post.return_value = _make_http_response({}, status_code=500)

        with patch("app.services.llm.get_settings", return_value=settings):
            with pytest.raises(httpx.HTTPStatusError):
                await llm_call(client, [{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_posts_to_configured_openai_url(self):
        """llm_call() should POST to the openai_url from settings."""
        from app.services.llm import llm_call

        settings = _make_settings(openai_url="http://custom-endpoint.com/chat")
        client = _make_async_client()
        client.post.return_value = _make_http_response(_openai_response("response"))

        with patch("app.services.llm.get_settings", return_value=settings):
            await llm_call(client, [{"role": "user", "content": "q"}])

        args, _ = client.post.call_args
        assert args[0] == "http://custom-endpoint.com/chat"


# ---------------------------------------------------------------------------
# TestClaudeCall
# ---------------------------------------------------------------------------

class TestClaudeCall:
    """Tests for claude_call()."""

    @pytest.mark.asyncio
    async def test_sends_correct_model_system_messages(self):
        """claude_call() should POST with correct model, system, and messages."""
        from app.services.llm import claude_call

        settings = _make_settings()
        client = _make_async_client()
        resp_data = _claude_response("Hi there!")
        client.post.return_value = _make_http_response(resp_data)

        messages = [{"role": "user", "content": "Hello"}]
        system = "You are a helpful assistant."

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await claude_call(client, system, messages)

        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert body["model"] == "claude-opus-test"
        assert body["system"] == system
        assert body["messages"] == messages
        assert body["max_tokens"] == 4096
        assert result == resp_data

    @pytest.mark.asyncio
    async def test_adds_tools_when_provided(self):
        """claude_call() should include tools in body when tools list is given."""
        from app.services.llm import claude_call

        settings = _make_settings()
        client = _make_async_client()
        client.post.return_value = _make_http_response(_claude_response("ok"))

        tools = [{"name": "my_tool", "description": "does stuff", "input_schema": {}}]

        with patch("app.services.llm.get_settings", return_value=settings):
            await claude_call(client, "sys", [{"role": "user", "content": "q"}], tools=tools)

        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert body["tools"] == tools

    @pytest.mark.asyncio
    async def test_no_tools_key_when_tools_is_none(self):
        """claude_call() should not include 'tools' when tools=None."""
        from app.services.llm import claude_call

        settings = _make_settings()
        client = _make_async_client()
        client.post.return_value = _make_http_response(_claude_response("ok"))

        with patch("app.services.llm.get_settings", return_value=settings):
            await claude_call(client, "sys", [{"role": "user", "content": "q"}], tools=None)

        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert "tools" not in body

    @pytest.mark.asyncio
    async def test_posts_to_configured_claude_url(self):
        """claude_call() should POST to the claude_gateway_url from settings."""
        from app.services.llm import claude_call

        settings = _make_settings(claude_gateway_url="http://claude-gateway.test/v1/messages")
        client = _make_async_client()
        client.post.return_value = _make_http_response(_claude_response("ok"))

        with patch("app.services.llm.get_settings", return_value=settings):
            await claude_call(client, "sys", [{"role": "user", "content": "q"}])

        args, _ = client.post.call_args
        assert args[0] == "http://claude-gateway.test/v1/messages"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        """claude_call() should propagate HTTP errors from raise_for_status."""
        import httpx
        from app.services.llm import claude_call

        settings = _make_settings()
        client = _make_async_client()
        client.post.return_value = _make_http_response({}, status_code=401)

        with patch("app.services.llm.get_settings", return_value=settings):
            with pytest.raises(httpx.HTTPStatusError):
                await claude_call(client, "sys", [{"role": "user", "content": "q"}])


# ---------------------------------------------------------------------------
# TestRunAgentOpenai
# ---------------------------------------------------------------------------

class TestRunAgentOpenai:
    """Tests for run_agent_openai()."""

    @pytest.mark.asyncio
    async def test_single_round_returns_content(self):
        """Should return the message content when finish_reason is 'stop'."""
        from app.services.llm import run_agent_openai

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        resp = _openai_response("The cluster is healthy.", finish_reason="stop")
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_openai(mcp, client, "How is the cluster?")

        assert result == "The cluster is healthy."

    @pytest.mark.asyncio
    async def test_tool_use_round_calls_mcp_call_tool(self):
        """Should call mcp.call_tool for each tool_call in the response."""
        from app.services.llm import run_agent_openai

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        tool_calls = [
            {
                "id": "tc-1",
                "function": {
                    "name": "get_pods",
                    "arguments": json.dumps({"namespace": "default"}),
                },
            }
        ]
        tool_resp = _openai_response("", finish_reason="tool_calls", tool_calls=tool_calls)
        tool_resp["choices"][0]["message"]["tool_calls"] = tool_calls

        final_resp = _openai_response("All pods running.", finish_reason="stop")

        client.post.side_effect = [
            _make_http_response(tool_resp),
            _make_http_response(final_resp),
        ]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_openai(mcp, client, "List pods")

        mcp.call_tool.assert_awaited_once_with("get_pods", {"namespace": "default"})
        assert result == "All pods running."

    @pytest.mark.asyncio
    async def test_stops_when_no_tool_calls(self):
        """Should stop when finish_reason is not 'tool_calls'."""
        from app.services.llm import run_agent_openai

        settings = _make_settings(max_tool_rounds=10)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        resp = _openai_response("Done.", finish_reason="stop")
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_openai(mcp, client, "Anything")

        assert result == "Done."
        assert client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_safety_net_on_max_rounds_exceeded(self):
        """Should make a final summarise call when max_tool_rounds is exhausted."""
        from app.services.llm import run_agent_openai

        settings = _make_settings(max_tool_rounds=2)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        tool_calls = [
            {
                "id": "tc-x",
                "function": {
                    "name": "some_tool",
                    "arguments": json.dumps({}),
                },
            }
        ]
        tool_resp = _openai_response("", finish_reason="tool_calls", tool_calls=tool_calls)
        tool_resp["choices"][0]["message"]["tool_calls"] = tool_calls

        summary_resp = _openai_response("Summary of findings.", finish_reason="stop")

        # Two tool rounds + one summary call = 3 posts
        client.post.side_effect = [
            _make_http_response(tool_resp),
            _make_http_response(tool_resp),
            _make_http_response(summary_resp),
        ]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_openai(mcp, client, "Keep using tools forever")

        assert result == "Summary of findings."
        assert client.post.await_count == 3

    @pytest.mark.asyncio
    async def test_appends_guide_to_system_prompt_when_set(self):
        """Should include MCP guide in system message when mcp.guide is set."""
        from app.services.llm import run_agent_openai

        settings = _make_settings(max_tool_rounds=3)
        mcp = _make_mcp_pool(guide="Use the force, Luke.")
        client = _make_async_client()

        resp = _openai_response("Got it.", finish_reason="stop")
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            await run_agent_openai(mcp, client, "Help")

        _, kwargs = client.post.call_args_list[0]
        system_msg = kwargs["json"]["messages"][0]
        assert system_msg["role"] == "system"
        assert "Use the force, Luke." in system_msg["content"]

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_round(self):
        """Should await mcp.call_tool for each tool_call in a single round."""
        from app.services.llm import run_agent_openai

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        tool_calls = [
            {
                "id": "tc-1",
                "function": {"name": "tool_one", "arguments": json.dumps({"a": 1})},
            },
            {
                "id": "tc-2",
                "function": {"name": "tool_two", "arguments": json.dumps({"b": 2})},
            },
        ]
        tool_resp = _openai_response("", finish_reason="tool_calls", tool_calls=tool_calls)
        tool_resp["choices"][0]["message"]["tool_calls"] = tool_calls

        final_resp = _openai_response("Two tools done.", finish_reason="stop")

        client.post.side_effect = [
            _make_http_response(tool_resp),
            _make_http_response(final_resp),
        ]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_openai(mcp, client, "Run both tools")

        assert mcp.call_tool.await_count == 2
        assert result == "Two tools done."


# ---------------------------------------------------------------------------
# TestRunAgentClaude
# ---------------------------------------------------------------------------

class TestRunAgentClaude:
    """Tests for run_agent_claude()."""

    @pytest.mark.asyncio
    async def test_single_round_returns_text_block(self):
        """Should return text block content when stop_reason is 'end_turn'."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        resp = _claude_response("Cluster is fine.", stop_reason="end_turn")
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_claude(mcp, client, "Is the cluster healthy?")

        assert result == "Cluster is fine."

    @pytest.mark.asyncio
    async def test_tool_use_stop_reason_calls_mcp_call_tool(self):
        """Should call mcp.call_tool when stop_reason is 'tool_use'."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        tool_block = {
            "type": "tool_use",
            "id": "tu-1",
            "name": "get_deployments",
            "input": {"namespace": "prod"},
        }
        tool_resp = _claude_response(stop_reason="tool_use", tool_use_blocks=[tool_block])
        final_resp = _claude_response("Deployments all running.", stop_reason="end_turn")

        client.post.side_effect = [
            _make_http_response(tool_resp),
            _make_http_response(final_resp),
        ]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_claude(mcp, client, "List deployments")

        mcp.call_tool.assert_awaited_once_with("get_deployments", {"namespace": "prod"})
        assert result == "Deployments all running."

    @pytest.mark.asyncio
    async def test_end_turn_returns_text(self):
        """Should return joined text blocks on end_turn."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        resp = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "First part."},
                {"type": "text", "text": "Second part."},
            ],
        }
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_claude(mcp, client, "Tell me two things")

        assert "First part." in result
        assert "Second part." in result

    @pytest.mark.asyncio
    async def test_safety_net_on_max_rounds_exceeded(self):
        """Should make a summarise call after exhausting max_tool_rounds."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=2)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        tool_block = {
            "type": "tool_use",
            "id": "tu-loop",
            "name": "infinite_tool",
            "input": {},
        }
        tool_resp = _claude_response(stop_reason="tool_use", tool_use_blocks=[tool_block])
        summary_resp = _claude_response("Final summary.", stop_reason="end_turn")

        # Two tool rounds + one summary = 3 posts
        client.post.side_effect = [
            _make_http_response(tool_resp),
            _make_http_response(tool_resp),
            _make_http_response(summary_resp),
        ]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_claude(mcp, client, "Loop forever")

        assert result == "Final summary."
        assert client.post.await_count == 3

    @pytest.mark.asyncio
    async def test_appends_guide_to_system_when_set(self):
        """Should include MCP guide in the system prompt when mcp.guide is set."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=3)
        mcp = _make_mcp_pool(guide="Cluster guide content here.")
        client = _make_async_client()

        resp = _claude_response("Understood.", stop_reason="end_turn")
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            await run_agent_claude(mcp, client, "Help")

        _, kwargs = client.post.call_args_list[0]
        system_text = kwargs["json"]["system"]
        assert "Cluster guide content here." in system_text

    @pytest.mark.asyncio
    async def test_multiple_tool_use_blocks_in_one_round(self):
        """Should await mcp.call_tool for each tool_use block in one round."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=5)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        tool_blocks = [
            {"type": "tool_use", "id": "tu-a", "name": "tool_alpha", "input": {"x": 1}},
            {"type": "tool_use", "id": "tu-b", "name": "tool_beta", "input": {"y": 2}},
        ]
        tool_resp = _claude_response(stop_reason="tool_use", tool_use_blocks=tool_blocks)
        final_resp = _claude_response("Both done.", stop_reason="end_turn")

        client.post.side_effect = [
            _make_http_response(tool_resp),
            _make_http_response(final_resp),
        ]

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_claude(mcp, client, "Run both")

        assert mcp.call_tool.await_count == 2
        assert result == "Both done."

    @pytest.mark.asyncio
    async def test_ignores_non_text_blocks_in_final_response(self):
        """Should only join text-type blocks; other block types are ignored."""
        from app.services.llm import run_agent_claude

        settings = _make_settings(max_tool_rounds=3)
        mcp = _make_mcp_pool()
        client = _make_async_client()

        resp = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "Only this counts."},
                {"type": "image", "source": {"type": "base64", "data": "..."}},
            ],
        }
        client.post.return_value = _make_http_response(resp)

        with patch("app.services.llm.get_settings", return_value=settings):
            result = await run_agent_claude(mcp, client, "Give me an image too")

        assert result == "Only this counts."
