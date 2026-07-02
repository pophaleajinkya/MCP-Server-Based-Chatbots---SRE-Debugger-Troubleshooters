"""Unit tests for app.mcp.client — MCP client helpers and classes."""

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_json_response(data: dict, content_type: str = "application/json"):
    """Return a mock httpx.Response that looks like a JSON response."""
    r = MagicMock()
    r.headers = {"content-type": content_type}
    r.json.return_value = data
    r.text = json.dumps(data)
    return r


def _make_sse_response(data_line: dict | None, extra_lines: list[str] | None = None):
    """Return a mock httpx.Response with text/event-stream content-type."""
    r = MagicMock()
    r.headers = {"content-type": "text/event-stream"}
    lines = []
    if extra_lines:
        lines.extend(extra_lines)
    if data_line is not None:
        lines.append(f"data: {json.dumps(data_line)}")
    r.text = "\n".join(lines)
    r.json.return_value = {}
    return r


# ---------------------------------------------------------------------------
# TestParseMcpResponse
# ---------------------------------------------------------------------------

class TestParseMcpResponse:
    """Tests for _parse_mcp_response()."""

    def test_json_content_type_returns_json(self):
        """JSON content-type should call r.json() and return its value."""
        from app.mcp.client import _parse_mcp_response

        payload = {"result": {"tools": [{"name": "ping"}]}}
        r = _make_json_response(payload)
        result = _parse_mcp_response(r)
        assert result == payload
        r.json.assert_called_once()

    def test_sse_with_data_line_returns_parsed_json(self):
        """SSE response with a 'data:' line should parse and return its JSON."""
        from app.mcp.client import _parse_mcp_response

        payload = {"result": {"sessionId": "abc123"}}
        r = _make_sse_response(payload, extra_lines=["event: message", "id: 1"])
        result = _parse_mcp_response(r)
        assert result == payload

    def test_sse_with_no_data_lines_returns_empty_dict(self):
        """SSE response with no 'data:' lines should return {}."""
        from app.mcp.client import _parse_mcp_response

        r = _make_sse_response(None, extra_lines=["event: ping", ": keep-alive"])
        result = _parse_mcp_response(r)
        assert result == {}

    def test_sse_picks_first_data_line(self):
        """SSE response with multiple 'data:' lines should return the first one."""
        from app.mcp.client import _parse_mcp_response

        r = MagicMock()
        r.headers = {"content-type": "text/event-stream"}
        first = {"id": 1}
        second = {"id": 2}
        r.text = f"data: {json.dumps(first)}\ndata: {json.dumps(second)}"
        result = _parse_mcp_response(r)
        assert result == first

    def test_json_response_with_no_content_type_header(self):
        """Missing content-type header should fall through to r.json()."""
        from app.mcp.client import _parse_mcp_response

        payload = {"jsonrpc": "2.0", "id": 1, "result": {}}
        r = MagicMock()
        r.headers = {}
        r.json.return_value = payload
        result = _parse_mcp_response(r)
        assert result == payload


# ---------------------------------------------------------------------------
# TestMCPServerConfig
# ---------------------------------------------------------------------------

class TestMCPServerConfig:
    """Tests for the MCPServerConfig dataclass."""

    def test_defaults(self):
        """MCPServerConfig should have correct default values."""
        from app.mcp.client import MCPServerConfig

        cfg = MCPServerConfig(name="my-server", url="http://localhost:8080/mcp")
        assert cfg.transport == "streamable_http"
        assert cfg.enabled is True
        assert cfg.headers == {}
        assert cfg.required_token is False
        assert cfg.description == ""

    def test_custom_values(self):
        """MCPServerConfig should store all custom values correctly."""
        from app.mcp.client import MCPServerConfig

        cfg = MCPServerConfig(
            name="custom",
            url="http://example.com/mcp",
            transport="http",
            enabled=False,
            headers={"Authorization": "Bearer tok"},
            required_token=True,
            description="A test server",
        )
        assert cfg.name == "custom"
        assert cfg.url == "http://example.com/mcp"
        assert cfg.transport == "http"
        assert cfg.enabled is False
        assert cfg.headers == {"Authorization": "Bearer tok"}
        assert cfg.required_token is True
        assert cfg.description == "A test server"

    def test_enabled_flag_false(self):
        """enabled=False should be stored correctly."""
        from app.mcp.client import MCPServerConfig

        cfg = MCPServerConfig(name="disabled", url="http://x.com/mcp", enabled=False)
        assert cfg.enabled is False

    def test_headers_are_independent(self):
        """Each MCPServerConfig instance should have its own headers dict."""
        from app.mcp.client import MCPServerConfig

        a = MCPServerConfig(name="a", url="http://a.com")
        b = MCPServerConfig(name="b", url="http://b.com")
        a.headers["X-Foo"] = "bar"
        assert "X-Foo" not in b.headers


