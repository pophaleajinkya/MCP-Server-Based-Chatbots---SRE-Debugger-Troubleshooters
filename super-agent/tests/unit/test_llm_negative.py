"""Negative and edge-case tests for src/app/services/llm.py.

Covers: llm_call, claude_call, run_agent_openai, run_agent_claude
with HTTP errors, timeouts, malformed responses, and boundary conditions.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.services.llm import claude_call, llm_call, run_agent_claude, run_agent_openai


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_settings(**overrides):
    defaults = dict(
        openai_model="gpt-4-test",
        openai_url="https://llm.test.com/openai/deployments/gpt-4-test/chat/completions?api-version=2024-10-21",
        openai_headers={"Content-Type": "application/json", "X-Api-Key": "k"},
        claude_model="claude-test",
        claude_gateway_url="https://claude.test.com/messages",
        claude_headers={"Content-Type": "application/json", "x-api-key": "k"},
        llm_timeout_seconds=10,
        max_tool_rounds=3,
    )
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _oai_response(content="hello", finish_reason="stop", tool_calls=None):
    msg = {"content": content, "role": "assistant"}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg, "finish_reason": finish_reason}]
    }


def _claude_response(text="hello", stop_reason="end_turn", tool_use_blocks=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool_use_blocks:
        content.extend(tool_use_blocks)
    return {"content": content, "stop_reason": stop_reason}


def _http_response(status_code, json_body=None, text_body=None):
    """Build a real httpx.Response with the given status code."""
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers = {"content-type": "application/json"}
    elif text_body is not None:
        body = text_body.encode()
        headers = {"content-type": "text/plain"}
    else:
        body = b""
        headers = {}
    return httpx.Response(status_code, content=body, headers=headers, request=httpx.Request("POST", "https://test"))


def _mock_mcp(guide="", oai_tools=None, claude_tools=None):
    mcp = MagicMock()
    mcp.guide = guide
    mcp.oai_tools = oai_tools or []
    mcp.claude_tools = claude_tools or []
    mcp.call_tool = AsyncMock(return_value="tool result")
    return mcp


_SETTINGS_PATCH = "app.services.llm.get_settings"
_HEADERS_PATCH = "app.services.llm.get_llm_headers"


# ============================================================================
# NEGATIVE TESTS — llm_call
# ============================================================================

class TestLlmCallHTTPErrors:
    """HTTP status errors from the LLM gateway."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
    async def test_http_error_codes(self, status):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(status, json_body={"error": "oops"})
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.HTTPStatusError):
                await llm_call(client, [{"role": "user", "content": "hi"}])


