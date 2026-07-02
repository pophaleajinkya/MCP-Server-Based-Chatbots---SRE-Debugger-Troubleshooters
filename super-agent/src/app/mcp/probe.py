"""MCP server probe — diagnostic tool to inspect a live MCP server.

Connects to the configured MCP server and lists all tools, resources,
and prompts it exposes. No tool calls are made — read-only inspection only.

Usage:
    python -m app.mcp.probe [MCP_URL]
  or
    python src/app/mcp/probe.py https://your-mcp-server/mcp/

If no URL is provided, defaults to http://localhost:8999/mcp.
"""

import asyncio
import logging
import sys

import httpx
from dotenv import load_dotenv

from app.logging import setup_logging
from app.mcp.client import MCP_HDRS, _parse_mcp_response

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_MCP_URL = "http://localhost:8999/mcp"


def _get_mcp_url() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_MCP_URL


async def _rpc(
    client: httpx.AsyncClient,
    mcp_url: str,
    method: str,
    params: dict,
    req_id: int,
    session_id: str | None = None,
) -> tuple[dict, dict]:
    """Send a JSON-RPC request and return (parsed_response, response_headers)."""
    hdrs = dict(MCP_HDRS)
    if session_id:
        hdrs["Mcp-Session-Id"] = session_id

    r = await client.post(
        mcp_url,
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
        headers=hdrs,
        timeout=10,
    )
    r.raise_for_status()
    return _parse_mcp_response(r), dict(r.headers)


def _section(title: str):
    logger.info("\n%s", "─" * 62)
    logger.info("  %s", title)
    logger.info("%s", "─" * 62)


async def probe():
    mcp_url = _get_mcp_url()
    logger.info("MCP server: %s", mcp_url)

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # ── Initialize ────────────────────────────────────────────────────────
        try:
            resp, resp_hdrs = await _rpc(client, mcp_url, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities":    {},
                "clientInfo":      {"name": "wibey-probe", "version": "1.0"},
            }, req_id=1)
        except Exception as exc:
            logger.error("initialize failed: %s", exc)
            sys.exit(1)

        if "error" in resp:
            logger.error("initialize error: %s", resp["error"])
            sys.exit(1)

        result = resp.get("result", {})
        proto  = result.get("protocolVersion", "?")
        sinfo  = result.get("serverInfo", {})
        caps   = result.get("capabilities", {})

        session_id: str | None = (
            resp_hdrs.get("mcp-session-id") or
            resp_hdrs.get("Mcp-Session-Id") or
            result.get("sessionId")
        )

        logger.info("Connected  |  protocol=%s  |  server=%s %s", proto, sinfo.get("name", "?"), sinfo.get("version", ""))
        logger.info("capabilities: %s", list(caps.keys()))
        if session_id:
            logger.info("session-id: %s", session_id)

        # Send initialized notification (required by spec)
        try:
            await client.post(mcp_url, json={
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
            }, headers={**MCP_HDRS, **({"Mcp-Session-Id": session_id} if session_id else {})}, timeout=5)
        except Exception:
            pass

        # ── Tools ─────────────────────────────────────────────────────────────
        _section("TOOLS")
        try:
            r, _ = await _rpc(client, mcp_url, "tools/list", {}, req_id=2, session_id=session_id)
            tools = r.get("result", {}).get("tools", [])
            logger.info("Total: %d", len(tools))
            for t in tools:
                schema    = t.get("inputSchema", {})
                props     = list(schema.get("properties", {}).keys())
                required  = schema.get("required", [])
                param_str = ", ".join(f"{p}*" if p in required else p for p in props)
                logger.info("  * %s(%s)", t["name"], param_str)
                if t.get("description"):
                    logger.info("      %s", t["description"][:110])
        except Exception as exc:
            logger.warning("tools/list failed: %s", exc)

        # ── Resources ─────────────────────────────────────────────────────────
        _section("RESOURCES")
        try:
            r, _ = await _rpc(client, mcp_url, "resources/list", {}, req_id=3, session_id=session_id)
            resources = r.get("result", {}).get("resources", [])
            logger.info("Total: %d", len(resources))
            for res in resources:
                mime = f"  [{res.get('mimeType', '')}]" if res.get("mimeType") else ""
                logger.info("  * %s%s", res.get("uri", "?"), mime)
                if res.get("name"):
                    logger.info("      name: %s", res["name"])
                if res.get("description"):
                    logger.info("      %s", res["description"][:110])
        except Exception as exc:
            logger.warning("resources/list failed: %s", exc)

        # ── Prompts ───────────────────────────────────────────────────────────
        _section("PROMPTS")
        try:
            r, _ = await _rpc(client, mcp_url, "prompts/list", {}, req_id=4, session_id=session_id)
            prompts = r.get("result", {}).get("prompts", [])
            logger.info("Total: %d", len(prompts))
            for p in prompts:
                args = ", ".join(
                    f"{a['name']}{'*' if a.get('required') else ''}"
                    for a in p.get("arguments", [])
                )
                logger.info("  * %s(%s)", p["name"], args)
                if p.get("description"):
                    logger.info("      %s", p["description"][:110])
        except Exception as exc:
            logger.warning("prompts/list failed: %s", exc)

    logger.info("%s", "─" * 62)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(probe())
