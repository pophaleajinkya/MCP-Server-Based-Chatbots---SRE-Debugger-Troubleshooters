"""
Valid8 MCP Server — ASGI entry point.

  POST /mcp                        → MCP protocol (streamable HTTP, stateless)
  GET  /health                     → health check (startup probe)
  GET  /health/liveness            → liveness probe
  GET  /health/readiness           → readiness probe
  GET  /                           → server info
  GET  /mcp/tools                  → list all tools
  GET  /mcp/resources              → list all resources
  GET  /mcp/resources/{uri:path}   → read resource content
  GET  /mcp/prompts                → list all prompts

Run:
    .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8015 --workers 2
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import unquote

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_settings
from src.server import mcp
from src.utils.logging import get_logger, setup_logging

_cfg = get_settings()
setup_logging(_cfg.log_level)
logger = get_logger(__name__)

_VERSION = "1.0.0"

# ── Startup cache — populated once per worker via lifespan ────────────────────
_cache: dict[str, list[Any]] = {"tools": [], "resources": [], "prompts": []}
_resource_content: dict[str, str] = {}


async def _build_cache() -> None:
    tools, resources, prompts = await asyncio.gather(
        mcp.list_tools(),
        mcp.list_resources(),
        mcp.list_prompts(),
    )
    _cache["tools"] = tools
    _cache["resources"] = resources
    _cache["prompts"] = prompts

    async def _load(r: Any) -> tuple[str, str]:
        result = await mcp.read_resource(r.uri)
        return str(r.uri), str(result.contents[0].content) if result.contents else ""

    pairs = await asyncio.gather(
        *(_load(r) for r in resources), return_exceptions=True,
    )
    for item in pairs:
        if isinstance(item, Exception):
            logger.warning("Could not preload resource: %s", item)
        else:
            uri, content = item
            _resource_content[uri] = content

    logger.info(
        "Valid8 MCP ready — tools=%d resources=%d prompts=%d",
        len(tools), len(resources), len(prompts),
    )


# ── Custom REST routes on the MCP server ──────────────────────────────────────

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> Response:
    return JSONResponse({
        "name": "Valid8 MCP Server",
        "version": _VERSION,
        "description": (
            "MCP server for Walmart International Valid8 validation and "
            "data retrieval — Canada (CA) and Mexico (MX) markets"
        ),
        "mcp_endpoint": "/mcp",
        "tools": len(_cache["tools"]),
        "resources": len(_cache["resources"]),
        "prompts": len(_cache["prompts"]),
    })


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({
        "status": "healthy",
        "version": _VERSION,
        "tools": len(_cache["tools"]),
        "resources": len(_cache["resources"]),
        "prompts": len(_cache["prompts"]),
    })


@mcp.custom_route("/health/liveness", methods=["GET"])
async def liveness(request: Request) -> Response:
    return JSONResponse({
        "status": "alive",
        "version": _VERSION,
    })


@mcp.custom_route("/health/readiness", methods=["GET"])
async def readiness(request: Request) -> Response:
    if not _cache["tools"] and not _cache["resources"]:
        return JSONResponse(
            {"status": "not_ready", "message": "Cache not yet populated"},
            status_code=503,
        )
    return JSONResponse({
        "status": "ready",
        "version": _VERSION,
        "tools": len(_cache["tools"]),
        "resources": len(_cache["resources"]),
        "prompts": len(_cache["prompts"]),
    })


@mcp.custom_route("/mcp/tools", methods=["GET"])
async def list_tools(request: Request) -> Response:
    return JSONResponse({
        "tools": [
            {
                "name": t.name,
                "description": (t.description or "").split("\n")[0],
                "required_params": t.parameters.get("required", []),
            }
            for t in _cache["tools"]
        ]
    })


@mcp.custom_route("/mcp/resources", methods=["GET"])
async def list_resources(request: Request) -> Response:
    return JSONResponse({
        "resources": [
            {
                "uri": str(r.uri),
                "name": r.name,
                "description": r.description,
                "mimeType": r.mime_type,
            }
            for r in _cache["resources"]
        ]
    })


@mcp.custom_route("/mcp/resources/{uri:path}", methods=["GET"])
async def read_resource(request: Request) -> Response:
    decoded_uri = unquote(request.path_params["uri"])
    content = _resource_content.get(decoded_uri)
    if content is None:
        return JSONResponse(
            {"detail": f"Resource not found: {decoded_uri}"}, status_code=404,
        )

    resource = next(
        (r for r in _cache["resources"] if str(r.uri) == decoded_uri), None,
    )
    return JSONResponse({
        "uri": decoded_uri,
        "name": resource.name if resource else decoded_uri,
        "mimeType": resource.mime_type if resource else "text/plain",
        "content": content,
    })


@mcp.custom_route("/mcp/prompts", methods=["GET"])
async def list_prompts(request: Request) -> Response:
    return JSONResponse({
        "prompts": [
            {
                "name": p.name,
                "description": p.description,
                "arguments": [
                    {
                        "name": a.name,
                        "description": a.description,
                        "required": a.required,
                    }
                    for a in (p.arguments or [])
                ],
            }
            for p in _cache["prompts"]
        ]
    })


# ── ASGI app — used by uvicorn ─────────────────────────────────────────────────
app = mcp.http_app(stateless_http=True)


# ── Lifespan: build cache before serving first request ────────────────────────
_original_lifespan = app.lifespan


@asynccontextmanager
async def _lifespan(scope: Any) -> Any:
    await _build_cache()
    async with _original_lifespan(scope):
        yield


app.router.lifespan_context = _lifespan


def main() -> None:
    uvicorn.run(
        "app:app",
        host=os.environ.get("APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APP_PORT", "8015")),
        workers=int(os.environ.get("APP_WORKERS", "2")),
        log_level=_cfg.log_level.lower(),
    )


if __name__ == "__main__":
    main()
