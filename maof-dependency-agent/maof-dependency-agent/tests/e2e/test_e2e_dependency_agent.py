"""
End-to-end tests for the Dependency Agent.

These tests exercise the complete request→response pipeline via the FastAPI
AsyncClient (ASGI transport).  All external HTTP calls (SRE-OPS, Topology,
DX Console, Conversation API, OpenAI/LLM) are mocked so the suite can run
in CI without real infrastructure.

Strategy: patch `src.agent.agent.dependency_agent.process_query` (the
module-level singleton's public method) to bypass LangGraph entirely, then
assert on the HTTP response structure.

Scenarios covered:
  1. Namespace-only query  → list of available apps returned
  2. App + namespace query → upstream / downstream / both deps returned
  3. Zero-dependency case  → success with empty deps
  4. Context inference     → namespace present in returned data
  5. Error cases           → invalid input, agent failure, external API failure
  6. Response shape        → contract assertions on the JSON structure
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.helpers import make_agent_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_agent(result: dict):
    """Patch the global dependency_agent singleton's process_query."""
    return patch(
        "src.agent.agent.dependency_agent.process_query",
        new=AsyncMock(return_value=result),
    )


def _patch_conv_history(history=None):
    return patch(
        "src.services.conversation_history.get_conversation_history",
        new=AsyncMock(return_value=history or []),
    )


# ---------------------------------------------------------------------------
# E2E: Namespace-only flow
# ---------------------------------------------------------------------------

class TestE2ENamespaceOnlyFlow:
    """Full pipeline for 'get apps in namespace' queries."""

    @pytest.mark.asyncio
    async def test_get_apps_for_namespace_returns_app_list(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """
        Full pipeline:
          user query → agent.process_query → structured response.
        No summarization step; 'response' field must be absent.
        """
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": f"get applications for {sample_namespace}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["query"] == f"get applications for {sample_namespace}"
        assert body["error"] is None
        assert "response" not in body   # summarization removed
        assert "data" in body

    @pytest.mark.asyncio
    async def test_get_apps_data_contains_available_apps(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """data.availableApps should contain the apps returned by the agent."""
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": f"list apps in {sample_namespace}"},
            )

        body = response.json()
        data = body.get("data", {})
        assert "availableApps" in data
        assert set(data["availableApps"]) == set(sample_available_apps)
        assert data["totalApps"] == len(sample_available_apps)
        assert data.get("namespace") == sample_namespace

    @pytest.mark.asyncio
    async def test_namespace_not_found_returns_success(
        self,
        async_client,
        sample_session_id,
    ):
        """When the agent finds no apps for a namespace, response is still 200."""
        unknown_ns = "non-existent-namespace"
        agent_result = make_agent_result(namespace=unknown_ns, available_apps=[])
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": f"get apps for {unknown_ns}"},
            )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# E2E: Dependency fetch flow
# ---------------------------------------------------------------------------

class TestE2EDependencyFetchFlow:
    """Full pipeline for dependency-fetch queries (app + namespace supplied)."""

    @pytest.mark.asyncio
    async def test_upstream_deps_zero_returns_success(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
    ):
        """
        Zero upstream deps → success response with appName and namespace in data.
        """
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,
            direction="upstream",
            dependencies=[],
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": (
                        f"Get dependencies upstream namespace {sample_namespace} "
                        f"and app name {sample_app_name}"
                    ),
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["error"] is None
        assert body["data"]["appName"] == sample_app_name
        assert body["data"]["namespace"] == sample_namespace

    @pytest.mark.asyncio
    async def test_upstream_deps_with_results(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_upstream_deps,
        sample_source_breakdown,
    ):
        """Upstream dependencies are surfaced in data.dependencies."""
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,
            direction="upstream",
            dependencies=sample_upstream_deps,
            source_breakdown=sample_source_breakdown,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": f"upstream deps for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        data = body["data"]
        assert "dependencies" in data
        assert len(data["dependencies"]) == len(sample_upstream_deps)
        assert data["totalCount"] == len(sample_upstream_deps)

    @pytest.mark.asyncio
    async def test_downstream_deps_with_results(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_downstream_deps,
    ):
        """Downstream dependencies are surfaced in data.dependencies."""
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,
            direction="downstream",
            dependencies=sample_downstream_deps,
            source_breakdown={"total": len(sample_downstream_deps)},
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": f"downstream deps for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert len(body["data"]["dependencies"]) == len(sample_downstream_deps)

    @pytest.mark.asyncio
    async def test_both_directions_combined(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_upstream_deps,
        sample_downstream_deps,
        sample_source_breakdown,
    ):
        """Both upstream + downstream deps appear combined in data.dependencies."""
        all_deps = sample_upstream_deps + sample_downstream_deps
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,
            direction="both",
            dependencies=all_deps,
            upstream_dependencies=sample_upstream_deps,
            downstream_dependencies=sample_downstream_deps,
            source_breakdown=sample_source_breakdown,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": f"all dependencies for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        expected_total = len(sample_upstream_deps) + len(sample_downstream_deps)
        assert len(body["data"]["dependencies"]) == expected_total


