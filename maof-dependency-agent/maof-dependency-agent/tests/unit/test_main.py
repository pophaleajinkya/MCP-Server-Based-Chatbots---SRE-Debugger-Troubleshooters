"""Unit tests for main.py FastAPI application."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_endpoint(self, client):
        """Test root endpoint returns service info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Dependency Agent API"
        assert data["version"] == "0.1.0"
        assert data["status"] == "running"


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_endpoint(self, client):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestDependenciesEndpoint:
    """Tests for /dependencies endpoint (WCNP)."""

    @pytest.mark.asyncio
    async def test_dependencies_success(self, async_client):
        """Test successful dependency query."""
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.data = {
            "dependencies": [{"name": "dep1"}],
            "appName": "my-app",
            "namespace": "prod"
        }
        mock_tool_result.error = None

        with patch("main.QueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.return_value = (MagicMock(), [mock_tool_result])
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": "test-session-123",
                    "query": "get deps for my-app in prod"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["query"] == "get deps for my-app in prod"

    @pytest.mark.asyncio
    async def test_dependencies_error(self, async_client):
        """Test dependency query error."""
        mock_tool_result = MagicMock()
        mock_tool_result.success = False
        mock_tool_result.data = None
        mock_tool_result.error = "Failed to parse parameters"

        with patch("main.QueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.return_value = (MagicMock(), [mock_tool_result])
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": "test-session-456",
                    "query": "invalid query"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"
            assert data["error"] == "Failed to parse parameters"

    @pytest.mark.asyncio
    async def test_dependencies_exception(self, async_client):
        """Test dependency query with exception."""
        with patch("main.QueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.side_effect = Exception("Unexpected error")
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies",
                json={
                    "session_id": "test-session-error",
                    "query": "test"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"
            assert "Unexpected error" in data["error"]


class TestOneOpsDependenciesEndpoint:
    """Tests for /dependencies/oneops endpoint."""

    @pytest.mark.asyncio
    async def test_oneops_success(self, async_client):
        """Test successful OneOps query."""
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.data = {
            "org": "mexicoecomm",
            "platform": "rmsag2",
            "assembly": "mx-rms",
            "dependencies": [{"name": "oneops-dep"}]
        }
        mock_tool_result.error = None

        with patch("main.OneOpsQueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.return_value = (MagicMock(), [mock_tool_result])
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies/oneops",
                json={
                    "session_id": "test-oneops-123",
                    "query": "get deps org=mexicoecomm platform=rmsag2 assembly=mx-rms"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_oneops_error(self, async_client):
        """Test OneOps query error."""
        mock_tool_result = MagicMock()
        mock_tool_result.success = False
        mock_tool_result.data = None
        mock_tool_result.error = "Missing OneOps parameters"

        with patch("main.OneOpsQueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.return_value = (MagicMock(), [mock_tool_result])
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies/oneops",
                json={
                    "session_id": "test-oneops-error",
                    "query": "invalid oneops query"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_oneops_exception(self, async_client):
        """Test OneOps query with exception."""
        with patch("main.OneOpsQueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.side_effect = Exception("OneOps service error")
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies/oneops",
                json={
                    "session_id": "test-oneops-exc",
                    "query": "test"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"
            assert "OneOps service error" in data["error"]


class TestManagedServiceEndpoint:
    """Tests for /dependencies/managed-service endpoint."""

    @pytest.mark.asyncio
    async def test_managed_service_success(self, async_client):
        """Test successful managed service query."""
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.data = {
            "serviceType": "cassandra",
            "assembly": "mx-rms",
            "platform": "rmsag2",
            "dependencies": [{"name": "cassandra-dep"}]
        }
        mock_tool_result.error = None

        with patch("main.ManagedServiceQueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.return_value = (MagicMock(), [mock_tool_result])
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies/managed-service",
                json={
                    "session_id": "test-managed-123",
                    "query": "cassandra deps assembly=mx-rms platform=rmsag2"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_managed_service_error(self, async_client):
        """Test managed service query error."""
        mock_tool_result = MagicMock()
        mock_tool_result.success = False
        mock_tool_result.data = None
        mock_tool_result.error = "Missing parameters"

        with patch("main.ManagedServiceQueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.return_value = (MagicMock(), [mock_tool_result])
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies/managed-service",
                json={
                    "session_id": "test-managed-error",
                    "query": "invalid managed query"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_managed_service_exception(self, async_client):
        """Test managed service query with exception."""
        with patch("main.ManagedServiceQueryProcessor.process_query", new_callable=AsyncMock) as mock_process, \
             patch("main.get_conversation_history", new_callable=AsyncMock) as mock_history:
            mock_process.side_effect = Exception("Managed service error")
            mock_history.return_value = []

            response = await async_client.post(
                "/dependencies/managed-service",
                json={
                    "session_id": "test-managed-exc",
                    "query": "test"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"
            assert "Managed service error" in data["error"]


class TestRequestValidation:
    """Tests for request validation."""

    @pytest.mark.asyncio
    async def test_missing_session_id(self, async_client):
        """Test that missing session_id returns validation error."""
        response = await async_client.post(
            "/dependencies",
            json={"query": "test query"}
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_missing_query(self, async_client):
        """Test that missing query returns validation error."""
        response = await async_client.post(
            "/dependencies",
            json={"session_id": "test-123"}
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_empty_body(self, async_client):
        """Test that empty body returns validation error."""
        response = await async_client.post(
            "/dependencies",
            json={}
        )
        assert response.status_code == 422
