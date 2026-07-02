"""Unit tests for app.routers.health — /health and /ready endpoints."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestHealthEndpoint:
    """Tests for GET /health — liveness + capability summary."""

    def test_returns_200(self, client):
        """GET /health must return HTTP 200."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_response_status_is_ok(self, client):
        """The `status` field must be 'ok'."""
        resp = client.get("/health")
        assert resp.json()["status"] == "ok"

    def test_response_version_field(self, client):
        """The `version` field must be present and non-empty."""
        resp = client.get("/health")
        assert resp.json()["version"] == "2.0.0"

    def test_response_includes_active_llm(self, client):
        """The `active_llm` field must be present and a non-empty string."""
        resp = client.get("/health")
        data = resp.json()
        assert "active_llm" in data
        assert isinstance(data["active_llm"], str)
        assert data["active_llm"]  # non-empty

    def test_response_includes_llm_endpoint(self, client):
        """The `llm_endpoint` field must be present and a non-empty string."""
        resp = client.get("/health")
        data = resp.json()
        assert "llm_endpoint" in data
        assert isinstance(data["llm_endpoint"], str)

    def test_response_includes_mcp_servers_from_state(self, client):
        """mcp_servers must reflect the list injected into app.state at startup."""
        resp = client.get("/health")
        servers = resp.json()["mcp_servers"]
        assert isinstance(servers, list)
        assert len(servers) == 1
        assert servers[0]["name"] == "test-mcp"
        assert servers[0]["url"] == "http://localhost:8999/mcp"

    def test_response_includes_mcp_tools_from_state(self, client):
        """mcp_tools must reflect the list injected into app.state at startup."""
        resp = client.get("/health")
        tools = resp.json()["mcp_tools"]
        assert isinstance(tools, list)
        assert "check_health" in tools
        assert "get_metrics" in tools

    def test_response_has_all_expected_fields(self, client):
        """Response must contain all six required top-level fields."""
        resp = client.get("/health")
        data = resp.json()
        for field in ("status", "version", "active_llm", "llm_endpoint", "mcp_servers", "mcp_tools"):
            assert field in data, f"Missing field: {field}"

    def test_empty_mcp_servers_when_state_is_empty(self, app):
        """When app.state has no MCP servers, mcp_servers must be an empty list."""
        from fastapi.testclient import TestClient

        app.state.mcp_servers = []
        app.state.mcp_tools = []
        resp = TestClient(app).get("/health")
        assert resp.json()["mcp_servers"] == []
        assert resp.json()["mcp_tools"] == []

    def test_multiple_mcp_servers_appear_in_response(self, app):
        """All MCP servers in app.state must appear in the response."""
        from fastapi.testclient import TestClient

        app.state.mcp_servers = [
            {"name": "server-a", "url": "http://a.test/mcp"},
            {"name": "server-b", "url": "http://b.test/mcp"},
        ]
        resp = TestClient(app).get("/health")
        names = [s["name"] for s in resp.json()["mcp_servers"]]
        assert "server-a" in names
        assert "server-b" in names


class TestReadyEndpoint:
    """Tests for GET /ready — Kubernetes readiness probe."""

    def test_returns_200(self, client):
        """GET /ready must return HTTP 200."""
        resp = client.get("/ready")
        assert resp.status_code == 200

    def test_returns_ready_status(self, client):
        """Response body must contain `{"status": "ready"}`."""
        resp = client.get("/ready")
        assert resp.json() == {"status": "ready"}

    def test_status_field_value(self, client):
        """`status` field must be exactly the string 'ready'."""
        resp = client.get("/ready")
        assert resp.json()["status"] == "ready"
