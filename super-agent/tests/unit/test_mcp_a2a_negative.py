"""Comprehensive negative and edge-case tests for MCP and A2A clients.

Covers connection failures, invalid configs, malformed responses,
timeouts, pool edge cases, and config loading from Redis/YAML.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.mcp.client import (
    MCPPool,
    MCPSession,
    MCPServerConfig,
    _load_from_file as mcp_load_from_file,
    _load_from_redis as mcp_load_from_redis,
    _parse_mcp_response,
    _validate_and_parse as mcp_validate_and_parse,
)
from app.a2a.client import (
    A2AAgentConfig,
    _load_from_file as a2a_load_from_file,
    _load_from_redis as a2a_load_from_redis,
    _validate_and_parse as a2a_validate_and_parse,
    fetch_agent_card,
    load_a2a_agents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(url="http://mcp.test/rpc", name="test-mcp"):
    client = httpx.AsyncClient()
    return MCPSession(client=client, url=url, name=name)


def _make_response(status_code=200, json_body=None, text="", headers=None):
    """Build a fake httpx.Response."""
    req = httpx.Request("POST", "http://mcp.test/rpc")
    resp = httpx.Response(
        status_code=status_code,
        request=req,
        headers=headers or {"content-type": "application/json"},
        text=text if text else json.dumps(json_body or {}),
    )
    return resp


def _valid_mcp_entry(**overrides):
    base = {
        "name": "srv1",
        "url": "http://mcp.test/rpc",
        "transport": "streamable_http",
        "enabled": True,
    }
    base.update(overrides)
    return base


def _valid_a2a_entry(**overrides):
    base = {"name": "agent1", "url": "http://a2a.test", "enabled": True}
    base.update(overrides)
    return base


# ===========================================================================
#  MCP / client.py  — Negative tests
# ===========================================================================


class TestMCPSessionConnectionFailure:
    """MCPSession.connect raises on unreachable server."""

    @pytest.mark.asyncio
    async def test_connect_unreachable(self):
        session = _make_session(url="http://localhost:1/rpc")
        with patch.object(
            session._c, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")
        ):
            with pytest.raises(httpx.ConnectError):
                await session.connect()

    @pytest.mark.asyncio
    async def test_connect_invalid_url_format(self):
        session = _make_session(url="not-a-url")
        with patch.object(
            session._c, "post", new_callable=AsyncMock, side_effect=httpx.InvalidURL("bad url")
        ):
            with pytest.raises(httpx.InvalidURL):
                await session.connect()

    @pytest.mark.asyncio
    async def test_connect_ssl_error(self):
        session = _make_session(url="https://bad-cert.test/rpc")
        # httpx does not have a dedicated SSLError; ConnectError wraps it
        with patch.object(
            session._c,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"),
        ):
            with pytest.raises(httpx.ConnectError, match="SSL"):
                await session.connect()


class TestMCPSessionRPC:
    """MCPSession._rpc edge / error cases."""

    @pytest.mark.asyncio
    async def test_rpc_timeout(self):
        session = _make_session()
        with patch.object(
            session._c,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            with pytest.raises(httpx.ReadTimeout):
                await session._rpc("tools/list", {}, req_id=1)

    @pytest.mark.asyncio
    async def test_rpc_malformed_json_response(self):
        """Server returns non-JSON body with application/json content-type."""
        resp = _make_response(status_code=200, text="NOT-JSON")
        resp.headers["content-type"] = "application/json"
        session = _make_session()
        with patch.object(
            session._c,
            "post",
            new_callable=AsyncMock,
            return_value=resp,
        ):
            # httpx Response.json() raises JSONDecodeError on invalid JSON
            with pytest.raises(Exception):
                await session._rpc("tools/list", {}, req_id=1)

    @pytest.mark.asyncio
    async def test_rpc_jsonrpc_error_response(self):
        """Server returns a valid JSON-RPC error — _rpc should still return it."""
        body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}
        resp = _make_response(json_body=body)
        session = _make_session()
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session._rpc("tools/list", {}, req_id=1)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_rpc_http_500(self):
        resp = _make_response(status_code=500, json_body={"error": "boom"})
        session = _make_session()
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                await session._rpc("tools/list", {}, req_id=1)

    @pytest.mark.asyncio
    async def test_rpc_sse_no_data_lines(self):
        """SSE response with no 'data:' lines yields empty dict."""
        resp = _make_response(text="event: keep-alive\n\n")
        resp.headers["content-type"] = "text/event-stream"
        session = _make_session()
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session._rpc("tools/call", {"name": "x", "arguments": {}}, req_id=99)
            assert result == {}


class TestMCPSessionReconnect:
    """call_tool reconnect logic."""

    @pytest.mark.asyncio
    async def test_reconnect_also_fails(self):
        session = _make_session()
        session.sid = "old-sid"
        # First _rpc call raises, triggering reconnect which also raises
        with patch.object(
            session,
            "_rpc",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("gone"),
        ):
            with patch.object(
                session,
                "connect",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("still gone"),
            ):
                result = await session.call_tool("some_tool", {})
                assert "Tool error" in result

    @pytest.mark.asyncio
    async def test_call_tool_first_fail_reconnect_success(self):
        session = _make_session()
        call_count = 0

        async def _rpc_side_effect(method, params, req_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("timeout")
            return {"result": {"content": [{"type": "text", "text": "ok"}]}}

        with patch.object(session, "_rpc", new_callable=AsyncMock, side_effect=_rpc_side_effect):
            with patch.object(session, "connect", new_callable=AsyncMock):
                result = await session.call_tool("t", {"a": 1})
                assert result == "ok"


class TestMCPPoolCallTool:
    """MCPPool.call_tool routing / error cases."""

    @pytest.mark.asyncio
    async def test_unknown_tool_name(self):
        pool = MCPPool(sessions=[])
        result = await pool.call_tool("nonexistent_tool", {})
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_tool_execution_raises(self):
        session = _make_session()
        session.tools = [{"name": "boom"}]
        pool = MCPPool(sessions=[session])
        pool._tool_session_map["boom"] = session
        with patch.object(
            session,
            "call_tool",
            new_callable=AsyncMock,
            return_value="Tool error: kaboom",
        ):
            result = await pool.call_tool("boom", {})
            assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_pool(self):
        pool = MCPPool(sessions=[])
        await pool.connect()  # should not raise
        assert pool.tools == []
        assert pool.oai_tools == []
        result = await pool.call_tool("anything", {})
        assert "not found" in result


class TestMCPPoolCallPrompt:
    """MCPPool.call_prompt negative paths."""

    @pytest.mark.asyncio
    async def test_unknown_prompt(self):
        pool = MCPPool(sessions=[])
        result = await pool.call_prompt("missing_prompt")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_all_sessions_fail_prompt(self):
        s1 = _make_session(name="s1")
        s2 = _make_session(name="s2")
        pool = MCPPool(sessions=[s1, s2])
        pool.failed_servers = []  # none failed at connect
        with patch.object(s1, "call_prompt", new_callable=AsyncMock, return_value="Prompt unavailable: err"):
            with patch.object(s2, "call_prompt", new_callable=AsyncMock, return_value="Prompt unavailable: err"):
                result = await pool.call_prompt("ask")
                assert "not found" in result


class TestMCPLoadFromRedis:
    """_load_from_redis negative paths."""

    @pytest.mark.asyncio
    async def test_redis_key_missing(self):
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        with patch("app.mcp.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value=None)
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            with pytest.raises(ValueError, match="not set or is empty"):
                await mcp_load_from_redis("agent:mcp_servers", mock_settings)

    @pytest.mark.asyncio
    async def test_redis_invalid_json(self):
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        with patch("app.mcp.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value="{bad json")
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            with pytest.raises(ValueError, match="JSON syntax error"):
                await mcp_load_from_redis("agent:mcp_servers", mock_settings)

    @pytest.mark.asyncio
    async def test_redis_empty_list(self):
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        with patch("app.mcp.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value="[]")
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            with pytest.raises(ValueError, match="empty list"):
                await mcp_load_from_redis("agent:mcp_servers", mock_settings)


class TestMCPLoadFromFile:
    """_load_from_file negative paths."""

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            mcp_load_from_file("/nonexistent/mcp_servers.yml")

    def test_malformed_yaml(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text(":\n  - :\n  bad: [")
        with pytest.raises(ValueError, match="YAML syntax error"):
            mcp_load_from_file(str(f))

    def test_empty_yaml(self, tmp_path):
        f = tmp_path / "empty.yml"
        f.write_text("")
        with pytest.raises(ValueError, match="is empty"):
            mcp_load_from_file(str(f))

    def test_yaml_no_mcp_servers_key(self, tmp_path):
        f = tmp_path / "no_key.yml"
        f.write_text("other_key:\n  - item")
        with pytest.raises(ValueError, match="no 'mcp_servers' key"):
            mcp_load_from_file(str(f))


class TestMCPValidateAndParse:
    """_validate_and_parse edge / error cases."""

    def test_empty_entries(self):
        with pytest.raises(ValueError, match="is empty"):
            mcp_validate_and_parse([], "test")

    def test_missing_required_fields(self):
        with pytest.raises(ValueError, match="missing required fields"):
            mcp_validate_and_parse([{"name": "x"}], "test")

    def test_invalid_transport(self):
        entry = _valid_mcp_entry(transport="grpc")
        with pytest.raises(ValueError, match="invalid transport"):
            mcp_validate_and_parse([entry], "test")

    def test_all_disabled(self):
        entry = _valid_mcp_entry(enabled=False)
        with pytest.raises(ValueError, match="none are enabled"):
            mcp_validate_and_parse([entry], "test")

    def test_empty_tools_list(self):
        """Server config is valid even with no tools — tools are discovered at connect time."""
        entry = _valid_mcp_entry()
        configs = mcp_validate_and_parse([entry], "test")
        assert len(configs) == 1


class TestMCPPoolConnect:
    """MCPPool.connect when individual sessions fail."""

    @pytest.mark.asyncio
    async def test_partial_session_failure(self):
        s1 = _make_session(name="good")
        s2 = _make_session(name="bad")
        with patch.object(s1, "connect", new_callable=AsyncMock):
            s1.tools = [{"name": "t1"}]
            s1.oai_tools = []
            s1.claude_tools = []
            s1.prompts = []
            s1.guide = ""
            with patch.object(
                s2, "connect", new_callable=AsyncMock, side_effect=Exception("boom")
            ):
                pool = MCPPool(sessions=[s1, s2])
                await pool.connect()
                assert len(pool.failed_servers) == 1
                assert pool.failed_servers[0]["name"] == "bad"

    @pytest.mark.asyncio
    async def test_concurrent_partial_failures(self):
        """Simulates multiple sessions where some fail."""
        sessions = []
        for i in range(5):
            s = _make_session(name=f"s{i}")
            sessions.append(s)

        pool = MCPPool(sessions=sessions)
        for i, s in enumerate(sessions):
            if i % 2 == 0:
                s.tools = [{"name": f"tool_{i}"}]
                s.oai_tools = []
                s.claude_tools = []
                s.prompts = []
                s.guide = ""
                patch.object(s, "connect", new_callable=AsyncMock).start()
            else:
                patch.object(
                    s, "connect", new_callable=AsyncMock, side_effect=Exception("fail")
                ).start()

        await pool.connect()
        assert len(pool.failed_servers) == 2  # sessions 1, 3
        patch.stopall()


class TestMCPCallToolLargeArgs:
    """Tool call with very large arguments."""

    @pytest.mark.asyncio
    async def test_large_arguments(self):
        session = _make_session()
        big_args = {"data": "x" * 100_000}
        resp_body = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        resp = _make_response(json_body=resp_body)
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session.call_tool("big_tool", big_args)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_tool_response_not_json_serializable(self):
        """When tool result content is not plain text — json.dumps fallback."""
        session = _make_session()
        resp_body = {"result": {"content": [{"type": "image", "data": "base64stuff"}]}}
        resp = _make_response(json_body=resp_body)
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session.call_tool("img_tool", {})
            # non-text content triggers json.dumps(c)
            assert "image" in result


# ===========================================================================
#  A2A / client.py  — Negative tests
# ===========================================================================


class TestA2ALoadFromRedis:

    @pytest.mark.asyncio
    async def test_redis_key_missing_returns_empty(self):
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        with patch("app.a2a.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value=None)
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            result = await a2a_load_from_redis("agent:a2a", mock_settings)
            assert result == []

    @pytest.mark.asyncio
    async def test_redis_invalid_json(self):
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        with patch("app.a2a.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value="not valid json{")
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            with pytest.raises(json.JSONDecodeError):
                await a2a_load_from_redis("agent:a2a", mock_settings)

    @pytest.mark.asyncio
    async def test_redis_empty_list_returns_empty(self):
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        with patch("app.a2a.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value="[]")
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            result = await a2a_load_from_redis("agent:a2a", mock_settings)
            assert result == []


class TestA2ALoadFromFile:

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            a2a_load_from_file("/nonexistent/a2a_agents.yml")

    def test_empty_yaml(self, tmp_path):
        f = tmp_path / "empty.yml"
        f.write_text("")
        with pytest.raises(ValueError, match="is empty"):
            a2a_load_from_file(str(f))

    def test_yaml_no_a2a_agents_key(self, tmp_path):
        f = tmp_path / "no_key.yml"
        f.write_text("other: stuff")
        with pytest.raises(ValueError, match="no 'a2a_agents' key"):
            a2a_load_from_file(str(f))

    def test_malformed_yaml(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text("a2a_agents:\n  - name: x\n  bad:\n[")
        # yaml.safe_load may raise yaml.YAMLError — A2A does not wrap it
        with pytest.raises(Exception):
            a2a_load_from_file(str(f))


class TestA2AValidateAndParse:

    def test_empty_entries(self):
        with pytest.raises(ValueError, match="is empty"):
            a2a_validate_and_parse([], "test")

    def test_missing_required_fields(self):
        with pytest.raises(ValueError, match="missing required fields"):
            a2a_validate_and_parse([{"name": "x"}], "test")

    def test_all_disabled(self):
        entry = _valid_a2a_entry(enabled=False)
        with pytest.raises(ValueError, match="none are enabled"):
            a2a_validate_and_parse([entry], "test")

    def test_hyphen_replaced_in_name(self):
        entry = _valid_a2a_entry(name="my-agent")
        configs = a2a_validate_and_parse([entry], "test")
        assert configs[0].name == "my_agent"

    def test_trailing_slash_stripped(self):
        entry = _valid_a2a_entry(url="http://a2a.test///")
        configs = a2a_validate_and_parse([entry], "test")
        assert not configs[0].url.endswith("/")


class TestA2AAgentConnectionFailure:

    @pytest.mark.asyncio
    async def test_fetch_agent_card_unreachable(self):
        with patch("app.a2a.client.httpx.AsyncClient") as MockClient:
            inst = AsyncMock()
            inst.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = inst
            card = await fetch_agent_card("http://down.test")
            assert card == {}

    @pytest.mark.asyncio
    async def test_fetch_agent_card_timeout(self):
        with patch("app.a2a.client.httpx.AsyncClient") as MockClient:
            inst = AsyncMock()
            inst.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = inst
            card = await fetch_agent_card("http://slow.test")
            assert card == {}

    @pytest.mark.asyncio
    async def test_fetch_agent_card_http_404(self):
        with patch("app.a2a.client.httpx.AsyncClient") as MockClient:
            inst = AsyncMock()
            resp = httpx.Response(
                404,
                request=httpx.Request("GET", "http://test/.well-known/agent.json"),
            )
            inst.get = AsyncMock(return_value=resp)
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = inst
            # raise_for_status is called inside, which raises HTTPStatusError
            card = await fetch_agent_card("http://test")
            assert card == {}


class TestA2ALoadAgentsLocal:
    """load_a2a_agents in local mode."""

    @pytest.mark.asyncio
    async def test_no_file_set_returns_empty(self):
        mock_settings = MagicMock(
            agent_env="local",
            a2a_agents_file="",
        )
        with patch("app.a2a.client.get_settings", return_value=mock_settings):
            result = await load_a2a_agents()
            assert result == []

    @pytest.mark.asyncio
    async def test_file_missing_raises(self):
        mock_settings = MagicMock(
            agent_env="local",
            a2a_agents_file="/nonexistent.yml",
        )
        with patch("app.a2a.client.get_settings", return_value=mock_settings):
            with pytest.raises(FileNotFoundError):
                await load_a2a_agents()


class TestA2AEmptyAgentList:
    """Config that resolves to an empty list of agents."""

    @pytest.mark.asyncio
    async def test_redis_empty_returns_empty(self):
        mock_settings = MagicMock(
            agent_env="dev",
            agent_group="default",
            a2a_agents_config_key="super_agent:config:a2a_agents:dev:default:config",
        )
        with patch("app.a2a.client.get_settings", return_value=mock_settings):
            with patch("app.a2a.client._load_from_redis", new_callable=AsyncMock, return_value=[]):
                result = await load_a2a_agents()
                assert result == []


# ===========================================================================
#  Edge-case tests
# ===========================================================================


class TestMCPSessionURLEdgeCases:
    """URL formatting edge cases."""

    @pytest.mark.asyncio
    async def test_trailing_slashes(self):
        session = _make_session(url="http://mcp.test/rpc///")
        assert session._url == "http://mcp.test/rpc///"

    @pytest.mark.asyncio
    async def test_various_url_schemes(self):
        for scheme in ("http", "https", "wss"):
            session = _make_session(url=f"{scheme}://mcp.test/rpc")
            assert session._url.startswith(scheme)

    @pytest.mark.asyncio
    async def test_session_headers_include_session_id(self):
        session = _make_session()
        session.sid = "abc-123"
        hdrs = session._hdrs()
        assert hdrs["Mcp-Session-Id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_session_headers_without_session_id(self):
        session = _make_session()
        session.sid = None
        hdrs = session._hdrs()
        assert "Mcp-Session-Id" not in hdrs


class TestMCPPoolSingleSession:

    @pytest.mark.asyncio
    async def test_single_session_pool(self):
        s = _make_session(name="solo")
        s.tools = [{"name": "t1"}]
        s.oai_tools = [{"type": "function", "function": {"name": "t1"}}]
        s.claude_tools = [{"name": "t1"}]
        s.prompts = []
        s.guide = "guide text"
        with patch.object(s, "connect", new_callable=AsyncMock):
            pool = MCPPool(sessions=[s])
            await pool.connect()
            assert len(pool.tools) == 1
            assert "guide text" in pool.guide


class TestMCPPoolManySessions:

    @pytest.mark.asyncio
    async def test_many_sessions(self):
        sessions = []
        for i in range(12):
            s = _make_session(name=f"srv{i}")
            s.tools = [{"name": f"tool_{i}"}]
            s.oai_tools = []
            s.claude_tools = []
            s.prompts = []
            s.guide = f"guide {i}" if i % 3 == 0 else ""
            patch.object(s, "connect", new_callable=AsyncMock).start()
            sessions.append(s)

        pool = MCPPool(sessions=sessions)
        await pool.connect()
        assert len(pool.tools) == 12
        assert pool.servers == [{"name": f"srv{i}", "url": "http://mcp.test/rpc"} for i in range(12)]
        patch.stopall()


class TestToolNameSpecialChars:

    @pytest.mark.asyncio
    async def test_tool_with_dots_hyphens_underscores(self):
        session = _make_session()
        resp_body = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        resp = _make_response(json_body=resp_body)
        for name in ("my.tool", "my-tool", "my_tool", "ns.sub-tool_v2"):
            with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
                result = await session.call_tool(name, {})
                assert result == "ok"

    @pytest.mark.asyncio
    async def test_tool_with_unicode(self):
        session = _make_session()
        resp_body = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        resp = _make_response(json_body=resp_body)
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session.call_tool("werkzeug_\u00fc", {"key": "\u00e9"})
            assert result == "ok"


class TestEmptyToolArguments:

    @pytest.mark.asyncio
    async def test_empty_arguments(self):
        session = _make_session()
        resp_body = {"result": {"content": [{"type": "text", "text": "empty ok"}]}}
        resp = _make_response(json_body=resp_body)
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session.call_tool("tool", {})
            assert result == "empty ok"


class TestVeryLargeToolResponse:

    @pytest.mark.asyncio
    async def test_large_response_1mb(self):
        big_text = "A" * (1024 * 1024)
        resp_body = {"result": {"content": [{"type": "text", "text": big_text}]}}
        resp = _make_response(json_body=resp_body)
        session = _make_session()
        with patch.object(session._c, "post", new_callable=AsyncMock, return_value=resp):
            result = await session.call_tool("big", {})
            assert len(result) == 1024 * 1024


class TestA2AAgentExtraHeaders:

    def test_extra_headers_preserved(self):
        entry = _valid_a2a_entry(headers={"Authorization": "Bearer tok"})
        configs = a2a_validate_and_parse([entry], "test")
        assert configs[0].headers == {"Authorization": "Bearer tok"}


class TestA2AAgentCustomTimeout:

    @pytest.mark.asyncio
    async def test_fetch_card_respects_timeout(self):
        """fetch_agent_card uses its own timeouts; verify it doesn't crash."""
        with patch("app.a2a.client.httpx.AsyncClient") as MockClient:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value=httpx.Response(
                200,
                request=httpx.Request("GET", "http://t/.well-known/agent.json"),
                json={"name": "bot", "skills": []},
            ))
            inst.__aenter__ = AsyncMock(return_value=inst)
            inst.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = inst
            card = await fetch_agent_card("http://t", headers={"X-Custom": "val"})
            assert card.get("name") == "bot"


