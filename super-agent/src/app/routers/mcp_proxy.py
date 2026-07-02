"""MCP proxy endpoint for MCP Apps iframe widgets.

Forwards JSON-RPC requests from sandboxed iframe widgets to the correct
MCP server in the pool. The iframe sends requests via the UI's /api/mcp-proxy,
which forwards them here, and this endpoint forwards to the actual MCP server.

Supports: tools/call, resources/read, resources/list, prompts/list, prompts/get
"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(tags=["MCP Proxy"])


@router.post(
    "/mcp-proxy",
    summary="Proxy MCP JSON-RPC requests from iframe widgets to MCP servers",
)
async def mcp_proxy(request: Request) -> JSONResponse:
    """Forward a JSON-RPC request from an MCP Apps iframe to the MCP pool.

    The request body must include:
    - method: MCP JSON-RPC method (tools/call, resources/read, etc.)
    - params: Method-specific parameters
    - serverName: (optional) Target MCP server name for routing
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    method = body.get("method", "")
    params = body.get("params", {})

    mcp_pool = request.app.state.mcp_pool

    try:
        if method == "tools/list":
            all_tools = []
            for session in mcp_pool._sessions:
                for tool in session.tools:
                    all_tools.append(tool)
            return JSONResponse({"result": {"tools": all_tools}})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            if not tool_name:
                return JSONResponse({"error": "Missing tool name"}, status_code=400)
            log.info("MCP proxy: tools/call %s(%s)", tool_name, json.dumps(arguments)[:120])
            result = await mcp_pool.call_tool(tool_name, arguments)
            return JSONResponse({"result": {"content": [{"type": "text", "text": result}]}})

        elif method == "resources/read":
            uri = params.get("uri", "")
            if not uri:
                return JSONResponse({"error": "Missing resource URI"}, status_code=400)
            for session in mcp_pool._sessions:
                try:
                    resp = await session._rpc("resources/read", {"uri": uri}, req_id=100)
                    return JSONResponse({"result": resp.get("result", {})})
                except Exception as exc:
                    log.debug("resources/read failed on %s: %s", session._name, exc)
                    continue
            return JSONResponse({"error": f"Resource not found: {uri}"}, status_code=404)

        elif method == "resources/list":
            for session in mcp_pool._sessions:
                try:
                    resp = await session._rpc("resources/list", {}, req_id=101)
                    return JSONResponse({"result": resp.get("result", {})})
                except Exception as exc:
                    log.debug("resources/list failed on %s: %s", session._name, exc)
                    continue
            return JSONResponse({"result": {"resources": []}})

        elif method == "prompts/list":
            for session in mcp_pool._sessions:
                try:
                    resp = await session._rpc("prompts/list", {}, req_id=102)
                    return JSONResponse({"result": resp.get("result", {})})
                except Exception as exc:
                    log.debug("prompts/list failed on %s: %s", session._name, exc)
                    continue
            return JSONResponse({"result": {"prompts": []}})

        elif method == "prompts/get":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await mcp_pool.call_prompt(name, arguments)
            return JSONResponse({"result": {"content": [{"type": "text", "text": result}]}})

        else:
            return JSONResponse({"error": f"Unsupported method: {method}"}, status_code=400)

    except Exception as exc:
        log.error("MCP proxy error [%s]: %s", method, exc)
        return JSONResponse({"error": f"Internal proxy error: {exc}"}, status_code=502)
