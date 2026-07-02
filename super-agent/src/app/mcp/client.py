"""MCP client — JSON-RPC session management over Streamable HTTP.

Provides:
  MCPServerConfig  — dataclass describing a single MCP server entry
  load_mcp_servers — loads server list from Redis key ``agent:mcp_servers``
  MCPSession       — persistent JSON-RPC session for one MCP server
  MCPPool          — aggregates multiple sessions and routes tool calls
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from redis.asyncio.cluster import ClusterNode, RedisCluster

from app.config import get_settings

log = logging.getLogger(__name__)

MCP_HDRS = {
    "Content-Type": "application/json",
    "Accept":       "application/json, text/event-stream",
}


def _parse_mcp_response(r: httpx.Response) -> dict:
    ct = r.headers.get("content-type", "")
    if "text/event-stream" in ct:
        for line in r.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}
    return r.json()


@dataclass
class MCPServerConfig:
    name: str
    url: str
    transport: str = "streamable_http"
    enabled: bool = True
    headers: dict = field(default_factory=dict)
    required_token: bool = False
    description: str = ""


_VALID_TRANSPORTS = {"streamable_http", "sse", "stdio"}
_REQUIRED_FIELDS  = {"name", "url", "transport", "enabled"}


def _parse_required_token(value: Any, index: int, source: str) -> bool:
    """Parse required_token from config and return a strict bool value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(
        f"MCP server entry [{index}] in {source} has invalid required_token={value!r}. "
        "Use true or false"
    )


def _normalize_headers(value: Any, index: int, source: str) -> dict[str, str]:
    """Validate and normalize headers to a string:string dict."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(
            f"MCP server entry [{index}] in {source} has invalid headers={type(value).__name__!r}. "
            "headers must be a JSON/YAML object"
        )

    normalized: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(
                f"MCP server entry [{index}] in {source} has non-string header {k!r}: {v!r}. "
                "All header keys and values must be strings"
            )
        normalized[k] = v
    return normalized


def _has_authorization_header(headers: dict[str, str]) -> bool:
    """Return True when headers already contain Authorization (any casing)."""
    return any(k.lower() == "authorization" for k in headers)


def _validate_and_parse(entries: list[dict], source: str) -> list[MCPServerConfig]:
    """Validate a list of raw server-config dicts and return enabled MCPServerConfig objects.

    Raises:
        ValueError: if any enabled entry is missing required fields or has an
                    unrecognised transport value.
    """
    if not entries:
        raise ValueError(f"MCP config from {source} is empty — no server entries found")

    configs: list[MCPServerConfig] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"MCP server entry [{i}] in {source} is {type(entry).__name__!r}, expected object"
            )
        missing = _REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(
                f"MCP server entry [{i}] in {source} is missing required fields: {sorted(missing)}"
            )
        transport = entry["transport"]
        if transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"MCP server entry [{i}] '{entry['name']}' has invalid transport={transport!r}. "
                f"Must be one of {sorted(_VALID_TRANSPORTS)}"
            )
        if entry.get("enabled"):
            parsed = dict(entry)
            parsed["headers"] = _normalize_headers(entry.get("headers", {}), i, source)
            parsed["required_token"] = _parse_required_token(
                entry.get("required_token", False), i, source,
            )
            configs.append(MCPServerConfig(**parsed))

    if not configs:
        raise ValueError(
            f"MCP config from {source} has entries but none are enabled — "
            "set enabled: true on at least one server"
        )
    return configs


def _load_from_file(path: str) -> list[dict]:
    """Read and parse a YAML MCP servers file.  Raises on any problem."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"MCP_SERVERS_FILE not found: {path} — "
            "create the file or point MCP_SERVERS_FILE at an existing YAML config"
        )
    try:
        with p.open() as f:
            doc = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"YAML syntax error in '{path}': {exc}"
        ) from exc
    if not doc:
        raise ValueError(
            f"MCP_SERVERS_FILE '{path}' is empty — "
            "add at least one server entry (see mcp_servers.yml.example)"
        )
    entries = doc.get("mcp_servers", doc.get("servers"))
    if not entries:
        raise ValueError(
            f"MCP_SERVERS_FILE '{path}' has no 'mcp_servers' key or the list is empty"
        )
    return entries