class TestMCPDuplicateServerNames:

    def test_duplicate_names_accepted(self):
        """_validate_and_parse does not reject duplicate names (it's valid config)."""
        entries = [_valid_mcp_entry(name="dup"), _valid_mcp_entry(name="dup")]
        configs = mcp_validate_and_parse(entries, "test")
        assert len(configs) == 2


class TestYAMLConfigEdgeCases:

    def test_yaml_with_anchors(self, tmp_path):
        """YAML anchors & aliases parse correctly."""
        content = (
            "defaults: &defaults\n"
            "  transport: streamable_http\n"
            "  enabled: true\n"
            "mcp_servers:\n"
            "  - name: s1\n"
            "    url: http://s1.test\n"
            "    <<: *defaults\n"
        )
        f = tmp_path / "anchors.yml"
        f.write_text(content)
        entries = mcp_load_from_file(str(f))
        assert entries[0]["name"] == "s1"


class TestRedisKeySpecialChars:

    @pytest.mark.asyncio
    async def test_key_with_colons(self):
        """Redis keys with colons (standard pattern) work fine."""
        mock_settings = MagicMock(
            redis_host="localhost", redis_port=6379,
            redis_username="", redis_password="pass",
            redis_ssl=False,
        )
        valid_json = json.dumps([_valid_mcp_entry()])
        with patch("app.mcp.client.RedisCluster") as MockRedis:
            inst = AsyncMock()
            inst.get = AsyncMock(return_value=valid_json)
            inst.aclose = AsyncMock()
            MockRedis.return_value = inst
            entries = await mcp_load_from_redis(
                "super_agent:config:mcp_servers:dev:grp:config", mock_settings
            )
            assert len(entries) == 1


