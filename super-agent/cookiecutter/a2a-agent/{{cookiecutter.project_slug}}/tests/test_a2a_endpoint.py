"""Tests for the A2A message/send endpoint.

Verifies A2A 0.3 JSON-RPC protocol compliance so super-agent can
call this agent correctly.
"""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from src.app.factory import create_app


@pytest.fixture
def app():
    return create_app()


def _a2a_payload(text: str, session_id: str | None = None) -> dict:
    """Build a valid A2A 0.3 message/send JSON-RPC payload."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": text}],
                "messageId": str(uuid.uuid4()),
            },
            "configuration": {
                **({"sessionId": session_id} if session_id else {}),
            },
        },
    }


@pytest.mark.asyncio
async def test_a2a_returns_jsonrpc_response(app):
    """POST /a2a returns a valid JSON-RPC 2.0 response envelope."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/a2a", json=_a2a_payload("Hello"))
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("jsonrpc") == "2.0"
    assert "result" in body or "error" in body


@pytest.mark.asyncio
async def test_a2a_completed_task_has_artifacts(app):
    """A completed A2A task must have non-empty artifacts with text parts."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/a2a", json=_a2a_payload("What can you do?"))
    assert resp.status_code == 200
    body  = resp.json()
    task  = body.get("result", {})
    state = task.get("status", {}).get("state", "")
    assert state in ("completed", "working", "submitted"), f"Unexpected task state: {state}"
    if state == "completed":
        artifacts = task.get("artifacts", [])
        assert artifacts, "Completed task must have at least one artifact"
        parts = artifacts[0].get("parts", [])
        texts = [p["text"] for p in parts if p.get("type") == "text" and p.get("text")]
        assert texts, "Artifact must contain non-empty text parts"