# ---------------------------------------------------------------------------
# TestLoadMcpServers
# ---------------------------------------------------------------------------

class TestLoadMcpServersFromFile:
    """Tests for _load_mcp_servers_from_file() (the dev-mode YAML loader)."""

    def test_loads_enabled_servers(self, tmp_path):
        """Should parse YAML and return only enabled servers."""
        from app.mcp.client import _load_mcp_servers_from_file

        yml = tmp_path / "servers.yml"
        yml.write_text(
            "servers:\n"
            "  - name: health-mcp\n"
            "    url: http://localhost:8999/mcp/\n"
            "    transport: streamable_http\n"
            "    enabled: true\n"
            "  - name: dep-mcp\n"
            "    url: http://localhost:8015/mcp/\n"
            "    transport: streamable_http\n"
            "    enabled: false\n"
        )

        servers = _load_mcp_servers_from_file(str(yml))

        assert len(servers) == 1
        assert servers[0].name == "health-mcp"
        assert servers[0].url == "http://localhost:8999/mcp/"

    def test_all_enabled_returns_all(self, tmp_path):
        """All enabled entries should all be returned."""
        from app.mcp.client import _load_mcp_servers_from_file

        yml = tmp_path / "servers.yml"
        yml.write_text(
            "servers:\n"
            "  - name: alpha\n"
            "    url: http://alpha.com/mcp\n"
            "    transport: streamable_http\n"
            "    enabled: true\n"
            "  - name: beta\n"
            "    url: http://beta.com/mcp\n"
            "    transport: streamable_http\n"
            "    enabled: true\n"
        )

        servers = _load_mcp_servers_from_file(str(yml))

        assert len(servers) == 2
        assert {s.name for s in servers} == {"alpha", "beta"}

    def test_raises_on_missing_file(self):
        """FileNotFoundError must be raised when the path does not exist."""
        from app.mcp.client import _load_mcp_servers_from_file

        with pytest.raises(FileNotFoundError):
            _load_mcp_servers_from_file("/nonexistent/path.yml")

    def test_headers_and_description_fields(self, tmp_path):
        """Optional headers and description should be read correctly."""
        from app.mcp.client import _load_mcp_servers_from_file

        yml = tmp_path / "servers.yml"
        yml.write_text(
            "servers:\n"
            "  - name: srv\n"
            "    url: http://srv.com/mcp\n"
            "    transport: sse\n"
            "    enabled: true\n"
            "    description: my server\n"
            "    headers:\n"
            "      Authorization: Bearer tok\n"
        )

        servers = _load_mcp_servers_from_file(str(yml))

        assert servers[0].transport == "sse"
        assert servers[0].description == "my server"
        assert servers[0].headers == {"Authorization": "Bearer tok"}


