"""
Integration tests for the /dependencies API endpoint.

All external calls are mocked.  The key strategy is to patch
`src.agent.agent.dependency_agent.process_query` (the singleton's public
method), which completely bypasses the LangGraph internals so tests are fast
and deterministic.
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
# Tests: GET /health  and  GET /
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    """Basic smoke tests for auxiliary endpoints."""

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_root_endpoint(self, client):
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["service"] == "Dependency Agent API"
        assert body["status"] == "running"


# ---------------------------------------------------------------------------
# Tests: POST /dependencies – namespace-only query (suggest apps)
# ---------------------------------------------------------------------------

class TestNamespaceOnlyQuery:
    """Integration tests for queries that supply only a namespace."""

    @pytest.mark.asyncio
    async def test_suggest_apps_returns_success(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """When only a namespace is given the endpoint should return success."""
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
        assert body.get("error") is None

    @pytest.mark.asyncio
    async def test_suggest_apps_returns_data_field_no_response_field(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """Response must have 'data' and must NOT have 'response' (summarization removed)."""
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

        body = response.json()
        assert "data" in body
        assert "response" not in body  # summarization removed


# ---------------------------------------------------------------------------
# Tests: POST /dependencies – fetch dependencies (app + namespace)
# ---------------------------------------------------------------------------

class TestFetchDependencies:
    """Integration tests for queries that supply both app name and namespace."""

    @pytest.mark.asyncio
    async def test_upstream_dependencies_found(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_upstream_deps,
        sample_source_breakdown,
    ):
        """Should return upstream dependencies when both app and namespace are given."""
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
                    "query": f"Get upstream dependencies for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["error"] is None
        assert "data" in body

    @pytest.mark.asyncio
    async def test_zero_upstream_dependencies(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
    ):
        """Should return success with empty dependencies list when none found."""
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
                    "query": f"Get upstream dependencies namespace {sample_namespace} and app name {sample_app_name}",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["error"] is None

    @pytest.mark.asyncio
    async def test_downstream_dependencies(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_downstream_deps,
    ):
        """Should return downstream dependencies."""
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
                    "query": f"Get downstream dependencies for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @pytest.mark.asyncio
    async def test_both_directions(
        self,
        async_client,
        sample_session_id,
        sample_app_name,
        sample_namespace,
        sample_upstream_deps,
        sample_downstream_deps,
        sample_source_breakdown,
    ):
        """Should return both upstream and downstream dependencies."""
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
                    "query": f"Get all dependencies for {sample_app_name} in {sample_namespace}",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Tests: POST /dependencies – error / edge cases
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Integration tests for error cases."""

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, async_client):
        """Request without sessionId or query should return 422."""
        response = await async_client.post("/dependencies", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_session_id(self, async_client, sample_namespace):
        """Request without sessionId should return 422."""
        response = await async_client.post(
            "/dependencies",
            json={"query": f"get apps for {sample_namespace}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_query(self, async_client, sample_session_id):
        """Request without query should return 422."""
        response = await async_client.post(
            "/dependencies",
            json={"session_id": sample_session_id},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_agent_exception_returns_error_status(
        self, async_client, sample_session_id
    ):
        """When the agent raises an unexpected error, response status should be error."""
        with (
            _patch_conv_history(),
            patch(
                "src.services.query_processor.QueryProcessor.process_query",
                new=AsyncMock(side_effect=RuntimeError("Unexpected failure")),
            ),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id, "query": "get apps for test-namespace"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert body["error"] is not None

    @pytest.mark.asyncio
    async def test_conversation_history_failure_still_processes(
        self,
        async_client,
        sample_session_id,
        sample_namespace,
        sample_available_apps,
    ):
        """Even if conversation history returns empty, query should still be processed."""
        agent_result = make_agent_result(
            namespace=sample_namespace,
            available_apps=sample_available_apps,
        )
        with (
            _patch_conv_history([]),
            _patch_agent(agent_result),
        ):
            response = await async_client.post(
                "/dependencies",
                json={"session_id": sample_session_id, "query": f"get apps for {sample_namespace}"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Tests: merge_service integration
# ---------------------------------------------------------------------------

class TestMergeService:
    """Integration tests for the dependency merge logic (no HTTP)."""

    @pytest.mark.asyncio
    async def test_get_upstream_and_downstream_returns_sre_ops_results(self, sample_app_name, sample_namespace):
        """get_upstream_and_downstream_dependencies returns upstream results from SRE-OPS."""
        from src.services.merge_service import get_upstream_and_downstream_dependencies

        sre_data = [
            {"name": "svc-a", "namespace": "ns-1", "app": "svc-a", "source": "db"},
            {"name": "svc-b", "namespace": "ns-2", "app": "svc-b", "source": "db"},
        ]

        with (
            patch("src.services.merge_service.fetch_upstream_dependencies", new=AsyncMock(return_value=sre_data)),
            patch("src.services.merge_service.fetch_downstream_dependencies", new=AsyncMock(return_value=[])),
        ):
            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                sample_app_name, sample_namespace
            )

        assert len(upstream) == 2
        assert len(downstream) == 0
        assert breakdown["total"] == 2
        assert breakdown["upstream_count"] == 2
        assert breakdown["downstream_count"] == 0

    @pytest.mark.asyncio
    async def test_get_upstream_and_downstream_empty(self, sample_app_name, sample_namespace):
        """get_upstream_and_downstream_dependencies returns empty lists when SRE-OPS returns nothing."""
        from src.services.merge_service import get_upstream_and_downstream_dependencies

        with (
            patch("src.services.merge_service.fetch_upstream_dependencies", new=AsyncMock(return_value=[])),
            patch("src.services.merge_service.fetch_downstream_dependencies", new=AsyncMock(return_value=[])),
        ):
            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                sample_app_name, sample_namespace
            )

        assert upstream == []
        assert downstream == []
        assert breakdown["total"] == 0

    @pytest.mark.asyncio
    async def test_get_upstream_and_downstream_upstream_only(
        self, sample_app_name, sample_namespace, sample_upstream_deps
    ):
        """get_upstream_and_downstream_dependencies with direction=upstream."""
        from src.services.merge_service import get_upstream_and_downstream_dependencies

        with (
            patch("src.services.merge_service.fetch_upstream_dependencies", new=AsyncMock(return_value=sample_upstream_deps)),
            patch("src.services.merge_service.fetch_downstream_dependencies", new=AsyncMock(return_value=[])),
        ):
            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                sample_app_name, sample_namespace, direction="upstream"
            )

        assert isinstance(upstream, list)
        assert isinstance(downstream, list)
        assert len(downstream) == 0

    @pytest.mark.asyncio
    async def test_sre_ops_results_returned_as_is(self, sample_app_name, sample_namespace):
        """SRE-OPS results are returned as-is (no dedup needed, server handles it)."""
        from src.services.merge_service import get_upstream_and_downstream_dependencies

        sre_dep = {"name": "shared-svc", "namespace": "shared-ns", "app": "shared-svc", "source": "db"}

        with (
            patch("src.services.merge_service.fetch_upstream_dependencies", new=AsyncMock(return_value=[sre_dep])),
            patch("src.services.merge_service.fetch_downstream_dependencies", new=AsyncMock(return_value=[])),
        ):
            upstream, downstream, breakdown = await get_upstream_and_downstream_dependencies(
                sample_app_name, sample_namespace
            )

        names = [d["name"] for d in upstream]
        assert names.count("shared-svc") == 1


# ---------------------------------------------------------------------------
# Tests: response_builder
# ---------------------------------------------------------------------------

class TestResponseBuilder:
    """Unit-level tests for response builder helpers."""

    def test_build_data_payload_with_dependencies(self, sample_upstream_deps):
        from src.services.response_builder import build_data_payload
        from src.models.query import ToolResult

        tool_result = ToolResult(
            toolName="get_app_dependencies",
            success=True,
            data={
                "appName": "my-app",
                "namespace": "my-ns",
                "dependencies": sample_upstream_deps,
                "totalCount": len(sample_upstream_deps),
                "sourceBreakdown": {"total": len(sample_upstream_deps)},
            },
        )
        payload = build_data_payload(True, [tool_result])
        assert payload is not None
        assert "dependencies" in payload
        assert payload["totalCount"] == len(sample_upstream_deps)

    def test_build_data_payload_with_available_apps(self, sample_available_apps, sample_namespace):
        from src.services.response_builder import build_data_payload
        from src.models.query import ToolResult

        tool_result = ToolResult(
            toolName="get_app_dependencies",
            success=True,
            data={
                "namespace": sample_namespace,
                "available_apps": sample_available_apps,
            },
        )
        payload = build_data_payload(True, [tool_result])
        assert payload is not None
        assert "availableApps" in payload
        assert payload["totalApps"] == len(sample_available_apps)

    def test_build_data_payload_failure_returns_none(self):
        from src.services.response_builder import build_data_payload
        from src.models.query import ToolResult

        tool_result = ToolResult(
            toolName="get_app_dependencies",
            success=False,
            data=None,
            error="Something went wrong",
        )
        payload = build_data_payload(False, [tool_result])
        assert payload is None

    def test_create_error_response(self, sample_session_id):
        from src.services.response_builder import create_error_response
        from src.models.query import QueryRequest

        request = QueryRequest(session_id=sample_session_id, query="test query")
        resp = create_error_response(request, "boom")
        assert resp.status == "error"
        assert resp.error == "boom"
        assert resp.query == "test query"

