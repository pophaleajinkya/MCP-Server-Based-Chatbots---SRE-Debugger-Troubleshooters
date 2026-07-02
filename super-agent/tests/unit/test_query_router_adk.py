"""
Unit tests for the ADK-native POST /query and POST /query_api endpoints
(app/routers/query.py).

Uses the conftest `client` fixture which includes the ADK query router wired
to a mock ADK runner.  The fixture pre-sets a ``loginId`` header so that
existing tests satisfy the user-identity requirement without adding ``user_id``
to every payload.  A separate ``client_no_auth`` fixture is used for tests
that verify the 422 enforcement when no identity is supplied.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


@pytest.fixture
def client_no_auth(app):
    """TestClient with NO loginId header — used to verify 422 enforcement."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: POST /query
# ---------------------------------------------------------------------------


class TestQueryEndpoint:
    """Behaviour of POST /query — ADK-native query route."""

    def test_returns_200_with_answer(self, client):
        """A valid query must return HTTP 200 with the agent's answer."""
        resp = client.post(
            "/query",
            json={"query": "Check namespace health", "session_id": "sess-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["response"] == "Test response from agent"

    def test_response_echoes_session_id(self, client):
        """The session_id from the request must appear in the response."""
        resp = client.post(
            "/query",
            json={"query": "Check health", "session_id": "my-session-xyz"},
        )
        assert resp.json()["session_id"] == "my-session-xyz"

    def test_missing_query_returns_422(self, client):
        """Requests missing the `query` field must be rejected with HTTP 422."""
        resp = client.post("/query", json={"session_id": "sess-1"})
        assert resp.status_code == 422

    def test_missing_session_id_auto_generates_uuid(self, client):
        """Requests without session_id succeed — a UUID is auto-generated."""
        import uuid
        resp = client.post("/query", json={"query": "Check health"})
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        assert len(sid) == 36  # UUID4 format: 8-4-4-4-12
        uuid.UUID(sid)  # raises ValueError if not a valid UUID

    def test_empty_query_returns_422(self, client):
        """Empty string query must be rejected (min_length=1)."""
        resp = client.post("/query", json={"query": "", "session_id": "s"})
        assert resp.status_code == 422

    def test_response_has_both_fields(self, client):
        """Response must contain response and session_id keys."""
        resp = client.post(
            "/query",
            json={"query": "ping", "session_id": "sess-2"},
        )
        data = resp.json()
        assert "response" in data
        assert "session_id" in data

    def test_response_field_is_string(self, client):
        """The `response` value must be a string."""
        resp = client.post(
            "/query",
            json={"query": "test query", "session_id": "s"},
        )
        assert isinstance(resp.json()["response"], str)


# ---------------------------------------------------------------------------
# Tests: POST /query_api (MAOF alias)
# ---------------------------------------------------------------------------


class TestQueryApiEndpoint:
    """Behaviour of POST /query_api — MAOF-registered alias for /query."""

    def test_returns_200_with_answer(self, client):
        """query_api must return HTTP 200 with the agent's answer."""
        resp = client.post(
            "/query_api",
            json={"query": "Check namespace health", "session_id": "sess-api-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["response"] == "Test response from agent"

    def test_session_id_echoed_in_response(self, client):
        """query_api must echo the supplied session_id back in the response."""
        resp = client.post(
            "/query_api",
            json={"query": "Health check", "session_id": "api-session-42"},
        )
        assert resp.json()["session_id"] == "api-session-42"

    def test_response_contains_both_fields(self, client):
        """query_api response must have response and session_id keys."""
        resp = client.post(
            "/query_api",
            json={"query": "test", "session_id": "s"},
        )
        data = resp.json()
        assert "response" in data
        assert "session_id" in data

    def test_missing_session_id_auto_generates_uuid(self, client):
        """Requests to query_api without session_id succeed — a UUID is auto-generated."""
        import uuid
        resp = client.post("/query_api", json={"query": "check"})
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        assert len(sid) == 36  # UUID4 format: 8-4-4-4-12
        uuid.UUID(sid)  # raises ValueError if not a valid UUID

    def test_missing_query_returns_422(self, client):
        """Requests to query_api without query must be rejected (HTTP 422)."""
        resp = client.post("/query_api", json={"session_id": "sess-1"})
        assert resp.status_code == 422

    def test_produces_same_answer_as_query_endpoint(self, client):
        """/query and /query_api use the same agent; answers should match."""
        payload = {"query": "ping", "session_id": "same-session"}

        resp_query = client.post("/query", json=payload)
        resp_api = client.post("/query_api", json=payload)

        assert resp_query.json()["response"] == resp_api.json()["response"]


# ---------------------------------------------------------------------------
# Tests: user_id enforcement (no fallback to "admin")
# ---------------------------------------------------------------------------


class TestUserIdEnforcement:
    """Verify that /query and /query_api reject requests with no user identity."""

    def test_no_user_id_anywhere_returns_422_on_query(self, client_no_auth):
        """No body user_id, no loginId header → 422 (not silently stored as admin)."""
        resp = client_no_auth.post("/query", json={"query": "Check health"})
        assert resp.status_code == 422
        assert "user_id" in resp.json()["detail"].lower()

    def test_no_user_id_anywhere_returns_422_on_query_api(self, client_no_auth):
        """No body user_id, no loginId header → 422 on query_api as well."""
        resp = client_no_auth.post("/query_api", json={"query": "Check health"})
        assert resp.status_code == 422

    def test_user_id_in_body_is_accepted(self, client_no_auth):
        """Explicit user_id in JSON body satisfies the requirement."""
        resp = client_no_auth.post(
            "/query",
            json={"query": "Check health", "user_id": "alice@walmart.com"},
        )
        assert resp.status_code == 200

    def test_login_id_header_is_accepted(self, client_no_auth):
        """loginId request header satisfies the requirement (no body user_id needed)."""
        resp = client_no_auth.post(
            "/query",
            json={"query": "Check health"},
            headers={"loginId": "bob@walmart.com"},
        )
        assert resp.status_code == 200

    def test_wm_llm_gw_header_is_accepted(self, client_no_auth):
        """wm_llm_gw.user_name header is accepted as the third fallback."""
        resp = client_no_auth.post(
            "/query",
            json={"query": "Check health"},
            headers={"wm_llm_gw.user_name": "carol@walmart.com"},
        )
        assert resp.status_code == 200