class TestLoadMcpServers:
    """Tests for load_mcp_servers() — dev vs prod routing."""

    @pytest.mark.asyncio
    async def test_local_mode_reads_yaml_file(self, tmp_path):
        """When AGENT_ENV=local, must read from MCP_SERVERS_FILE, not Redis."""
        from app.mcp.client import load_mcp_servers

        yml = tmp_path / "servers.yml"
        yml.write_text(
            "servers:\n"
            "  - name: health-mcp\n"
            "    url: http://localhost:8999/mcp/\n"
            "    transport: streamable_http\n"
            "    enabled: true\n"
        )

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = str(yml)

        with patch("app.mcp.client.get_settings", return_value=mock_settings):
            servers = await load_mcp_servers()

        assert len(servers) == 1
        assert servers[0].name == "health-mcp"

    @pytest.mark.asyncio
    async def test_local_mode_missing_file_raises(self, tmp_path):
        """When AGENT_ENV=local and MCP_SERVERS_FILE points to a missing file, raise FileNotFoundError."""
        from app.mcp.client import load_mcp_servers

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = str(tmp_path / "nonexistent.yml")

        with patch("app.mcp.client.get_settings", return_value=mock_settings):
            with pytest.raises(FileNotFoundError):
                await load_mcp_servers()

    @pytest.mark.asyncio
    async def test_local_mode_no_file_path_raises(self):
        """When AGENT_ENV=local but MCP_SERVERS_FILE is empty, raise RuntimeError."""
        from app.mcp.client import load_mcp_servers

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = ""

        with patch("app.mcp.client.get_settings", return_value=mock_settings):
            with pytest.raises(RuntimeError, match="MCP_SERVERS_FILE is not defined"):
                await load_mcp_servers()

    @pytest.mark.asyncio
    async def test_prod_mode_reads_redis(self):
        """When AGENT_ENV=prod, must query Redis for the server list."""
        from app.mcp.client import load_mcp_servers
        import json as _json

        redis_data = _json.dumps([
            {"name": "health-mcp", "url": "http://mcp:8999/mcp/", "transport": "streamable_http", "enabled": True}
        ])

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=redis_data)
        mock_redis.aclose = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.agent_env = "prod"
        mock_settings.mcp_config_key = "super_agent:config:mcp_servers:prod:sre:config"
        mock_settings.agent_group = "sre"
        mock_settings.redis_host = "redis-host"
        mock_settings.redis_port = 6379
        mock_settings.redis_username = "user"
        mock_settings.redis_password = "pass"
        mock_settings.redis_ssl = True

        with patch("app.mcp.client.get_settings", return_value=mock_settings), \
             patch("app.mcp.client.RedisCluster", return_value=mock_redis):
            servers = await load_mcp_servers()

        assert len(servers) == 1
        assert servers[0].name == "health-mcp"
        mock_redis.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prod_mode_empty_redis_key_raises(self):
        """When Redis key is absent, raise ValueError."""
        from app.mcp.client import load_mcp_servers

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.agent_env = "prod"
        mock_settings.mcp_config_key = "super_agent:config:mcp_servers:prod:sre:config"
        mock_settings.agent_group = "sre"
        mock_settings.redis_host = "h"
        mock_settings.redis_port = 6379
        mock_settings.redis_username = ""
        mock_settings.redis_password = ""
        mock_settings.redis_ssl = True

        with patch("app.mcp.client.get_settings", return_value=mock_settings), \
             patch("app.mcp.client.RedisCluster", return_value=mock_redis):
            with pytest.raises(ValueError, match="is not set or is empty"):
                await load_mcp_servers()

    @pytest.mark.asyncio
    async def test_required_token_injects_authorization_when_missing(self, tmp_path):
        """required_token=true should inject Bearer token when Authorization is absent."""
        from app.mcp.client import load_mcp_servers

        yml = tmp_path / "servers.yml"
        yml.write_text(
            "servers:\n"
            "  - name: edge-network-mcp\n"
            "    url: http://edge-network-agent.walmart.com/mcp/\n"
            "    transport: streamable_http\n"
            "    enabled: true\n"
            "    required_token: true\n"
            "    headers:\n"
            "      WM_CONSUMER.ID: 690a60d0\n"
        )

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = str(yml)

        with patch("app.mcp.client.get_settings", return_value=mock_settings), \
             patch("app.pingfed.get_hub_token", new=AsyncMock(return_value="hub-jwt-token")):
            servers = await load_mcp_servers()

        assert len(servers) == 1
        assert servers[0].required_token is True
        assert servers[0].headers["WM_CONSUMER.ID"] == "690a60d0"
        assert servers[0].headers["Authorization"] == "Bearer hub-jwt-token"

    @pytest.mark.asyncio
    async def test_required_token_preserves_existing_authorization(self, tmp_path):
        """required_token=true must not overwrite explicitly provided Authorization."""
        from app.mcp.client import load_mcp_servers

        yml = tmp_path / "servers.yml"
        yml.write_text(
            "servers:\n"
            "  - name: edge-network-mcp\n"
            "    url: http://edge-network-agent.walmart.com/mcp/\n"
            "    transport: streamable_http\n"
            "    enabled: true\n"
            "    required_token: true\n"
            "    headers:\n"
            "      Authorization: Bearer explicit-token\n"
        )

        mock_settings = MagicMock()
        mock_settings.agent_env = "local"
        mock_settings.mcp_servers_file = str(yml)

        with patch("app.mcp.client.get_settings", return_value=mock_settings), \
             patch("app.pingfed.get_hub_token", new=AsyncMock(return_value="hub-jwt-token")):
            servers = await load_mcp_servers()

        assert len(servers) == 1
        assert servers[0].headers["Authorization"] == "Bearer explicit-token"