class TestParseMCPResponse:
    """Unit tests for _parse_mcp_response helper."""

    def test_json_content_type(self):
        resp = _make_response(json_body={"result": "ok"})
        assert _parse_mcp_response(resp) == {"result": "ok"}

    def test_sse_content_type(self):
        resp = _make_response(text="data: {\"result\": \"ok\"}\n\n")
        resp.headers["content-type"] = "text/event-stream"
        assert _parse_mcp_response(resp) == {"result": "ok"}

    def test_sse_no_data(self):
        resp = _make_response(text="event: ping\n\n")
        resp.headers["content-type"] = "text/event-stream"
        assert _parse_mcp_response(resp) == {}


class TestMCPPoolServersProperty:

    def test_servers_returns_correct_info(self):
        s1 = _make_session(name="a", url="http://a.test")
        s2 = _make_session(name="b", url="http://b.test")
        pool = MCPPool(sessions=[s1, s2])
        assert pool.servers == [
            {"name": "a", "url": "http://a.test"},
            {"name": "b", "url": "http://b.test"},
        ]


class TestMCPPoolGenerateFaqs:

    def test_generate_faqs_no_tools_no_prompts(self):
        pool = MCPPool(sessions=[])
        faqs = pool.generate_faqs()
        assert faqs == []

    def test_generate_faqs_with_prompts_and_tools(self):
        pool = MCPPool(sessions=[])
        pool.prompts = [
            {"name": "deploy-ask_crq", "description": "Ask about CRQ"},
            {"name": "deploy-check_status", "description": "Check deploy status"},
        ]
        pool.claude_tools = [
            {"name": "check_health", "description": "Check health status"},
        ]
        faqs = pool.generate_faqs()
        assert len(faqs) >= 2  # at least one prompt group + one tool group


