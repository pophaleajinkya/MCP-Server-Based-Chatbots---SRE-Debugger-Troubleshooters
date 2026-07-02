"""Unit tests for app.routers.faqs — GET /group/faqs endpoint."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.routers.faqs import router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def faqs_app():
    """Return a minimal FastAPI app with the faqs router mounted."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def faqs_client(faqs_app):
    """Return a TestClient for the faqs app."""
    return TestClient(faqs_app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATIC_FAQS = [
    {
        "title": "Getting Started",
        "description": "Basic questions",
        "faqs": ["How do I log in?", "How do I reset my password?"],
    },
    {
        "title": "Monitoring",
        "description": "Monitoring questions",
        "faqs": ["How do I check health?"],
    },
]

_DYNAMIC_FAQS = [
    {
        "title": "MCP Tools",
        "description": "Questions from MCP servers",
        "faqs": ["How do I run a scan?", "How do I deploy?"],
    },
]

_AGENT_JSON = {
    "skills": [
        {
            "name": "Health Check",
            "description": "Check system health",
            "examples": ["Is the system healthy?", "Show me health status"],
        },
        {
            "name": "Metrics",
            "description": "View metrics",
            "examples": ["Show me CPU usage"],
        },
        {
            "name": "Empty Skill",
            "description": "No examples",
        },
    ]
}


# ---------------------------------------------------------------------------
# TestGetFaqs
# ---------------------------------------------------------------------------

class TestGetFaqs:
    """Tests for GET /group/faqs endpoint."""

    def test_returns_static_faqs_when_file_exists(self, faqs_client):
        """When faqs.json exists, its content is returned."""
        with patch("app.routers.faqs.Path.exists", return_value=True), \
             patch("app.routers.faqs.Path.open", mock_open(read_data=json.dumps(_STATIC_FAQS))):
            resp = faqs_client.get("/group/faqs")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["title"] == "Getting Started"
        assert data[1]["title"] == "Monitoring"

    def test_returns_dynamic_faqs_from_app_state(self, faqs_app):
        """When app.state.dynamic_faqs is set and no static file, returns dynamic FAQs."""
        faqs_app.state.dynamic_faqs = _DYNAMIC_FAQS

        with patch("app.routers.faqs.Path.exists", return_value=False):
            client = TestClient(faqs_app)
            resp = client.get("/group/faqs")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "MCP Tools"

    def test_merges_static_and_dynamic_no_duplicate_titles(self, faqs_app):
        """Static + dynamic FAQs are merged; different titles produce separate groups."""
        faqs_app.state.dynamic_faqs = _DYNAMIC_FAQS

        with patch("app.routers.faqs.Path.exists", return_value=True), \
             patch("app.routers.faqs.Path.open", mock_open(read_data=json.dumps(_STATIC_FAQS))):
            client = TestClient(faqs_app)
            resp = client.get("/group/faqs")

        data = resp.json()
        titles = [g["title"] for g in data]
        assert "Getting Started" in titles
        assert "Monitoring" in titles
        assert "MCP Tools" in titles
        assert len(data) == 3  # no duplicates

    def test_merges_faqs_into_existing_group_when_titles_overlap(self, faqs_app):
        """When a dynamic FAQ has the same title as a static one, its faqs are merged."""
        overlapping_dynamic = [
            {
                "title": "Getting Started",
                "faqs": ["New dynamic FAQ item"],
            }
        ]
        faqs_app.state.dynamic_faqs = overlapping_dynamic

        with patch("app.routers.faqs.Path.exists", return_value=True), \
             patch("app.routers.faqs.Path.open", mock_open(read_data=json.dumps(_STATIC_FAQS))):
            client = TestClient(faqs_app)
            resp = client.get("/group/faqs")

        data = resp.json()
        # Should still be 2 groups (no new group added)
        assert len(data) == 2
        # The "Getting Started" group should have merged faqs
        gs_group = next(g for g in data if g["title"] == "Getting Started")
        assert "New dynamic FAQ item" in gs_group["faqs"]
        # Original faqs still present
        assert "How do I log in?" in gs_group["faqs"]

    def test_falls_back_to_agent_json_skills(self, faqs_client):
        """When no static or dynamic FAQs, falls back to agent.json skills."""
        with patch("app.routers.faqs.Path.exists", return_value=False), \
             patch("app.routers.faqs.Path.open", mock_open(read_data=json.dumps(_AGENT_JSON))):
            resp = faqs_client.get("/group/faqs")

        assert resp.status_code == 200
        data = resp.json()
        # Only skills with examples should appear
        assert len(data) == 2
        titles = [g["title"] for g in data]
        assert "Health Check" in titles
        assert "Metrics" in titles
        assert "Empty Skill" not in titles

    def test_returns_empty_list_when_nothing_available(self, faqs_client):
        """When no faqs.json, no dynamic FAQs, and no agent.json, returns []."""
        with patch("app.routers.faqs.Path.exists", return_value=False), \
             patch("app.routers.faqs.Path.open", side_effect=FileNotFoundError):
            resp = faqs_client.get("/group/faqs")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_handles_file_read_error_gracefully(self, faqs_client):
        """When faqs.json exists but read fails, endpoint doesn't crash."""
        with patch("app.routers.faqs.Path.exists", return_value=True), \
             patch("app.routers.faqs.Path.open", side_effect=PermissionError("denied")), \
             patch.object(Path, "open", side_effect=PermissionError("denied")):
            resp = faqs_client.get("/group/faqs")

        # Should still return 200 with either empty list or fallback data
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
