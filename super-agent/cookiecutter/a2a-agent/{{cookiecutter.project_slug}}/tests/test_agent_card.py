"""Tests for the A2A Agent Card endpoint.

Verifies that /.well-known/agent.json returns a valid A2A 0.3 Agent Card
so super-agent can discover this agent at startup.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from src.app.factory import create_app, AGENT_CARD


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_agent_card_endpoint(app):
    """GET /.well-known/agent.json returns a valid Agent Card."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == AGENT_CARD.name
    assert "description" in card
    assert "skills" in card
    assert len(card["skills"]) > 0, "Agent Card must have at least one skill"


@pytest.mark.asyncio
async def test_health_endpoint(app):
    """GET /health returns ok."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_agent_card_has_valid_skills():
    """Agent Card skills have required fields."""
    for skill in AGENT_CARD.skills:
        assert skill.id, "skill.id must not be empty"
        assert skill.name, "skill.name must not be empty"
        assert skill.description, "skill.description must not be empty — LLM uses this for routing"
        assert len(skill.description) > 20, (
            f"skill '{skill.id}' description is too short — be specific about input/output"
        )
