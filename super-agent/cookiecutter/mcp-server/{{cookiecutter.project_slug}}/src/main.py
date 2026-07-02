"""Entry point for {{cookiecutter.project_name}}.

Mounts the MCP server at /mcp/ using Streamable HTTP transport (default).
Also exposes GET /health for monitoring.

super-agent connects to this server at:
  POST http://<host>:{{cookiecutter.server_port}}/mcp/
"""

import logging
import uvicorn
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.server import mcp
from src.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    s = get_settings()
    log.info("{{cookiecutter.project_name}} starting — port=%s", s.server_port)
    # TODO: Initialize any long-lived resources here (DB connections, HTTP clients, etc.)
    yield
    # TODO: Clean up resources here
    log.info("{{cookiecutter.project_name}} shut down cleanly")


def create_app() -> FastAPI:
    app = FastAPI(
        title="{{cookiecutter.project_name}}",
        version="{{cookiecutter.server_version}}",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Mount MCP at /mcp/ (Streamable HTTP — default super-agent transport) ──
    # super-agent connects to: POST http://<host>:{{cookiecutter.server_port}}/mcp/
    mcp_app = mcp.streamable_http_app()
    app.mount("/mcp", mcp_app)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        return {
            "status": "ok",
            "server": "{{cookiecutter.server_name}}",
            "version": "{{cookiecutter.server_version}}",
            "tools": tool_names,
        }

    return app


app = create_app()

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run(
        "src.main:app",
        host=s.server_host,
        port=s.server_port,
        reload=True,
    )