class TestLlmCallTimeouts:

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.ConnectTimeout("connect timed out")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.ConnectTimeout):
                await llm_call(client, [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_read_timeout(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.ReadTimeout("read timed out")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.ReadTimeout):
                await llm_call(client, [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_pool_timeout(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.PoolTimeout("pool exhausted")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.PoolTimeout):
                await llm_call(client, [{"role": "user", "content": "hi"}])


class TestLlmCallNetworkErrors:

    @pytest.mark.asyncio
    async def test_connect_error(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.ConnectError("DNS failure")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.ConnectError):
                await llm_call(client, [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_remote_protocol_error(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.RemoteProtocolError("peer reset")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.RemoteProtocolError):
                await llm_call(client, [{"role": "user", "content": "hi"}])


class TestLlmCallMalformedResponses:

    @pytest.mark.asyncio
    async def test_malformed_json_body(self):
        resp = httpx.Response(
            200,
            content=b"not json{{{",
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://test"),
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = resp
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(Exception):
                await llm_call(client, [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_empty_response_body(self):
        resp = httpx.Response(
            200,
            content=b"",
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://test"),
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = resp
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(Exception):
                await llm_call(client, [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_missing_choices_key(self):
        """llm_call returns the raw dict; run_agent_openai accesses choices — KeyError expected there."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body={"model": "gpt-4"})
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await llm_call(client, [{"role": "user", "content": "hi"}])
            assert "choices" not in result

    @pytest.mark.asyncio
    async def test_none_tools_omitted_from_body(self):
        """When tools is None the body should not contain 'tools' or 'tool_choice'."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await llm_call(client, [{"role": "user", "content": "hi"}], tools=None)
            posted_body = client.post.call_args[1]["json"]
            assert "tools" not in posted_body
            assert "tool_choice" not in posted_body

    @pytest.mark.asyncio
    async def test_empty_tools_list_omitted(self):
        """Empty list is falsy so tools should be omitted from the body."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await llm_call(client, [{"role": "user", "content": "hi"}], tools=[])
            posted_body = client.post.call_args[1]["json"]
            assert "tools" not in posted_body


# ============================================================================
# NEGATIVE TESTS — claude_call
# ============================================================================

class TestClaudeCallErrors:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
    async def test_http_error_codes(self, status):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(status, json_body={"error": "bad"})
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(httpx.HTTPStatusError):
                await claude_call(client, "system", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_missing_content_key(self):
        """claude_call returns raw dict; missing 'content' is handled by caller."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body={"stop_reason": "end_turn"})
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await claude_call(client, "sys", [{"role": "user", "content": "hi"}])
            assert "content" not in result

    @pytest.mark.asyncio
    async def test_none_tools_omitted(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_claude_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await claude_call(client, "sys", [{"role": "user", "content": "hi"}], tools=None)
            posted_body = client.post.call_args[1]["json"]
            assert "tools" not in posted_body


# ============================================================================
# NEGATIVE TESTS — run_agent_openai
# ============================================================================

class TestRunAgentOpenaiNegative:

    @pytest.mark.asyncio
    async def test_missing_choices_key_raises(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body={"model": "gpt-4"})
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(KeyError):
                await run_agent_openai(mcp, client, "hello")

    @pytest.mark.asyncio
    async def test_zero_choices_raises(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body={"choices": []})
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(IndexError):
                await run_agent_openai(mcp, client, "hello")

    @pytest.mark.asyncio
    async def test_tool_call_invalid_json_arguments(self):
        """json.loads on garbage arguments should raise."""
        resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{
                "id": "tc1",
                "function": {"name": "check_health", "arguments": "NOT JSON!!!"},
            }],
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "check_health"}}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(json.JSONDecodeError):
                await run_agent_openai(mcp, client, "check it")

    @pytest.mark.asyncio
    async def test_mcp_tool_call_failure(self):
        """When mcp.call_tool raises, the error propagates."""
        resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{
                "id": "tc1",
                "function": {"name": "check_health", "arguments": "{}"},
            }],
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "check_health"}}])
        mcp.call_tool.side_effect = RuntimeError("MCP down")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(RuntimeError, match="MCP down"):
                await run_agent_openai(mcp, client, "check it")

    @pytest.mark.asyncio
    async def test_tool_calls_present_but_empty_list(self):
        """finish_reason=tool_calls but empty tool_calls list -> return content."""
        resp = _oai_response(content="answer", finish_reason="tool_calls", tool_calls=[])
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "t"}}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            # empty tool_calls is falsy -> early return
            assert result == "answer"

    @pytest.mark.asyncio
    async def test_unexpected_finish_reason(self):
        """Unknown finish_reason != tool_calls -> should return content."""
        resp = _oai_response(content="partial", finish_reason="length")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == "partial"

    @pytest.mark.asyncio
    async def test_max_tool_rounds_exhaustion(self):
        """When every round returns tool_calls, the safety-net fires after max rounds."""
        tool_resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{"id": "tc1", "function": {"name": "check_health", "arguments": "{}"}}],
        )
        final_resp = _oai_response(content="summary", finish_reason="stop")
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "check_health"}}])

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # max_tool_rounds=3 -> calls 1,2,3 are tool rounds, call 4 is safety-net
            if call_count <= 3:
                return _http_response(200, json_body=tool_resp)
            return _http_response(200, json_body=final_resp)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == "summary"
            assert call_count == 4  # 3 tool rounds + 1 safety net

    @pytest.mark.asyncio
    async def test_empty_query_string(self):
        """Empty query should still execute; the LLM decides what to do."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response("response"))
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "")
            assert result == "response"

    @pytest.mark.asyncio
    async def test_empty_messages_list_in_llm_call(self):
        """Empty messages list should still be sent (LLM gateway may error)."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await llm_call(client, [])
            assert "choices" in result

    @pytest.mark.asyncio
    async def test_llm_returns_content_none(self):
        """msg.get('content') is None -> run_agent_openai returns ''."""
        resp = _oai_response(content=None, finish_reason="stop")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == ""


