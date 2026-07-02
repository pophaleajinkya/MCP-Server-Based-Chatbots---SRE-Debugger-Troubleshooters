"""Tests for the MCP server health endpoint."""

import pytest
from httpx import AsyncClient, ASGITransport
from src.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_returns_ok(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "tools" in body
    assert isinstance(body["tools"], list)
    assert len(body["tools"]) > 0, "Health endpoint must list at least one tool"


@pytest.mark.asyncio
async def test_mcp_endpoint_exists(app):
    """POST /mcp/ must be reachable (MCP Streamable HTTP)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.0.1"},
                },
            },
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    # 200 or 400 both confirm the endpoint exists
    assert resp.status_code in (200, 400, 422), (
        f"Expected /mcp/ to respond, got {resp.status_code}"
    )