async def _load_from_redis(key: str, s) -> list[dict]:
    """Read and parse the MCP servers JSON from a Redis key.  Raises on any problem."""
    redis: RedisCluster = RedisCluster(
        startup_nodes=[ClusterNode(s.redis_host, s.redis_port)],
        username=s.redis_username or None,
        password=s.redis_password,
        decode_responses=True,
        ssl=s.redis_ssl,
        ssl_cert_reqs=None,
        socket_connect_timeout=5,
        socket_timeout=10,
    )
    try:
        raw = await redis.get(key)
        if not raw:
            raise ValueError(
                f"Redis key '{key}' is not set or is empty — "
                "populate it with a JSON array of MCP server configs"
            )
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON syntax error in Redis key '{key}': {exc}"
            ) from exc
        if not entries:
            raise ValueError(f"Redis key '{key}' contains an empty list — no MCP servers defined")
        return entries
    finally:
        await redis.aclose()


def _load_mcp_servers_from_file(path: str) -> list[MCPServerConfig]:
    """Convenience wrapper: load + validate a YAML file → list of MCPServerConfig.

    Used by tests and dev tooling. Production code should call load_mcp_servers().
    """
    entries = _load_from_file(path)
    return _validate_and_parse(entries, source=path)


async def load_mcp_servers() -> list[MCPServerConfig]:
    """Load, validate, and return enabled MCP server configs.

    **Local mode** (``AGENT_ENV=local``):
      - ``MCP_SERVERS_FILE`` must be set → raises ``RuntimeError`` if missing.
      - File must exist → raises ``FileNotFoundError`` if absent.
      - File must be non-empty with valid entries → raises ``ValueError`` if not.

    **All other environments** (dev, stage, prod, etc.):
      - Redis key is derived from ``AGENT_ENV`` and ``AGENT_GROUP``:
        ``super_agent:config:mcp_servers:<agent_env>:<agent_group>:config``
      - Redis key must exist and be non-empty → raises ``ValueError`` if not.
      - JSON must contain valid, enabled entries → raises ``ValueError`` if not.

    Called **once at startup** — no periodic refresh.
    Raises on any configuration or connectivity problem so startup fails fast.
    """
    s = get_settings()

    try:
        return await _do_load_mcp_servers(s)
    except Exception as exc:
        source = (
            f"file '{s.mcp_servers_file}'"
            if s.agent_env.lower() == "local"
            else f"Redis key '{s.mcp_config_key}' (env={s.agent_env}, group={s.agent_group})"
        )
        log.critical(
            "\n##########################################################################\n"
            "# STARTUP FAILURE — MCP server config could not be loaded\n"
            "#\n"
            "# Source : %s\n"
            "# Reason : %s\n"
            "#\n"
            "# Fix    : Check your MCP servers config for errors\n"
            "#           (bad YAML indentation, invalid JSON in Redis,\n"
            "#            missing keys, connection timeouts, etc.)\n"
            "##########################################################################",
            source, exc,
        )
        raise