# ---------------------------------------------------------------------------
# E2E: Conversation-history context inference
# ---------------------------------------------------------------------------

class TestE2EConversationContextInference:
    """Verify namespace/app are correctly surfaced when inferred from history."""

    @pytest.mark.asyncio
    async def test_namespace_inferred_from_conversation_history(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        mock_conversation_history,
        sample_upstream_deps,
        sample_source_breakdown,
    ):
        """
        Scenario:
          - Previous conversation mentioned namespace 'atlas-inventory-crons'
          - User now asks about a specific app without naming the namespace
          - The namespace in the response data should match what the agent extracted
        """
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,   # inferred from history inside real agent
            direction="upstream",
            dependencies=sample_upstream_deps,
            source_breakdown=sample_source_breakdown,
        )
        with (
            _patch_conv_history(mock_conversation_history),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    # No namespace in query – would be inferred from history
                    "query": f"upstream dependencies for {sample_app_name}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["namespace"] == sample_namespace

    @pytest.mark.asyncio
    async def test_empty_conversation_history_falls_back_gracefully(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
    ):
        """Empty conversation history should not crash the pipeline."""
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,
            direction="upstream",
            dependencies=[],
        )
        with (
            _patch_conv_history([]),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": f"upstream deps for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ---------------------------------------------------------------------------
# E2E: Error / edge-case scenarios
# ---------------------------------------------------------------------------

class TestE2EErrorScenarios:
    """End-to-end error and edge-case coverage."""

    @pytest.mark.asyncio
    async def test_invalid_json_body(self, async_client):
        """Sending non-JSON body must return 422."""
        response = await async_client.post(
            "/dependencies",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_body(self, async_client):
        """Empty JSON object must return 422 (missing required fields)."""
        response = await async_client.post("/dependencies", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_agent_process_query_failure_returns_error_response(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
    ):
        """If dependency_agent.process_query raises, the endpoint returns error status."""
        with (
            _patch_conv_history(),
            patch(
                "src.agent.agent.dependency_agent.process_query",
                new=AsyncMock(side_effect=RuntimeError("Agent internal failure")),
            ),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": f"upstream deps for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert body["error"] is not None

    @pytest.mark.asyncio
    async def test_query_processor_exception_returns_error_response(
        self,
        async_client,
        sample_session_id,
    ):
        """If QueryProcessor itself throws, endpoint returns error (not 500)."""
        with (
            _patch_conv_history(),
            patch(
                "src.services.query_processor.QueryProcessor.process_query",
                new=AsyncMock(side_effect=RuntimeError("Unexpected failure")),
            ),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": "get apps for test-namespace"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert body["error"] is not None

    @pytest.mark.asyncio
    async def test_success_error_field_is_null_not_string(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """On success the 'error' field must be null (not the string 'None')."""
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": f"apps in {sample_namespace}"},
            )

        body = response.json()
        assert body.get("error") is None   # null in JSON, not "None"


# ---------------------------------------------------------------------------
# E2E: Response shape / contract tests
# ---------------------------------------------------------------------------

class TestE2EResponseShape:
    """Validate the exact JSON shape / contract of API responses."""

    @pytest.mark.asyncio
    async def test_namespace_query_required_top_level_keys(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """
        For namespace-only query, response must have status, query, data, error.
        Must NOT have a 'response' key (summarization moved to Redis).
        """
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": f"get apps for {sample_namespace}"},
            )

        body = response.json()
        for key in ("status", "query", "data", "error"):
            assert key in body, f"Missing required key: '{key}'"
        assert "response" not in body, "'response' field must not be present"
        assert isinstance(body["status"], str)
        assert isinstance(body["query"], str)

    @pytest.mark.asyncio
    async def test_dependency_query_data_shape(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_upstream_deps,
        sample_source_breakdown,
    ):
        """
        For a dependency query, data should contain:
          dependencies (list), totalCount (int), sourceBreakdown (dict).
        """
        agent_result = make_agent_result(
            app_name=sample_app_name,
            namespace=sample_namespace,
            direction="upstream",
            dependencies=sample_upstream_deps,
            source_breakdown=sample_source_breakdown,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": sample_session_id,
                    "query": f"upstream deps for {sample_app_name} in {sample_namespace}",
                },
            )

        body = response.json()
        assert body["status"] == "success"
        data = body["data"]
        assert isinstance(data["dependencies"], list)
        assert isinstance(data["totalCount"], int)
        assert isinstance(data["sourceBreakdown"], dict)

    @pytest.mark.asyncio
    async def test_query_field_mirrors_input_exactly(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """The 'query' field in the response must exactly mirror the input query."""
        query_text = f"get applications for {sample_namespace}"
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id, "query": query_text},
            )

        assert response.json()["query"] == query_text

    @pytest.mark.asyncio
    async def test_available_apps_data_shape(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """data.availableApps must be a list and data.totalApps must equal its length."""
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history(),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id,
                      "query": f"apps in {sample_namespace}"},
            )

        data = response.json()["data"]
        assert isinstance(data["availableApps"], list)
        assert data["totalApps"] == len(data["availableApps"])

