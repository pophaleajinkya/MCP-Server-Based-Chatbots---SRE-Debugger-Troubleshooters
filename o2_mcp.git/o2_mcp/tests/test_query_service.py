"""Tests for src/services/query_service.py — QueryService class."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.query_service import QueryService, _compact_fields, _essential_fields, _prune_schema
from src.http_client import O2HttpClient, O2ApiError, O2ConnectionError


@pytest.fixture
def mock_client():
    """Create a mock O2HttpClient."""
    client = MagicMock(spec=O2HttpClient)
    client.org = "test-org"
    client.parse_time_range = MagicMock(return_value=(1000000, 2000000))
    client.now_us = MagicMock(return_value=2000000)
    return client


@pytest.fixture
def service(mock_client):
    """Create QueryService with mock client."""
    return QueryService(client=mock_client)


class TestQueryServiceInit:
    """Test QueryService initialization."""

    def test_init_with_client(self, mock_client):
        """Should accept client parameter."""
        svc = QueryService(client=mock_client)
        assert svc._client is mock_client

    @patch("src.services.query_service.O2HttpClient")
    def test_init_without_client_creates_one(self, mock_http_client):
        """Should create client if none provided."""
        svc = QueryService()
        assert svc._client is not None

    def test_org_property(self, service, mock_client):
        """Should expose org property."""
        assert service.org == "test-org"


@pytest.mark.asyncio
class TestExecuteSQL:
    """Test execute_sql method."""

    async def test_successful_query(self, service, mock_client):
        """Should execute SQL and return results."""
        mock_client.post = AsyncMock(return_value={
            "hits": [{"field": "value"}],
            "total": 1
        })

        result = await service.execute_sql("SELECT * FROM logs")

        assert result["success"] is True
        assert "hits" in result
        assert result["total"] == 1

    async def test_adds_limit_if_missing(self, service, mock_client):
        """Should add LIMIT clause if not present."""
        mock_client.post = AsyncMock(return_value={"hits": [], "total": 0})

        await service.execute_sql("SELECT * FROM logs", limit=100)

        # Check the SQL passed includes LIMIT
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert "LIMIT" in payload["query"]["sql"]

    async def test_rejects_non_select(self, service, mock_client):
        """Should reject non-SELECT queries."""
        result = await service.execute_sql("DELETE FROM logs")

        assert result["success"] is False
        assert "Only SELECT" in result["error"]

    async def test_handles_api_error(self, service, mock_client):
        """Should handle O2ApiError gracefully."""
        mock_client.post = AsyncMock(
            side_effect=O2ApiError(500, "Internal error")
        )

        result = await service.execute_sql("SELECT * FROM logs")

        assert result["success"] is False
        assert "error" in result

    async def test_marks_auth_expired_on_401(self, service, mock_client):
        """Should set auth_expired=True for 401 errors."""
        mock_client.post = AsyncMock(
            side_effect=O2ApiError(401, "Unauthorized")
        )

        result = await service.execute_sql("SELECT * FROM logs")

        assert result["success"] is False
        assert result.get("auth_expired") is True

    async def test_uses_custom_time_range(self, service, mock_client):
        """Should use start_time/end_time if provided."""
        mock_client.post = AsyncMock(return_value={"hits": [], "total": 0})

        await service.execute_sql(
            "SELECT * FROM logs",
            start_time=1000,
            end_time=2000
        )

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["query"]["start_time"] == 1000
        assert payload["query"]["end_time"] == 2000

    async def test_clamps_limit_to_max(self, service, mock_client):
        """Should clamp limit to max_limit from settings."""
        mock_client.post = AsyncMock(return_value={"hits": [], "total": 0})

        # Try to request 100000 rows
        await service.execute_sql("SELECT * FROM logs", limit=100000)

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        # Should be clamped to max_limit (typically 10000)
        assert payload["query"]["size"] <= 10000


@pytest.mark.asyncio
class TestSearchAround:
    """Test search_around method."""

    async def test_successful_search(self, service, mock_client):
        """Should fetch logs around timestamp."""
        mock_client.get = AsyncMock(return_value={"logs": []})

        result = await service.search_around("test-stream", 1234567890, size=10)

        assert result["success"] is True
        mock_client.get.assert_called_once()

    async def test_handles_error(self, service, mock_client):
        """Should handle errors gracefully."""
        mock_client.get = AsyncMock(side_effect=O2ApiError(404, "Not found"))

        result = await service.search_around("test-stream", 1234567890)

        assert result["success"] is False


@pytest.mark.asyncio
class TestGetFieldValues:
    """Test get_field_values method."""

    async def test_fetches_multiple_fields(self, service, mock_client):
        """Should fetch values for multiple fields in parallel."""
        mock_client.post = AsyncMock(return_value={
            "hits": [{"value": "test", "count": 5}],
            "total": 1
        })

        result = await service.get_field_values(
            stream="logs",
            fields=["field1", "field2"]
        )

        assert result["success"] is True
        assert "fields" in result
        assert len(result["fields"]) == 2

    async def test_handles_partial_errors(self, service, mock_client):
        """Should handle partial errors across fields."""
        # First call succeeds, second fails
        mock_client.post = AsyncMock(
            side_effect=[
                {"hits": [{"value": "test"}]},
                O2ApiError(500, "Error")
            ]
        )

        result = await service.get_field_values(
            stream="logs",
            fields=["field1", "field2"]
        )

        assert result["success"] is True
        assert "partial_errors" in result

    async def test_marks_auth_expired_on_partial_401(self, service, mock_client):
        """Should mark auth_expired if any field query returns 401."""
        mock_client.post = AsyncMock(
            side_effect=[
                {"hits": []},
                O2ApiError(401, "Unauthorized")
            ]
        )

        result = await service.get_field_values(
            stream="logs",
            fields=["field1", "field2"]
        )

        assert result.get("auth_expired") is True


@pytest.mark.asyncio
class TestListStreams:
    """Test list_streams method."""

    async def test_lists_streams(self, service, mock_client):
        """Should list all streams."""
        mock_client.get = AsyncMock(return_value={
            "list": [{"name": "stream1"}, {"name": "stream2"}]
        })

        result = await service.list_streams()

        assert result["success"] is True
        assert result["total"] == 2

    async def test_handles_error(self, service, mock_client):
        """Should handle errors."""
        mock_client.get = AsyncMock(side_effect=O2ConnectionError("Timeout"))

        result = await service.list_streams()

        assert result["success"] is False


@pytest.mark.asyncio
class TestGetStreamSchema:
    """Test get_stream_schema method."""

    async def test_fetches_schema(self, service, mock_client):
        """Should fetch stream schema."""
        mock_client.get = AsyncMock(return_value={
            "name": "test-stream",
            "schema": [{"name": "_timestamp", "type": "Int64"}],
            "settings": {}
        })

        result = await service.get_stream_schema("test-stream")

        assert "name" in result
        assert result["name"] == "test-stream"

    async def test_handles_error(self, service, mock_client):
        """Should handle errors."""
        mock_client.get = AsyncMock(side_effect=O2ApiError(404, "Not found"))

        result = await service.get_stream_schema("missing-stream")

        assert result["success"] is False


@pytest.mark.asyncio
class TestValidateSQL:
    """Test validate_sql method."""

    async def test_valid_sql_returns_true(self, service, mock_client):
        """Should return valid=True for valid SQL."""
        mock_client.post = AsyncMock(return_value={"hits": []})

        result = await service.validate_sql("SELECT * FROM logs")

        assert result["valid"] is True

    async def test_invalid_sql_returns_false(self, service, mock_client):
        """Should return valid=False for invalid SQL."""
        mock_client.post = AsyncMock(
            side_effect=O2ApiError(400, "Syntax error")
        )

        result = await service.validate_sql("SELECT INVALID")

        assert result["valid"] is False
        assert "error" in result

    @patch("src.services.query_service.get_settings")
    async def test_respects_disable_flag(self, mock_settings, service, mock_client):
        """Should skip validation if disabled."""
        mock_settings.return_value = MagicMock(enable_sql_validation=False)

        result = await service.validate_sql("SELECT * FROM logs")

        assert result["valid"] is True
        assert "disabled" in result["message"]


@pytest.mark.asyncio
class TestValidateVRL:
    """Test validate_vrl method."""

    async def test_valid_vrl_returns_true(self, service, mock_client):
        """Should return valid=True for valid VRL."""
        mock_client.post = AsyncMock(return_value={"output": []})

        result = await service.validate_vrl(".message = \"test\"")

        assert result["valid"] is True

    async def test_invalid_vrl_returns_false(self, service, mock_client):
        """Should return valid=False for invalid VRL."""
        mock_client.post = AsyncMock(
            side_effect=O2ApiError(400, "VRL error")
        )

        result = await service.validate_vrl("invalid vrl")

        assert result["valid"] is False


class TestCompactFields:
    """Test _compact_fields helper."""

    def test_groups_by_type(self):
        """Should group fields by type."""
        fields = [
            {"name": "f1", "type": "Utf8"},
            {"name": "f2", "type": "Utf8"},
            {"name": "f3", "type": "Int64"}
        ]

        result = _compact_fields(fields)

        assert "Utf8" in result
        assert "Int64" in result
        assert len(result["Utf8"]) == 2
        assert len(result["Int64"]) == 1

    def test_handles_empty_list(self):
        """Should handle empty field list."""
        result = _compact_fields([])
        assert result == {}


class TestEssentialFields:
    """Test _essential_fields helper."""

    def test_includes_timestamp(self):
        """Should always include _timestamp."""
        result = _essential_fields({})
        assert "_timestamp" in result

    def test_includes_partition_keys(self):
        """Should include enabled partition keys."""
        settings = {
            "partition_keys": {
                "key1": {"field": "field1", "disabled": False},
                "key2": {"field": "field2", "disabled": True}
            }
        }

        result = _essential_fields(settings)

        assert "field1" in result
        assert "field2" not in result

    def test_includes_fts_keys(self):
        """Should include full_text_search_keys."""
        settings = {
            "full_text_search_keys": ["message", "log"]
        }

        result = _essential_fields(settings)

        assert "message" in result
        assert "log" in result


class TestPruneSchema:
    """Test _prune_schema helper."""

    def test_returns_full_schema_when_small(self):
        """Should return full schema if below threshold."""
        data = {
            "name": "test",
            "schema": [{"name": "f1", "type": "Utf8"}],
            "settings": {}
        }

        result = _prune_schema(data)

        assert result["returned_fields"] == 1

    def test_prunes_large_schema_with_prompt(self):
        """Should prune large schema based on prompt."""
        fields = [{"name": f"field{i}", "type": "Utf8"} for i in range(100)]
        data = {
            "name": "test",
            "schema": fields,
            "settings": {}
        }

        result = _prune_schema(data, user_prompt="field5 field10")

        # Should only return mentioned fields + essentials
        assert result["returned_fields"] < result["total_fields"]

    def test_respects_full_schema_flag(self):
        """Should return all fields if full_schema=True."""
        fields = [{"name": f"field{i}", "type": "Utf8"} for i in range(100)]
        data = {
            "name": "test",
            "schema": fields,
            "settings": {}
        }

        result = _prune_schema(data, full_schema=True)

        assert result["returned_fields"] == result["total_fields"]