class TestMCPSessionCallPrompt:

    @pytest.mark.asyncio
    async def test_call_prompt_rpc_error(self):
        session = _make_session()
        with patch.object(
            session, "_rpc", new_callable=AsyncMock, side_effect=Exception("rpc fail")
        ):
            result = await session.call_prompt("broken_prompt")
            assert "Prompt unavailable" in result

    @pytest.mark.asyncio
    async def test_call_prompt_success(self):
        session = _make_session()
        resp_body = {
            "result": {
                "messages": [
                    {"content": {"text": "Hello from prompt"}},
                    {"content": "plain string"},
                ]
            }
        }
        with patch.object(session, "_rpc", new_callable=AsyncMock, return_value=resp_body):
            result = await session.call_prompt("greet", {"user": "test"})
            assert "Hello from prompt" in result
            assert "plain string" in result


class TestMCPSessionLoadTools:

    @pytest.mark.asyncio
    async def test_load_tools_builds_oai_and_claude_formats(self):
        session = _make_session()
        resp = {
            "result": {
                "tools": [
                    {
                        "name": "my_tool",
                        "description": "Does stuff",
                        "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
                    }
                ]
            }
        }
        with patch.object(session, "_rpc", new_callable=AsyncMock, return_value=resp):
            await session._load_tools()
        assert len(session.tools) == 1
        assert session.oai_tools[0]["function"]["name"] == "my_tool"
        assert session.claude_tools[0]["name"] == "my_tool"


class TestMCPSessionLoadGuide:

    @pytest.mark.asyncio
    async def test_load_guide_no_resources(self):
        session = _make_session()
        with patch.object(
            session, "_rpc", new_callable=AsyncMock,
            return_value={"result": {"resources": []}},
        ):
            await session._load_guide()
        assert session.guide == ""

    @pytest.mark.asyncio
    async def test_load_guide_rpc_fails(self):
        session = _make_session()
        with patch.object(
            session, "_rpc", new_callable=AsyncMock, side_effect=Exception("fail")
        ):
            await session._load_guide()
        assert session.guide == ""
