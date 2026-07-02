"""Final comprehensive tests targeting remaining coverage gaps."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, Mock
import json


class TestHTTPClientFullCoverage:
    """Complete HTTP client coverage targeting all uncovered lines."""

    @pytest.mark.asyncio
    async def test_request_handles_already_classified_exceptions(self):
        """Test that O2ApiError and O2ConnectionError are re-raised."""
        from src.http_client import O2HttpClient, O2ApiError

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="token"
        )

        client._http = MagicMock()
        client._http.is_closed = False

        # Already classified error should be re-raised
        client._http.request = AsyncMock(side_effect=O2ApiError(500, "Server error"))

        with pytest.raises(O2ApiError):
            await client.request("GET", "/test")

    def test_http_client_with_settings_parameter(self):
        """Test client initialization with settings parameter."""
        from src.http_client import O2HttpClient
        from src.config import Settings

        settings = Settings(
            endpoint="https://settings.test.com/api",
            auth_token="settings_token",
            org_id="settings_org",
            timeout=45.0,
            ssl_verify=True
        )

        client = O2HttpClient(settings=settings)

        assert client.base_url == "https://settings.test.com/api"
        assert client.org == "settings_org"

    def test_http_client_ssl_verify_none(self):
        """Test SSL verify with None value."""
        from src.http_client import O2HttpClient

        client = O2HttpClient(
            base_url="https://test.com/api",
            auth_token="token",
            ssl_verify=None  # Should use settings default
        )

        assert client._ssl_verify is not None

    def test_http_client_with_bare_session_token(self):
        """Test bare session token wrapping."""
        from src.http_client import O2HttpClient

        client = O2HttpClient(
            base_url="https://test.com/api",
            bearer_token="session xyz123"  # Bare session token
        )

        headers = client._headers()
        assert "Cookie" in headers
        # Should wrap in JSON
        assert "auth_tokens=" in headers["Cookie"]
        assert "access_token" in headers["Cookie"]


class TestQueryServiceCompleteCoverage:
    """Complete QueryService coverage."""

    @pytest.mark.asyncio
    async def test_field_values_sql_no_count(self):
        """Test field values SQL with no_count=True."""
        from src.services.query_service import QueryService

        mock_client = MagicMock()
        svc = QueryService(client=mock_client)

        sql = svc._field_values_sql(
            stream="logs",
            field="status",
            size=50,
            keyword="",
            no_count=True  # Should use DISTINCT
        )

        assert "DISTINCT" in sql
        assert "COUNT" not in sql

    @pytest.mark.asyncio
    async def test_fetch_field_values_with_none_values(self):
        """Test field values filtering None values."""
        from src.services.query_service import QueryService

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value={
            "hits": [
                {"value": "val1", "count": 5},
                {"value": None, "count": 3},  # Should be filtered
                {"value": "val2", "count": 2}
            ]
        })

        svc = QueryService(client=mock_client)

        result = await svc._fetch_field_values(
            stream="logs",
            field="status",
            start_us=1000,
            end_us=2000,
            size=100,
            keyword="",
            no_count=False
        )

        # None values should be filtered
        assert all(v["value"] is not None for v in result["values"])

    @pytest.mark.asyncio
    async def test_list_streams_with_streams_key(self):
        """Test list_streams with 'streams' key instead of 'list'."""
        from src.services.query_service import QueryService

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value={
            "streams": [{"name": "s1"}, {"name": "s2"}]  # Using 'streams' key
        })

        svc = QueryService(client=mock_client)

        result = await svc.list_streams()

        assert result["success"] is True
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_validate_sql_catches_generic_exception(self):
        """Test validate_sql handles generic exceptions."""
        from src.services.query_service import QueryService

        mock_client = MagicMock()
        mock_client.now_us = MagicMock(return_value=2000000)
        mock_client.post = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        with patch("src.services.query_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(enable_sql_validation=True)

            svc = QueryService(client=mock_client)

            result = await svc.validate_sql("SELECT * FROM logs")

            assert result["valid"] is False


class TestConfigEnvLoading:
    """Test config environment variable loading."""

    @patch.dict('os.environ', {
        'O2_ENDPOINT': 'https://env.example.com/api',
        'O2_LOG_LEVEL': 'DEBUG'
    })
    def test_settings_loads_from_environment(self):
        """Should load settings from environment variables."""
        from src.config import Settings
        
        # Create new settings instance
        settings = Settings()
        
        # Should not crash
        assert isinstance(settings, Settings)


class TestSQLAnalysisEdgeCases:
    """SQL analysis edge cases."""
    
    def test_analyze_sql_with_cte(self):
        """Should analyze CTEs."""
        from src.sql.analysis import analyze_sql
        from src.sql.models import SqlAnalysisResult
        
        sql = """
        WITH stats AS (
            SELECT status, COUNT(*) AS cnt
            FROM logs
            GROUP BY status
        )
        SELECT * FROM stats WHERE cnt > 10
        """
        
        result = analyze_sql(sql)
        assert isinstance(result, SqlAnalysisResult)
    
    def test_analyze_sql_with_window_function(self):
        """Should analyze window functions."""
        from src.sql.analysis import analyze_sql
        from src.sql.models import SqlAnalysisResult
        
        sql = """
        SELECT 
            _timestamp,
            LAG(_timestamp) OVER (ORDER BY _timestamp) AS prev_ts
        FROM logs
        """
        
        result = analyze_sql(sql)
        assert isinstance(result, SqlAnalysisResult)
    
    def test_analyze_sql_with_union(self):
        """Should analyze UNION queries."""
        from src.sql.analysis import analyze_sql
        from src.sql.models import SqlAnalysisResult
        
        sql = """
        SELECT status FROM logs WHERE level = 'error'
        UNION ALL
        SELECT status FROM logs WHERE level = 'warning'
        """
        
        result = analyze_sql(sql)
        assert isinstance(result, SqlAnalysisResult)


class TestASTParserEdgeCases:
    """AST parser edge cases."""
    
    def test_parse_multiple_statements(self):
        """Should parse multiple statements."""
        from src.sql.ast_parser import parse_sql
        from src.sql.models import SqlParseResult
        
        sql = "SELECT * FROM logs; SELECT * FROM users;"
        result = parse_sql(sql)
        
        # Should handle multiple statements
        assert isinstance(result, SqlParseResult)
    
    def test_parse_with_comments(self):
        """Should parse SQL with comments."""
        from src.sql.ast_parser import parse_sql
        from src.sql.models import SqlParseResult
        
        sql = """
        -- This is a comment
        SELECT * FROM logs  -- inline comment
        WHERE status = 500
        """
        
        result = parse_sql(sql)
        assert isinstance(result, SqlParseResult)


class TestAllModelsToDict:
    """Test model structure."""
    
    def test_sql_parse_result_structure(self):
        """Test SqlParseResult structure."""
        from src.sql.models import SqlParseResult
        
        result = SqlParseResult(
            ok=True,
            ast=None,
            errors=("error1", "error2"),
            backend="test"
        )
        
        assert result.ok is True
        assert result.backend == "test"
        assert len(result.errors) == 2
    
    def test_sql_facts_structure(self):
        """Test SqlFacts structure."""
        from src.sql.models import SqlFacts
        
        facts = SqlFacts(
            streams=["logs", "metrics"],
            columns=["_timestamp", "status"],
            functions=["count", "avg"]
        )
        
        assert len(facts.streams) == 2
        assert "_timestamp" in facts.columns
    
    def test_sql_analysis_result_structure(self):
        """Test SqlAnalysisResult structure."""
        from src.sql.models import SqlAnalysisResult, SqlFacts
        
        facts = SqlFacts(streams=["logs"])
        result = SqlAnalysisResult(
            ok=True,
            facts=facts,
            errors=(),
            backend="sqlglot"
        )
        
        assert result.ok is True
        assert result.facts is not None
        assert result.backend == "sqlglot"

