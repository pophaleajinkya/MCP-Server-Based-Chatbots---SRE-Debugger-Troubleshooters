"""
Unit tests for app.tools.remote_agent — make_remote_agent_tool.

Covers every code path in the returned async callable:
  - Successful response with text artifact
  - Successful response with status message (no artifacts)
  - Successful response with no text output at all
  - JSON-RPC error in response body
  - HTTP status error (4xx/5xx)
  - Network / connection error
  - Optional session_id forwarded to params
  - Custom extra_headers merged into request
  - Tool name and docstring set on returned callable
  - Default and custom timeout_seconds
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "src")
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_REQUEST = httpx.Request("POST", "http://agent.test/a2a")


def _make_response(body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        text=json.dumps(body),
        headers={"content-type": "application/json"},
        request=_DUMMY_REQUEST,
    )


def _completed_task(text: str) -> dict:
    return {
        "result": {
            "status": {"state": "completed"},
            "artifacts": [
                {"parts": [{"type": "text", "text": text}]}
            ],
        }
    }


def _status_message_task(text: str) -> dict:
    return {
        "result": {
            "status": {
                "state": "completed",
                "message": {"parts": [{"type": "text", "text": text}]},
            },
            "artifacts": [],
        }
    }


def _no_output_task(state: str = "completed") -> dict:
    return {
        "result": {
            "status": {"state": state},
            "artifacts": [],
        }
    }


def _rpc_error_body(code: int = -32600, message: str = "bad request") -> dict:
    return {"error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMakeRemoteAgentTool:

    def _tool(self, **kw):
        from app.tools.remote_agent import make_remote_agent_tool
        return make_remote_agent_tool(
            name="call_sre_agent",
            description="Delegate to SRE agent",
            base_url="http://agent.test",
            **kw,
        )

    # -- metadata -------------------------------------------------------

    def test_returned_callable_has_correct_name(self):
        tool = self._tool()
        assert tool.__name__ == "call_sre_agent"

    def test_returned_callable_has_correct_docstring(self):
        tool = self._tool()
        assert tool.__doc__ == "Delegate to SRE agent"

    def test_default_timeout_is_120_seconds(self):
        """Default read timeout is _READ_TIMEOUT (120 s)."""
        from app.tools.remote_agent import _READ_TIMEOUT
        assert _READ_TIMEOUT == 120.0

    # -- successful artifact response -----------------------------------

    @pytest.mark.asyncio
    async def test_returns_text_from_artifact(self):
        tool = self._tool()
        resp = _make_response(_completed_task("All pods healthy"))
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=resp),
        ):
            result = await tool("check health")
        assert result == "All pods healthy"

    @pytest.mark.asyncio
    async def test_multiple_text_parts_joined(self):
        """Multiple text parts in artifact[0] are joined with newline."""
        body = {
            "result": {
                "status": {"state": "completed"},
                "artifacts": [{
                    "parts": [
                        {"type": "text", "text": "Line 1"},
                        {"type": "text", "text": "Line 2"},
                    ]
                }],
            }
        }
        tool = self._tool()
        resp = _make_response(body)
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert result == "Line 1\nLine 2"

    @pytest.mark.asyncio
    async def test_non_text_parts_in_artifact_skipped(self):
        """Parts without type='text' are ignored; only text parts are joined."""
        body = {
            "result": {
                "status": {"state": "completed"},
                "artifacts": [{
                    "parts": [
                        {"type": "image", "data": "base64..."},
                        {"type": "text", "text": "result text"},
                    ]
                }],
            }
        }
        tool = self._tool()
        resp = _make_response(body)
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert result == "result text"

    # -- fallback to status message -------------------------------------

    @pytest.mark.asyncio
    async def test_falls_back_to_status_message_when_no_artifacts(self):
        tool = self._tool()
        resp = _make_response(_status_message_task("Working on it"))
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("check")
        assert result == "Working on it"

    @pytest.mark.asyncio
    async def test_status_message_multiple_parts_joined(self):
        body = {
            "result": {
                "status": {
                    "state": "working",
                    "message": {
                        "parts": [
                            {"type": "text", "text": "Part A"},
                            {"type": "text", "text": "Part B"},
                        ]
                    },
                },
                "artifacts": [],
            }
        }
        tool = self._tool()
        resp = _make_response(body)
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert result == "Part A\nPart B"

    # -- no output at all -----------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_fallback_message_when_no_text_output(self):
        """When neither artifacts nor status message have text, return fallback."""
        tool = self._tool()
        resp = _make_response(_no_output_task("completed"))
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert "completed" in result
        assert "call_sre_agent" in result

    @pytest.mark.asyncio
    async def test_state_reflected_in_fallback_message(self):
        tool = self._tool()
        resp = _make_response(_no_output_task("failed"))
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert "failed" in result

    # -- JSON-RPC error -------------------------------------------------

    @pytest.mark.asyncio
    async def test_rpc_error_returns_error_message(self):
        tool = self._tool()
        resp = _make_response(_rpc_error_body(message="tool not found"))
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert "[remote-agent error]" in result
        assert "tool not found" in result

    @pytest.mark.asyncio
    async def test_rpc_error_without_message_uses_unknown(self):
        """RPC error body without 'message' key uses 'unknown error' fallback."""
        body = {"error": {"code": -32603}}
        tool = self._tool()
        resp = _make_response(body)
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
            result = await tool("query")
        assert "unknown error" in result

    # -- HTTP errors ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_http_status_error_returns_error_prefix(self):
        tool = self._tool()
        err_resp = _make_response({}, status=503)
        exc = httpx.HTTPStatusError(
            "503", request=_DUMMY_REQUEST, response=err_resp
        )
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=exc),
        ):
            result = await tool("query")
        assert "[remote-agent error]" in result
        assert "503" in result
        assert "call_sre_agent" in result

    @pytest.mark.asyncio
    async def test_http_status_error_404(self):
        tool = self._tool()
        err_resp = _make_response({}, status=404)
        exc = httpx.HTTPStatusError(
            "404", request=_DUMMY_REQUEST, response=err_resp
        )
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=exc)):
            result = await tool("query")
        assert "404" in result

    # -- Network errors -------------------------------------------------

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_prefix(self):
        tool = self._tool()
        exc = httpx.ConnectError("connection refused", request=_DUMMY_REQUEST)
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=exc)):
            result = await tool("query")
        assert "[remote-agent error]" in result
        assert "call_sre_agent" in result

    @pytest.mark.asyncio
    async def test_timeout_error_returns_error_prefix(self):
        tool = self._tool()
        exc = httpx.TimeoutException(
            "read timed out", request=_DUMMY_REQUEST
        )
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=exc)):
            result = await tool("query")
        assert "[remote-agent error]" in result

    # -- session_id forwarding ------------------------------------------

    @pytest.mark.asyncio
    async def test_session_id_included_when_provided(self):
        """session_id must appear in the JSON-RPC params when passed."""
        tool = self._tool()
        resp = _make_response(_completed_task("ok"))
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=resp),
        ) as mock_post:
            await tool("query", session_id="sess-abc-123")

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        # A2A SDK 0.3: sessionId lives in params.configuration
        assert payload["params"]["configuration"]["sessionId"] == "sess-abc-123"

    @pytest.mark.asyncio
    async def test_session_id_omitted_when_not_provided(self):
        """When session_id is None the configuration dict must not contain 'sessionId'."""
        tool = self._tool()
        resp = _make_response(_completed_task("ok"))
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=resp),
        ) as mock_post:
            await tool("query")

        payload = mock_post.call_args[1]["json"]
        assert "sessionId" not in payload["params"].get("configuration", {})

    # -- extra headers --------------------------------------------------

    @pytest.mark.asyncio
    async def test_extra_headers_included(self):
        """extra_headers are merged into the client's default headers."""
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            name="t",
            description="d",
            base_url="http://agent.test",
            extra_headers={"X-Custom": "value-xyz"},
        )
        resp = _make_response(_completed_task("ok"))
        # Capture the AsyncClient that's instantiated to inspect headers
        original_init = httpx.AsyncClient.__init__

        captured_headers = {}

        def patched_init(self, *args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            with patch(
                "httpx.AsyncClient.post",
                new=AsyncMock(return_value=resp),
            ):
                await tool("query")

        assert captured_headers.get("X-Custom") == "value-xyz"

    # -- endpoint URL construction --------------------------------------

    @pytest.mark.asyncio
    async def test_endpoint_appends_a2a_to_base_url(self):
        """The tool must POST to {base_url}/a2a."""
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            name="t", description="d",
            base_url="http://my-agent.example.com",
        )
        resp = _make_response(_completed_task("ok"))
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=resp),
        ) as mock_post:
            await tool("query")

        url = mock_post.call_args[0][0]
        assert url == "http://my-agent.example.com/a2a"

    @pytest.mark.asyncio
    async def test_trailing_slash_stripped_from_base_url(self):
        """Trailing slash on base_url must not produce double-slash endpoint."""
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            name="t", description="d",
            base_url="http://my-agent.example.com/",
        )
        resp = _make_response(_completed_task("ok"))
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=resp),
        ) as mock_post:
            await tool("query")

        url = mock_post.call_args[0][0]
        assert url == "http://my-agent.example.com/a2a"

    # -- custom timeout -------------------------------------------------

    @pytest.mark.asyncio
    async def test_custom_timeout_passed_to_httpx(self):
        """timeout_seconds configures the read timeout on the httpx.Timeout."""
        from app.tools.remote_agent import make_remote_agent_tool
        tool = make_remote_agent_tool(
            name="t", description="d",
            base_url="http://agent.test",
            timeout_seconds=30.0,
        )
        resp = _make_response(_completed_task("ok"))
        captured_timeouts: list = []
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            t = kwargs.get("timeout")
            if t is not None:
                captured_timeouts.append(t)
            return original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            with patch(
                "httpx.AsyncClient.post",
                new=AsyncMock(return_value=resp),
            ):
                await tool("query")

        assert captured_timeouts, "Expected at least one timeout to be captured"
        t = captured_timeouts[0]
        assert t.read == 30.0

    # -- JSON-RPC payload structure ------------------------------------

    @pytest.mark.asyncio
    async def test_jsonrpc_payload_has_correct_structure(self):
        """The POST payload must be a valid JSON-RPC 2.0 message/send request (A2A SDK 0.3)."""
        tool = self._tool()
        resp = _make_response(_completed_task("ok"))
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=resp),
        ) as mock_post:
            await tool("hello world")

        payload = mock_post.call_args[1]["json"]
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == 1
        assert payload["method"] == "message/send"
        assert payload["params"]["message"]["role"] == "user"
        assert payload["params"]["message"]["parts"][0]["text"] == "hello world"