# ---------------------------------------------------------------------------
# TestMCPSession
# ---------------------------------------------------------------------------

class TestMCPSession:
    """Tests for MCPSession."""

    def _make_client(self) -> MagicMock:
        """Return a mock httpx.AsyncClient."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_connect_sets_sid_from_header(self):
        """connect() should store the session ID from the mcp-session-id header."""
        from app.mcp.client import MCPSession

        client = self._make_client()

        init_response = _make_json_response({"result": {}})
        init_response.headers = {"mcp-session-id": "session-xyz", "content-type": "application/json"}
        init_response.raise_for_status = MagicMock()

        notif_response = _make_json_response({})
        notif_response.raise_for_status = MagicMock()

        tools_response = _make_json_response({"result": {"tools": []}})
        tools_response.raise_for_status = MagicMock()

        guide_response = _make_json_response({"result": {"contents": []}})
        guide_response.raise_for_status = MagicMock()

        post_call_count = [0]
        responses = [init_response, notif_response, tools_response, guide_response]

        async def fake_post(url, **kwargs):
            idx = post_call_count[0]
            post_call_count[0] += 1
            return responses[idx] if idx < len(responses) else _make_json_response({})

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp", name="test")
        await session.connect()

        assert session.sid == "session-xyz"

    @pytest.mark.asyncio
    async def test_connect_sends_custom_headers(self):
        """connect() should include configured custom headers in initialize call."""
        from app.mcp.client import MCPSession

        client = self._make_client()

        init_response = _make_json_response({"result": {}})
        init_response.headers = {"mcp-session-id": "session-abc", "content-type": "application/json"}
        init_response.raise_for_status = MagicMock()

        notif_response = _make_json_response({})
        notif_response.raise_for_status = MagicMock()

        tools_response = _make_json_response({"result": {"tools": []}})
        tools_response.raise_for_status = MagicMock()

        resources_response = _make_json_response({"result": {"resources": []}})
        resources_response.raise_for_status = MagicMock()

        prompts_response = _make_json_response({"result": {"prompts": []}})
        prompts_response.raise_for_status = MagicMock()

        captured_headers: list[dict] = []
        responses = [init_response, notif_response, tools_response, resources_response, prompts_response]

        async def fake_post(url, **kwargs):
            captured_headers.append(kwargs.get("headers", {}))
            return responses[len(captured_headers) - 1]

        client.post = fake_post

        session = MCPSession(
            client,
            "http://mcp.example.com/mcp",
            headers={"WM_SVC.NAME": "APM0002050-MCP-JIRA"},
        )
        await session.connect()

        assert captured_headers
        assert captured_headers[0]["WM_SVC.NAME"] == "APM0002050-MCP-JIRA"

    @pytest.mark.asyncio
    async def test_load_tools_populates_oai_and_claude_tools(self):
        """_load_tools() should populate oai_tools and claude_tools from the response."""
        from app.mcp.client import MCPSession

        client = self._make_client()
        tools_data = [
            {
                "name": "get_pods",
                "description": "List pods",
                "inputSchema": {"type": "object", "properties": {"namespace": {"type": "string"}}},
            }
        ]
        tools_response = _make_json_response({"result": {"tools": tools_data}})
        tools_response.raise_for_status = MagicMock()

        async def fake_post(url, **kwargs):
            return tools_response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        await session._load_tools()

        assert len(session.tools) == 1
        assert session.tools[0]["name"] == "get_pods"

        assert len(session.oai_tools) == 1
        assert session.oai_tools[0]["type"] == "function"
        assert session.oai_tools[0]["function"]["name"] == "get_pods"

        assert len(session.claude_tools) == 1
        assert session.claude_tools[0]["name"] == "get_pods"
        assert "input_schema" in session.claude_tools[0]

    @pytest.mark.asyncio
    async def test_load_guide_sets_guide_text(self):
        """_load_guide() should discover guide URIs via resources/list then load each."""
        from app.mcp.client import MCPSession

        client = self._make_client()

        list_response = _make_json_response({
            "result": {
                "resources": [{"uri": "wcnp://agent-guide", "name": "WCNP Guide"}]
            }
        })
        list_response.raise_for_status = MagicMock()

        read_response = _make_json_response({
            "result": {
                "contents": [
                    {"type": "text", "text": "Welcome to WCNP."},
                    {"type": "text", "text": "Use tools wisely."},
                ]
            }
        })
        read_response.raise_for_status = MagicMock()

        responses = iter([list_response, read_response])

        async def fake_post(url, **kwargs):
            return next(responses)

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        await session._load_guide()

        assert "Welcome to WCNP." in session.guide
        assert "Use tools wisely." in session.guide

    @pytest.mark.asyncio
    async def test_load_guide_handles_exception_gracefully(self):
        """_load_guide() should log a warning and not raise on error."""
        from app.mcp.client import MCPSession

        client = self._make_client()

        async def fake_post(url, **kwargs):
            raise RuntimeError("connection refused")

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        await session._load_guide()  # should not raise

        assert session.guide == ""

    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self):
        """call_tool() should return joined text from content list."""
        from app.mcp.client import MCPSession

        client = self._make_client()
        tool_response = _make_json_response({
            "result": {
                "content": [
                    {"type": "text", "text": "pod-a is running"},
                    {"type": "text", "text": "pod-b is running"},
                ]
            }
        })
        tool_response.raise_for_status = MagicMock()

        async def fake_post(url, **kwargs):
            return tool_response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_tool("get_pods", {"namespace": "default"})

        assert "pod-a is running" in result
        assert "pod-b is running" in result

    @pytest.mark.asyncio
    async def test_call_tool_returns_json_when_no_content(self):
        """call_tool() should JSON-serialize the result when content list is empty."""
        from app.mcp.client import MCPSession

        client = self._make_client()
        raw_result = {"status": "ok", "count": 3}
        tool_response = _make_json_response({"result": raw_result})
        tool_response.raise_for_status = MagicMock()

        async def fake_post(url, **kwargs):
            return tool_response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_tool("check_status", {})

        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["count"] == 3

    @pytest.mark.asyncio
    async def test_call_tool_reconnects_on_failure(self):
        """call_tool() should reconnect and retry when the first call raises."""
        from app.mcp.client import MCPSession

        client = self._make_client()

        call_count = [0]

        init_response = _make_json_response({"result": {}})
        init_response.headers = {"content-type": "application/json"}
        init_response.raise_for_status = MagicMock()

        notif_response = _make_json_response({})
        notif_response.raise_for_status = MagicMock()

        tools_response = _make_json_response({"result": {"tools": []}})
        tools_response.raise_for_status = MagicMock()

        guide_response = _make_json_response({"result": {"contents": []}})
        guide_response.raise_for_status = MagicMock()

        success_response = _make_json_response({
            "result": {"content": [{"type": "text", "text": "retry success"}]}
        })
        success_response.raise_for_status = MagicMock()

        reconnect_responses = [init_response, notif_response, tools_response, guide_response, success_response]
        reconnect_idx = [0]

        async def fake_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("network error")
            idx = reconnect_idx[0]
            reconnect_idx[0] += 1
            return reconnect_responses[idx] if idx < len(reconnect_responses) else success_response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_tool("my_tool", {"arg": "val"})

        assert "retry success" in result

    @pytest.mark.asyncio
    async def test_call_tool_returns_error_string_on_double_failure(self):
        """call_tool() should return an error string when both attempts fail."""
        from app.mcp.client import MCPSession

        client = self._make_client()

        async def fake_post(url, **kwargs):
            raise RuntimeError("always fails")

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_tool("broken_tool", {})

        assert result.startswith("Tool error:")


# ---------------------------------------------------------------------------
# TestMCPPool
# ---------------------------------------------------------------------------

class TestMCPPool:
    """Tests for MCPPool."""

    def _make_session(self, name: str, url: str, tools: list, guide: str = "") -> MagicMock:
        """Return a mock MCPSession."""
        session = MagicMock()
        session._name = name
        session._url = url
        session.tools = tools
        session.oai_tools = [
            {"type": "function", "function": {"name": t["name"], "description": "", "parameters": {}}}
            for t in tools
        ]
        session.claude_tools = [
            {"name": t["name"], "description": "", "input_schema": {}}
            for t in tools
        ]
        session.guide = guide
        session.connect = AsyncMock()
        session.call_tool = AsyncMock(return_value="mock tool result")
        return session

    @pytest.mark.asyncio
    async def test_connect_merges_tools_from_multiple_sessions(self):
        """connect() should aggregate tools from all connected sessions."""
        from app.mcp.client import MCPPool

        s1 = self._make_session("s1", "http://s1.com", [{"name": "tool_a"}])
        s2 = self._make_session("s2", "http://s2.com", [{"name": "tool_b"}, {"name": "tool_c"}])

        pool = MCPPool([s1, s2])
        await pool.connect()

        tool_names = {t["name"] for t in pool.tools}
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names
        assert "tool_c" in tool_names

    @pytest.mark.asyncio
    async def test_connect_combines_all_guides(self):
        """connect() should concatenate guides from ALL sessions that have one."""
        from app.mcp.client import MCPPool

        s1 = self._make_session("s1", "http://s1.com", [], guide="Guide from s1")
        s2 = self._make_session("s2", "http://s2.com", [], guide="Guide from s2")

        pool = MCPPool([s1, s2])
        await pool.connect()

        assert "Guide from s1" in pool.guide
        assert "Guide from s2" in pool.guide

    @pytest.mark.asyncio
    async def test_connect_skips_failed_sessions(self):
        """connect() should continue and not raise when a session fails to connect."""
        from app.mcp.client import MCPPool

        s1 = self._make_session("s1", "http://s1.com", [{"name": "tool_ok"}])
        s2 = self._make_session("s2", "http://s2.com", [{"name": "tool_bad"}])
        s2.connect = AsyncMock(side_effect=RuntimeError("connection refused"))

        pool = MCPPool([s1, s2])
        await pool.connect()  # should not raise

        tool_names = {t["name"] for t in pool.tools}
        assert "tool_ok" in tool_names
        assert "tool_bad" not in tool_names

    @pytest.mark.asyncio
    async def test_call_tool_routes_to_correct_session(self):
        """call_tool() should delegate to the session that owns the tool."""
        from app.mcp.client import MCPPool

        s1 = self._make_session("s1", "http://s1.com", [{"name": "tool_a"}])
        s2 = self._make_session("s2", "http://s2.com", [{"name": "tool_b"}])
        s1.call_tool = AsyncMock(return_value="result from s1")
        s2.call_tool = AsyncMock(return_value="result from s2")

        pool = MCPPool([s1, s2])
        await pool.connect()

        result = await pool.call_tool("tool_a", {"x": 1})
        assert result == "result from s1"
        s1.call_tool.assert_awaited_once_with("tool_a", {"x": 1})
        s2.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_tool_returns_error_for_unknown_tool(self):
        """call_tool() should return an error string when tool is not found."""
        from app.mcp.client import MCPPool

        pool = MCPPool([])
        await pool.connect()

        result = await pool.call_tool("nonexistent_tool", {})
        assert "nonexistent_tool" in result
        assert "not found" in result.lower() or "Error" in result

    def test_servers_property_returns_name_and_url(self):
        """servers property should return list of dicts with name and url."""
        from app.mcp.client import MCPPool

        s1 = self._make_session("alpha", "http://alpha.com/mcp", [])
        s2 = self._make_session("beta", "http://beta.com/mcp", [])

        pool = MCPPool([s1, s2])

        servers = pool.servers
        assert len(servers) == 2
        assert {"name": "alpha", "url": "http://alpha.com/mcp"} in servers
        assert {"name": "beta", "url": "http://beta.com/mcp"} in servers

    @pytest.mark.asyncio
    async def test_connect_merges_oai_and_claude_tools(self):
        """connect() should merge oai_tools and claude_tools across sessions."""
        from app.mcp.client import MCPPool

        s1 = self._make_session("s1", "http://s1.com", [{"name": "tool_x"}])
        s2 = self._make_session("s2", "http://s2.com", [{"name": "tool_y"}])

        pool = MCPPool([s1, s2])
        await pool.connect()

        oai_names = {t["function"]["name"] for t in pool.oai_tools}
        claude_names = {t["name"] for t in pool.claude_tools}
        assert oai_names == {"tool_x", "tool_y"}
        assert claude_names == {"tool_x", "tool_y"}


# ---------------------------------------------------------------------------
# TestMCPSessionLoadGuideException  (lines 300-301)
# ---------------------------------------------------------------------------

class TestMCPSessionLoadGuideException:
    """Cover the per-URI exception handler in _load_guide() — lines 300-301."""

    @pytest.mark.asyncio
    async def test_load_guide_skips_failed_uri_and_loads_remaining(self):
        """When one guide URI fails, the exception is swallowed and others still load."""
        from app.mcp.client import MCPSession

        client = MagicMock()

        # resources/list returns two guide URIs that match the '://agent-guide' pattern
        list_response = _make_json_response({
            "result": {
                "resources": [
                    {"uri": "wcnp://agent-guide", "name": "Guide A"},
                    {"uri": "custom://agent-guide", "name": "Guide B"},
                ]
            }
        })
        list_response.raise_for_status = MagicMock()

        # First read fails; second succeeds
        fail_response = MagicMock()
        fail_response.raise_for_status = MagicMock(side_effect=RuntimeError("read failed"))
        fail_response.headers = {"content-type": "application/json"}
        fail_response.json.side_effect = RuntimeError("read failed")
        fail_response.text = ""

        ok_response = _make_json_response({
            "result": {"contents": [{"type": "text", "text": "Good guide content"}]}
        })
        ok_response.raise_for_status = MagicMock()

        call_count = [0]
        async def fake_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return list_response
            elif call_count[0] == 2:
                raise RuntimeError("network error on first guide")
            else:
                return ok_response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        await session._load_guide()  # must not raise

        # Good content from second URI must still be present
        assert "Good guide content" in session.guide


# ---------------------------------------------------------------------------
# TestMCPSessionCallPrompt  (lines 319-320)
# ---------------------------------------------------------------------------

class TestMCPSessionCallPrompt:
    """Cover call_prompt() — including the str-content branch (lines 319-320)."""

    @pytest.mark.asyncio
    async def test_call_prompt_with_string_content(self):
        """When message content is a plain string, it must be appended — line 319-320."""
        from app.mcp.client import MCPSession

        client = MagicMock()

        response = _make_json_response({
            "result": {
                "messages": [
                    {"role": "user", "content": "You are a helpful assistant."},
                    {"role": "assistant", "content": {"type": "text", "text": "Ready to help."}},
                ]
            }
        })
        response.raise_for_status = MagicMock()

        async def fake_post(url, **kwargs):
            return response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_prompt("my_prompt", {"arg": "val"})

        # Both parts must appear: plain string and dict text
        assert "You are a helpful assistant." in result
        assert "Ready to help." in result

    @pytest.mark.asyncio
    async def test_call_prompt_returns_error_on_exception(self):
        """When _rpc raises, call_prompt must return a 'Prompt unavailable' string."""
        from app.mcp.client import MCPSession

        client = MagicMock()

        async def fake_post(url, **kwargs):
            raise RuntimeError("timeout")

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_prompt("bad_prompt", {})

        assert result.startswith("Prompt unavailable:")

    @pytest.mark.asyncio
    async def test_call_prompt_with_only_dict_content(self):
        """When all message content is dict-shaped, only dict text is returned."""
        from app.mcp.client import MCPSession

        client = MagicMock()

        response = _make_json_response({
            "result": {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "System context."}},
                ]
            }
        })
        response.raise_for_status = MagicMock()

        async def fake_post(url, **kwargs):
            return response

        client.post = fake_post

        session = MCPSession(client, "http://mcp.example.com/mcp")
        result = await session.call_prompt("dict_prompt", {})

        assert "System context." in result