async def _do_load_mcp_servers(s) -> list[MCPServerConfig]:
    """Internal loader — called by load_mcp_servers() which wraps with error logging."""

    # ── Local mode: YAML file ─────────────────────────────────────────────────
    if s.agent_env.lower() == "local":
        if not s.mcp_servers_file:
            raise RuntimeError(
                "AGENT_ENV=local is set but MCP_SERVERS_FILE is not defined in .env — "
                "set MCP_SERVERS_FILE to the path of your local mcp_servers.yml"
            )
        log.info("[local] Loading MCP servers from file: %s", s.mcp_servers_file)
        entries = _load_from_file(s.mcp_servers_file)
        configs = _validate_and_parse(entries, source=s.mcp_servers_file)
        configs = await _apply_required_auth_headers(configs)
        log.info("[local] %d enabled MCP server(s) loaded from file", len(configs))
        for srv in configs:
            log.info("  server: name=%r  url=%r  transport=%r", srv.name, srv.url, srv.transport)
        return configs

    # ── Redis mode (dev / stage / prod) ─────────────────────────────────────────
    redis_key = s.mcp_config_key  # computed: super_agent:config:mcp_servers:<env>:<group>:config
    log.info(
        "[prod] Loading MCP servers — env=%r group=%r redis_key=%r",
        s.agent_env, s.agent_group, redis_key,
    )
    entries = await _load_from_redis(redis_key, s)
    configs = _validate_and_parse(entries, source=f"Redis key '{redis_key}'")
    configs = await _apply_required_auth_headers(configs)
    log.info("[prod] %d enabled MCP server(s) loaded from Redis", len(configs))
    for srv in configs:
        log.info("  server: name=%r  url=%r  transport=%r", srv.name, srv.url, srv.transport)
    return configs


async def _apply_required_auth_headers(configs: list[MCPServerConfig]) -> list[MCPServerConfig]:
    """Inject Authorization headers for MCP servers that require a shared hub token."""
    needs_token = [cfg for cfg in configs if cfg.required_token]
    if not needs_token:
        return configs

    hub_token: str | None = None
    for cfg in needs_token:
        if _has_authorization_header(cfg.headers):
            log.info(
                "MCP [%s]: required_token=true but Authorization header already provided — preserving configured value",
                cfg.name,
            )
            continue

        if hub_token is None:
            try:
                from app.pingfed import get_hub_token
            except ImportError as exc:
                raise RuntimeError(
                    "MCP server config requires required_token=true but app.pingfed.get_hub_token is unavailable"
                ) from exc

            hub_token = (await get_hub_token()).strip()
            if not hub_token:
                raise RuntimeError(
                    "MCP server config requires required_token=true but no hub bearer token could be resolved"
                )

        cfg.headers["Authorization"] = f"Bearer {hub_token}"
        log.info("MCP [%s]: injected Authorization header from shared hub token", cfg.name)

    return configs


