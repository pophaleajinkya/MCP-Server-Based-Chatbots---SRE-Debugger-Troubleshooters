"""Shared pytest fixtures and configuration for all tests."""
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Set test environment variables BEFORE any app imports
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-api-key-12345")
os.environ.setdefault("AZURE_OPENAI_MODEL", "gpt-4.1")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-10-21")
os.environ.setdefault("AZURE_EMBEDDING_MODEL", "text-embedding-ada-002")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("REDIS_USERNAME", "testuser")
os.environ.setdefault("SRE_OPS_URL", "http://localhost:9099")
os.environ.setdefault("TOPOLOGY_API_URL", "https://topology-api.test.com/api/v2/dependency-map")
os.environ.setdefault("TOPOLOGY_WM_CONSUMER_ID", "test-consumer-id")
os.environ.setdefault("TOPOLOGY_WM_SVC_NAME", "TEST-TOPOLOGY-SERVICE")
os.environ.setdefault("TOPOLOGY_WM_SVC_ENV", "test")
os.environ.setdefault("CONVERSATION_API_URL", "http://localhost:8020/session/conversations")
os.environ.setdefault("DX_CONSOLE_URL", "https://console.dx.test.com")
os.environ.setdefault("DX_CONSOLE_APPS_PATH", "/proxy/wcnp-apps/apps")
os.environ.setdefault("SRE_OPS_DOWNSTREAM_PATH", "/dependencies/downstream")
os.environ.setdefault("SRE_OPS_UPSTREAM_PATH", "/dependencies/upstream")


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_namespace():
    return "atlas-inventory-crons"


@pytest.fixture
def sample_app_name():
    return "inventory-ei-bootstrap-cell004"


@pytest.fixture
def sample_session_id():
    return "test-session-12345678-1234-1234-1234-123456789012"


@pytest.fixture
def sample_available_apps():
    return [
        "inventory-ei-bootstrap-cell004",
        "purge-us-wm-amb-cell000",
        "error-log-processor-cron",
        "arc-cleanup",
        "gi-reports",
        "allocation-alert-cron",
        "retry-event-cron",
        "eg-reports",
        "mfc-purge-cleanup",
        "gdc-ei-bootstrap",
    ]


@pytest.fixture
def sample_upstream_deps():
    return [
        {
            "name": "payment-service",
            "namespace": "payments-prod",
            "app": "payment-service",
            "source": "topology",
            "direction": "upstream",
            "icon": "k8app",
            "tier": "Tier 1",
            "type": "service",
        },
        {
            "name": "user-api",
            "namespace": "users-prod",
            "app": "user-api",
            "source": "database",
            "direction": "upstream",
            "icon": "k8app",
            "tier": "Tier 2",
            "wcnpId": "wcnp-123",
        },
    ]


@pytest.fixture
def sample_downstream_deps():
    return [
        {
            "name": "reporting-service",
            "namespace": "reports-prod",
            "app": "reporting-service",
            "source": "topology",
            "direction": "downstream",
            "icon": "k8app",
            "tier": "Tier 3",
        }
    ]


@pytest.fixture
def sample_source_breakdown():
    return {
        "database_only": 1,
        "topology_only": 1,
        "both": 0,
        "total": 2,
        "upstream_count": 2,
        "downstream_count": 0,
    }


@pytest.fixture
def mock_conversation_history():
    return [
        {
            "role": "user",
            "content": "get applications for atlas-inventory-crons",
            "timestamp": "2026-02-06T19:29:11Z",
        },
        {
            "role": "assistant",
            "content": "Found 45 apps in namespace 'atlas-inventory-crons'.",
            "timestamp": "2026-02-06T19:29:32Z",
        },
    ]


# ---------------------------------------------------------------------------
# App fixture (lazy import to avoid settings validation at collection time)
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Return the FastAPI application instance."""
    from main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
    """Synchronous TestClient."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client(app):
    """Async HTTPX client for the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# MCP client fixture (session-scoped — session manager can only start once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mcp_client():
    """
    Synchronous TestClient with the FastAPI lifespan running.

    Session-scoped because StreamableHTTPSessionManager.run() can only be
    called once per instance (per process).

    Using Starlette's TestClient (not async httpx) because:
    - TestClient starts/stops the FastAPI lifespan correctly as a context manager
    - It drives async endpoints via anyio's blocking portal (no cross-task issues)
    - No async event loop scope conflicts with pytest-asyncio's session teardown
    """
    from main import app
    from starlette.testclient import TestClient as StarletteTestClient

    with StarletteTestClient(app, raise_server_exceptions=True) as client:
        yield client

