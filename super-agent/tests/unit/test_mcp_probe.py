"""Unit tests for app.mcp.probe — MCP server probe diagnostic tool."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_httpx_response(data: dict, status_code: int = 200, headers: dict | None = None):
    """Return a mock httpx.Response with JSON body and configurable headers."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.headers = headers or {"content-type": "application/json"}
    r.json.return_value = data
    r.text = json.dumps(data)
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=r
        )
    return r


# ---------------------------------------------------------------------------
# TestGetMcpUrl
# ---------------------------------------------------------------------------

class TestGetMcpUrl:
    """Tests for _get_mcp_url()."""

    def test_no_args_returns_default(self):
        """When no CLI args provided, return the default URL."""
        from app.mcp.probe import _get_mcp_url, _DEFAULT_MCP_URL

        with patch.object(sys, "argv", ["probe.py"]):
            assert _get_mcp_url() == _DEFAULT_MCP_URL

    def test_argv1_returns_custom_url(self):
        """When sys.argv[1] is provided, return it."""
        from app.mcp.probe import _get_mcp_url

        custom = "http://my-server:9000/mcp"
        with patch.object(sys, "argv", ["probe.py", custom]):
            assert _get_mcp_url() == custom


# ---------------------------------------------------------------------------
# TestRpc
# ---------------------------------------------------------------------------

class TestRpc:
    """Tests for _rpc() — JSON-RPC request helper."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """_rpc sends JSON-RPC and returns (parsed_response, headers)."""
        from app.mcp.probe import _rpc

        payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        resp_headers = {"content-type": "application/json", "mcp-session-id": "sess-1"}
        mock_response = _make_httpx_response(payload, headers=resp_headers)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=mock_response)

        result, hdrs = await _rpc(client, "http://localhost/mcp", "tools/list", {}, req_id=1)

        client.post.assert_awaited_once()
        call_kwargs = client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["method"] == "tools/list"
        assert body["id"] == 1
        assert result == payload
        assert hdrs["mcp-session-id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_with_session_id_header(self):
        """When session_id is given, the Mcp-Session-Id header is included."""
        from app.mcp.probe import _rpc

        payload = {"jsonrpc": "2.0", "id": 2, "result": {}}
        mock_response = _make_httpx_response(payload)
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=mock_response)

        await _rpc(client, "http://localhost/mcp", "initialize", {}, req_id=2, session_id="my-session")

        call_kwargs = client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Mcp-Session-Id"] == "my-session"

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """When the HTTP response is an error, raise_for_status propagates."""
        from app.mcp.probe import _rpc

        mock_response = _make_httpx_response({}, status_code=500)
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            await _rpc(client, "http://localhost/mcp", "initialize", {}, req_id=1)


# ---------------------------------------------------------------------------
# TestSection
# ---------------------------------------------------------------------------

class TestSection:
    """Tests for _section() — log section header."""

    def test_logs_section_title(self, caplog):
        """_section logs separator lines with the title."""
        from app.mcp.probe import _section

        import logging
        with caplog.at_level(logging.INFO, logger="app.mcp.probe"):
            _section("TOOLS")

        assert "TOOLS" in caplog.text


# ---------------------------------------------------------------------------
# TestProbe
# ---------------------------------------------------------------------------

class TestProbe:
    """Tests for the probe() orchestration function."""

    def _build_rpc_side_effects(self, tools=None, resources=None, prompts=None):
        """Build a side_effect list for four _rpc calls in probe()."""
        init_resp = {
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "test-server", "version": "1.0"},
                "capabilities": {"tools": {}, "resources": {}},
            }
        }
        init_headers = {"mcp-session-id": "test-session"}

        tools_resp = {"result": {"tools": tools or []}}
        resources_resp = {"result": {"resources": resources or []}}
        prompts_resp = {"result": {"prompts": prompts or []}}

        return [
            (init_resp, init_headers),
            (tools_resp, {}),
            (resources_resp, {}),
            (prompts_resp, {}),
        ]

    @pytest.mark.asyncio
    async def test_successful_full_flow(self):
        """probe() completes the full initialize -> tools -> resources -> prompts flow."""
        from app.mcp.probe import probe

        tools = [{"name": "ping", "inputSchema": {"properties": {"host": {}}, "required": ["host"]}}]
        resources = [{"uri": "res://config", "mimeType": "application/json", "name": "config"}]
        prompts = [{"name": "greet", "arguments": [{"name": "name", "required": True}]}]

        side_effects = self._build_rpc_side_effects(tools=tools, resources=resources, prompts=prompts)

        with patch("app.mcp.probe._get_mcp_url", return_value="http://test/mcp"), \
             patch("app.mcp.probe._rpc", new_callable=AsyncMock, side_effect=side_effects), \
             patch("app.mcp.probe.httpx.AsyncClient") as mock_client_cls:

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            # Should complete without raising
            await probe()

    @pytest.mark.asyncio
    async def test_initialize_failure_exits(self):
        """When initialize raises an exception, probe() calls sys.exit(1)."""
        from app.mcp.probe import probe

        with patch("app.mcp.probe._get_mcp_url", return_value="http://test/mcp"), \
             patch("app.mcp.probe._rpc", new_callable=AsyncMock, side_effect=Exception("connection refused")), \
             patch("app.mcp.probe.httpx.AsyncClient") as mock_client_cls, \
             patch("app.mcp.probe.sys") as mock_sys:

            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(SystemExit):
                await probe()

            mock_sys.exit.assert_called_with(1)

    @pytest.mark.asyncio
    async def test_tools_list_failure_logged(self, caplog):
        """When tools/list fails, probe() logs a warning but continues."""
        from app.mcp.probe import probe
        import logging

        init_result = (
            {
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "srv", "version": "1"},
                    "capabilities": {},
                }
            },
            {"mcp-session-id": "s1"},
        )

        call_count = 0

        async def _rpc_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return init_result
            if call_count == 2:
                raise Exception("tools/list timeout")
            return ({"result": {}}, {})

        with patch("app.mcp.probe._get_mcp_url", return_value="http://test/mcp"), \
             patch("app.mcp.probe._rpc", new_callable=AsyncMock, side_effect=_rpc_side_effect), \
             patch("app.mcp.probe.httpx.AsyncClient") as mock_client_cls, \
             caplog.at_level(logging.WARNING, logger="app.mcp.probe"):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await probe()

        assert "tools/list" in caplog.text

    @pytest.mark.asyncio
    async def test_resources_list_failure_logged(self, caplog):
        """When resources/list fails, probe() logs a warning but continues."""
        from app.mcp.probe import probe
        import logging

        init_result = (
            {
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "srv", "version": "1"},
                    "capabilities": {},
                }
            },
            {"mcp-session-id": "s1"},
        )

        call_count = 0

        async def _rpc_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return init_result
            if call_count == 2:
                return ({"result": {"tools": []}}, {})
            if call_count == 3:
                raise Exception("resources/list failed")
            return ({"result": {}}, {})

        with patch("app.mcp.probe._get_mcp_url", return_value="http://test/mcp"), \
             patch("app.mcp.probe._rpc", new_callable=AsyncMock, side_effect=_rpc_side_effect), \
             patch("app.mcp.probe.httpx.AsyncClient") as mock_client_cls, \
             caplog.at_level(logging.WARNING, logger="app.mcp.probe"):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await probe()

        assert "resources/list" in caplog.text