# ============================================================================
# NEGATIVE TESTS — run_agent_claude
# ============================================================================

class TestRunAgentClaudeNegative:

    @pytest.mark.asyncio
    async def test_mcp_tool_call_failure(self):
        tool_block = {"type": "tool_use", "id": "tu1", "name": "get_metrics", "input": {}}
        resp1 = _claude_response(text="thinking", stop_reason="tool_use", tool_use_blocks=[tool_block])
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp1)
        mcp = _mock_mcp(claude_tools=[{"name": "get_metrics"}])
        mcp.call_tool.side_effect = RuntimeError("MCP crashed")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(RuntimeError, match="MCP crashed"):
                await run_agent_claude(mcp, client, "metrics?")

    @pytest.mark.asyncio
    async def test_unexpected_stop_reason(self):
        """stop_reason not 'tool_use' -> returns text immediately."""
        resp = _claude_response(text="I'm done", stop_reason="max_tokens")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == "I'm done"

    @pytest.mark.asyncio
    async def test_max_tool_rounds_exhaustion_claude(self):
        tool_block = {"type": "tool_use", "id": "tu1", "name": "get_metrics", "input": {}}
        tool_resp = _claude_response(text="using tool", stop_reason="tool_use", tool_use_blocks=[tool_block])
        final_resp = _claude_response(text="summary", stop_reason="end_turn")

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return _http_response(200, json_body=tool_resp)
            return _http_response(200, json_body=final_resp)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(claude_tools=[{"name": "get_metrics"}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == "summary"
            assert call_count == 4

    @pytest.mark.asyncio
    async def test_empty_query_string_claude(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_claude_response("ok"))
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "")
            assert result == "ok"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_very_large_response_body(self):
        """Simulate a very large response body."""
        big_text = "x" * 500_000
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response(big_text))
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await llm_call(client, [{"role": "user", "content": "hi"}])
            assert result["choices"][0]["message"]["content"] == big_text

    @pytest.mark.asyncio
    async def test_unicode_in_query_and_response(self):
        unicode_text = "Kubernetes \u2603 \u00e9\u00e8\u00ea \u4f60\u597d"
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response(unicode_text))
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, unicode_text)
            assert result == unicode_text

    @pytest.mark.asyncio
    async def test_unicode_in_claude_system_and_tool_result(self):
        unicode_sys = "Assistant \u2603 \u00e9\u00e8"
        tool_block = {"type": "tool_use", "id": "tu1", "name": "t1", "input": {}}
        resp1 = _claude_response(text=None, stop_reason="tool_use", tool_use_blocks=[tool_block])
        resp2 = _claude_response(text="r\u00e9ponse \u4f60\u597d", stop_reason="end_turn")

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=resp1)
            return _http_response(200, json_body=resp2)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(guide=unicode_sys, claude_tools=[{"name": "t1"}])
        mcp.call_tool.return_value = "tool \u00e9\u00e8 done"
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q \u2603")
            assert "\u4f60\u597d" in result

    @pytest.mark.asyncio
    async def test_tool_call_empty_arguments(self):
        """Tool call with empty arguments string '{}'."""
        resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{"id": "tc1", "function": {"name": "check_health", "arguments": "{}"}}],
        )
        final = _oai_response(content="done", finish_reason="stop")
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=resp)
            return _http_response(200, json_body=final)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "check_health"}}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            mcp.call_tool.assert_called_once_with("check_health", {})

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_single_response(self):
        """Multiple tool calls in a single OpenAI response."""
        resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[
                {"id": "tc1", "function": {"name": "check_health", "arguments": "{}"}},
                {"id": "tc2", "function": {"name": "get_metrics", "arguments": '{"ns":"default"}'}},
            ],
        )
        final = _oai_response(content="all good", finish_reason="stop")
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=resp)
            return _http_response(200, json_body=final)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(oai_tools=[
            {"type": "function", "function": {"name": "check_health"}},
            {"type": "function", "function": {"name": "get_metrics"}},
        ])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == "all good"
            assert mcp.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_claude(self):
        """Multiple tool_use blocks in a single Claude response."""
        tool_blocks = [
            {"type": "tool_use", "id": "tu1", "name": "t1", "input": {}},
            {"type": "tool_use", "id": "tu2", "name": "t2", "input": {"x": 1}},
        ]
        resp1 = _claude_response(text="using tools", stop_reason="tool_use", tool_use_blocks=tool_blocks)
        resp2 = _claude_response(text="done", stop_reason="end_turn")
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=resp1)
            return _http_response(200, json_body=resp2)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(claude_tools=[{"name": "t1"}, {"name": "t2"}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == "done"
            assert mcp.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_tool_name_not_in_mcp_pool(self):
        """MCPPool.call_tool returns an error string for unknown tool names."""
        resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{"id": "tc1", "function": {"name": "nonexistent_tool", "arguments": "{}"}}],
        )
        final = _oai_response(content="handled", finish_reason="stop")
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=resp)
            return _http_response(200, json_body=final)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "nonexistent_tool"}}])
        mcp.call_tool.return_value = "Error: tool 'nonexistent_tool' not found in any connected MCP server"
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == "handled"

    @pytest.mark.asyncio
    async def test_response_with_both_text_and_tool_calls(self):
        """OpenAI msg has content AND tool_calls with finish_reason=tool_calls."""
        resp = _oai_response(
            content="thinking aloud",
            finish_reason="tool_calls",
            tool_calls=[{"id": "tc1", "function": {"name": "check_health", "arguments": "{}"}}],
        )
        final = _oai_response(content="done", finish_reason="stop")
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=resp)
            return _http_response(200, json_body=final)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "check_health"}}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            # tool_calls are executed, second call returns final
            assert result == "done"

    @pytest.mark.asyncio
    async def test_max_tool_rounds_zero_openai(self):
        """max_tool_rounds=0 -> loop body never runs, immediate safety-net."""
        final = _oai_response(content="safety net", finish_reason="stop")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=final)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings(max_tool_rounds=0)), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == "safety net"
            # Only the safety-net call
            assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_max_tool_rounds_zero_claude(self):
        """max_tool_rounds=0 -> immediate safety-net for Claude."""
        final = _claude_response(text="safety net", stop_reason="end_turn")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=final)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings(max_tool_rounds=0)), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == "safety net"
            assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_max_tool_rounds_one_openai(self):
        """max_tool_rounds=1 -> one tool round then safety-net if still tool_calls."""
        tool_resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[{"id": "tc1", "function": {"name": "t", "arguments": "{}"}}],
        )
        final = _oai_response(content="sum", finish_reason="stop")
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _http_response(200, json_body=tool_resp)
            return _http_response(200, json_body=final)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = _side_effect
        mcp = _mock_mcp(oai_tools=[{"type": "function", "function": {"name": "t"}}])
        with patch(_SETTINGS_PATCH, return_value=_mock_settings(max_tool_rounds=1)), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == "sum"
            assert call_count == 2  # 1 tool round + 1 safety net

    @pytest.mark.asyncio
    async def test_llm_returns_empty_string_content(self):
        """Empty string content -> returns ''."""
        resp = _oai_response(content="", finish_reason="stop")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_openai(mcp, client, "q")
            assert result == ""

    @pytest.mark.asyncio
    async def test_claude_empty_string_content(self):
        """Claude returns text block with empty text."""
        resp = _claude_response(text="", stop_reason="end_turn")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == ""

    @pytest.mark.asyncio
    async def test_guide_none_vs_empty_string_openai(self):
        """mcp.guide is falsy -> no guide appended to system prompt."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response("ok"))
        mcp = _mock_mcp(guide="")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await run_agent_openai(mcp, client, "q")
            body = client.post.call_args[1]["json"]
            system_msg = body["messages"][0]["content"]
            assert "AGENT GUIDE" not in system_msg

    @pytest.mark.asyncio
    async def test_guide_present_appended_openai(self):
        """mcp.guide is truthy -> guide IS appended to system prompt."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response("ok"))
        mcp = _mock_mcp(guide="Use these tools wisely.")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await run_agent_openai(mcp, client, "q")
            body = client.post.call_args[1]["json"]
            system_msg = body["messages"][0]["content"]
            assert "AGENT GUIDE" in system_msg
            assert "Use these tools wisely." in system_msg

    @pytest.mark.asyncio
    async def test_guide_none_vs_empty_string_claude(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_claude_response("ok"))
        mcp = _mock_mcp(guide="")
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await run_agent_claude(mcp, client, "q")
            body = client.post.call_args[1]["json"]
            assert "AGENT GUIDE" not in body["system"]

    @pytest.mark.asyncio
    async def test_headers_merging_with_empty_llm_headers(self):
        """get_llm_headers returns {} -> headers are just openai_headers."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await llm_call(client, [{"role": "user", "content": "hi"}])
            headers = client.post.call_args[1]["headers"]
            assert headers["X-Api-Key"] == "k"

    @pytest.mark.asyncio
    async def test_headers_merging_with_extra_llm_headers(self):
        """get_llm_headers adds extra headers -> they are merged in."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={"X-Trace-Id": "abc123"}):
            await llm_call(client, [{"role": "user", "content": "hi"}])
            headers = client.post.call_args[1]["headers"]
            assert headers["X-Trace-Id"] == "abc123"
            assert headers["X-Api-Key"] == "k"

    @pytest.mark.asyncio
    async def test_concurrent_tool_execution_partial_failure(self):
        """asyncio.gather propagates the first exception when a tool call fails."""
        resp = _oai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[
                {"id": "tc1", "function": {"name": "t1", "arguments": "{}"}},
                {"id": "tc2", "function": {"name": "t2", "arguments": "{}"}},
            ],
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)

        async def _call_tool(name, args):
            if name == "t2":
                raise RuntimeError("t2 broke")
            return "ok"

        mcp = _mock_mcp(oai_tools=[
            {"type": "function", "function": {"name": "t1"}},
            {"type": "function", "function": {"name": "t2"}},
        ])
        mcp.call_tool.side_effect = _call_tool
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            with pytest.raises(RuntimeError, match="t2 broke"):
                await run_agent_openai(mcp, client, "q")

    @pytest.mark.asyncio
    async def test_invalid_tool_schema_still_sent(self):
        """Invalid tool schema (not proper JSON Schema) is still passed through."""
        bad_tools = [{"type": "function", "function": {"name": "bad", "parameters": "NOT A DICT"}}]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=_oai_response())
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            await llm_call(client, [{"role": "user", "content": "hi"}], tools=bad_tools)
            body = client.post.call_args[1]["json"]
            assert body["tools"] == bad_tools

    @pytest.mark.asyncio
    async def test_claude_content_missing_returns_empty(self):
        """Claude response with no 'content' key -> empty string."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body={"stop_reason": "end_turn"})
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == ""

    @pytest.mark.asyncio
    async def test_claude_no_text_blocks_returns_empty(self):
        """Claude content has blocks but none of type 'text'."""
        resp = {"content": [{"type": "image", "source": "data"}], "stop_reason": "end_turn"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _http_response(200, json_body=resp)
        mcp = _mock_mcp()
        with patch(_SETTINGS_PATCH, return_value=_mock_settings()), \
             patch(_HEADERS_PATCH, return_value={}):
            result = await run_agent_claude(mcp, client, "q")
            assert result == ""