class MCPSession:
    """Persistent MCP session for a single server — initialise once, reuse for all calls."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str,
        name: str = "mcp",
        headers: dict[str, str] | None = None,
    ):
        self._c    = client
        self._url  = url
        self._name = name
        self._headers = dict(headers or {})
        self.sid  : str | None = None
        self.tools: list[dict] = []
        self.oai_tools: list[dict] = []    # OpenAI function-calling format
        self.claude_tools: list[dict] = [] # Anthropic tool format
        self.guide: str = ""               # wcnp://agent-guide resource content
        self.prompts: list[dict] = []      # MCP prompts

    def _hdrs(self, *, include_session: bool = True) -> dict:
        h = {**MCP_HDRS, **self._headers}
        if include_session and self.sid:
            h["Mcp-Session-Id"] = self.sid
        return h

    async def _rpc(self, method: str, params: dict, req_id: int) -> dict:
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        r = await self._c.post(self._url, json=payload, headers=self._hdrs(), timeout=15)
        r.raise_for_status()
        return _parse_mcp_response(r)

    async def connect(self):
        r = await self._c.post(self._url, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities":    {},
                "clientInfo":      {"name": "a2a-health-agent", "version": "1.0"},
            },
        }, headers=self._hdrs(include_session=False), timeout=10)
        r.raise_for_status()
        resp = _parse_mcp_response(r)

        result = resp.get("result", {})
        self.sid = (
            r.headers.get("mcp-session-id") or
            r.headers.get("Mcp-Session-Id") or
            result.get("sessionId")
        )

        try:
            await self._c.post(self._url, json={
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
            }, headers=self._hdrs(), timeout=5)
        except Exception:
            pass

        sinfo = result.get("serverInfo", {})
        log.info("[%s] MCP connected: %s %s (session=%s)", self._name, sinfo.get("name"), sinfo.get("version"), self.sid)

        await self._load_tools()
        await self._load_guide()
        await self._load_prompts()

    async def _load_tools(self):
        resp = await self._rpc("tools/list", {}, req_id=1)
        self.tools = resp.get("result", {}).get("tools", [])
        self.oai_tools = [
            {
                "type": "function",
                "function": {
                    "name":        t["name"],
                    "description": t.get("description", ""),
                    "parameters":  t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
            for t in self.tools
        ]
        self.claude_tools = [
            {
                "name":         t["name"],
                "description":  t.get("description", ""),
                "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
            }
            for t in self.tools
        ]
        log.info("[%s] MCP tools loaded: %s", self._name, [t["name"] for t in self.tools])

    async def _load_guide(self):
        """Discover and load all agent-guide resources from this MCP server.

        Any resource whose URI ends with '://agent-guide' is treated as a
        domain knowledge guide and concatenated into self.guide.  This means
        a new MCP server only needs to expose a '<scheme>://agent-guide'
        resource — no changes to the agent code required.
        """
        try:
            list_resp  = await self._rpc("resources/list", {}, req_id=2)
            resources  = list_resp.get("result", {}).get("resources", [])
            guide_uris = [r["uri"] for r in resources if str(r.get("uri", "")).endswith("://agent-guide")]
        except Exception as exc:
            log.warning("[%s] Could not list resources: %s", self._name, exc)
            return

        parts: list[str] = []
        for uri in guide_uris:
            try:
                resp     = await self._rpc("resources/read", {"uri": uri}, req_id=3)
                contents = resp.get("result", {}).get("contents", [])
                text     = "\n".join(c.get("text", "") for c in contents if "text" in c)
                if text:
                    parts.append(text)
                    log.info("[%s] Guide loaded: %s (%d chars)", self._name, uri, len(text))
            except Exception as exc:
                log.warning("[%s] Could not load guide %s: %s", self._name, uri, exc)

        self.guide = "\n\n".join(parts)

    async def _load_prompts(self):
        """Discover and load all prompts from this MCP server."""
        try:
            resp = await self._rpc("prompts/list", {}, req_id=4)
            self.prompts = resp.get("result", {}).get("prompts", [])
            log.info("[%s] MCP prompts loaded: %d", self._name, len(self.prompts))
        except Exception as exc:
            log.warning("[%s] Could not list prompts: %s", self._name, exc)

    async def call_prompt(self, name: str, arguments: dict | None = None) -> str:
        """Call a named MCP prompt template and return its rendered text."""
        try:
            resp = await self._rpc(
                "prompts/get",
                {"name": name, "arguments": arguments or {}},
                req_id=50,
            )
            messages = resp.get("result", {}).get("messages", [])
            parts = []
            for msg in messages:
                content = msg.get("content", {})
                if isinstance(content, dict):
                    parts.append(content.get("text", ""))
                elif isinstance(content, str):
                    parts.append(content)
            return "\n\n".join(p for p in parts if p)
        except Exception as exc:
            log.warning("MCP prompt error (%s): %s", name, exc)
            return f"Prompt unavailable: {exc}"

    async def call_tool(self, name: str, arguments: dict) -> str:
        log.info("MCP tool call: %s(%s)", name, json.dumps(arguments)[:120])
        try:
            resp = await self._rpc("tools/call", {"name": name, "arguments": arguments}, req_id=99)
            result = resp.get("result", {})
            contents = result.get("content", [])
            if contents:
                parts = [c.get("text", "") if c.get("type") == "text" else json.dumps(c) for c in contents]
                text_result = "\n".join(parts)
            else:
                text_result = json.dumps(result)
            log.info("MCP tool result (%s): %s", name, text_result[:300])
            return text_result
        except Exception as exc:
            log.warning("MCP tool error (%s): %s — attempting reconnect", name, exc)
            try:
                await self.connect()
                resp = await self._rpc("tools/call", {"name": name, "arguments": arguments}, req_id=99)
                result = resp.get("result", {})
                contents = result.get("content", [])
                if contents:
                    return "\n".join(c.get("text", json.dumps(c)) for c in contents)
                return json.dumps(result)
            except Exception as exc2:
                return f"Tool error: {exc2}"


class MCPPool:
    """Aggregates multiple MCPSessions and routes tool calls to the owning session."""

    def __init__(self, sessions: list[MCPSession]):
        self._sessions             = sessions
        self._tool_session_map: dict[str, MCPSession] = {}
        self.tools      : list[dict] = []
        self.oai_tools  : list[dict] = []
        self.claude_tools: list[dict] = []
        self.prompts: list[dict] = []
        self.guide: str = ""
        self.failed_servers: list[dict] = []   # {"name": ..., "url": ..., "error": ...}

    async def connect(self):
        for session in self._sessions:
            try:
                await session.connect()
                for t in session.tools:
                    self._tool_session_map[t["name"]] = session
                self.tools.extend(session.tools)
                self.oai_tools.extend(session.oai_tools)
                self.claude_tools.extend(session.claude_tools)
                self.prompts.extend(session.prompts)
                # Collect guides from ALL connected MCP servers.
                # Each MCP owns its domain knowledge — combining them gives the
                # agent a complete routing table across all domains.
                if session.guide:
                    self.guide = (self.guide + "\n\n---\n\n" + session.guide).strip()
            except Exception as exc:
                log.error("Failed to connect MCP server [%s]: %s", session._name, exc)
                self.failed_servers.append({"name": session._name, "url": session._url, "error": str(exc)})

    async def call_tool(self, name: str, arguments: dict) -> str:
        session = self._tool_session_map.get(name)
        if not session:
            return f"Error: tool '{name}' not found in any connected MCP server"
        return await session.call_tool(name, arguments)

    async def call_prompt(self, name: str, arguments: dict | None = None) -> str:
        """Call a named MCP prompt across all sessions (tries each until one responds)."""
        for session in self._sessions:
            if session._name not in {f["name"] for f in self.failed_servers}:
                result = await session.call_prompt(name, arguments)
                if not result.startswith("Prompt unavailable"):
                    return result
        return f"Prompt '{name}' not found in any connected MCP server"

    @property
    def servers(self) -> list[dict]:
        return [{"name": s._name, "url": s._url} for s in self._sessions]

    def generate_faqs(self) -> list[dict]:
        """
        Dynamically generate FAQs based on MCP prompts and tools.
        
        This will inspect self.prompts and self.claude_tools (which were loaded during connect)
        and build a structured list of FAQs.
        """
        faqs = []
        
        # 1. Group prompts by Server/Namespace (e.g. maof_deployments-ask_crq -> maof_deployments)
        prompts_by_group = {}
        for p in self.prompts:
            name = p.get("name", "unknown")
            desc = p.get("description", f"Use {name}")
            parts = name.split("-", 1)
            group = parts[0] if len(parts) > 1 else "Agent Capabilities"
            
            if group not in prompts_by_group:
                prompts_by_group[group] = {
                    "title": group.replace("_", " ").title(),
                    "description": f"Prompts related to {group}",
                    "faqs": []
                }
            
            prompts_by_group[group]["faqs"].append(desc)
            
        for g_data in prompts_by_group.values():
            if g_data["faqs"]:
                faqs.append(g_data)
                
        # 2. Add Tools as another group
        tool_faqs = []
        for tool in self.claude_tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            # Clean up desc if it's too long
            desc_short = desc.split("\n")[0][:100]
            if name and desc_short:
                tool_faqs.append(f"How to use {name}? ({desc_short})")
                
        if tool_faqs:
            faqs.append({
                "title": "Agent Tools",
                "description": "Available backend tools you can use",
                "faqs": tool_faqs
            })
            
        return faqs
