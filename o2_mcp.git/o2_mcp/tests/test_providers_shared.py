"""Tests for src/providers/_shared.py — Shared provider helpers."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from src.providers._shared import (
    read_doc,
    build_service,
    AGENT_GUIDE,
    DATAFUSION_SQL_DOC,
    O2_FUNCTIONS_DOC,
    O2_GUIDE_DOC,
    RETRY_GUIDE,
)


class TestReadDoc:
    """Test read_doc function."""

    def test_reads_existing_file(self, tmp_path):
        """Should read file content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content", encoding="utf-8")

        result = read_doc(test_file, "fallback")

        assert result == "test content"

    def test_returns_fallback_for_missing_file(self, tmp_path):
        """Should return fallback if file doesn't exist."""
        missing = tmp_path / "missing.txt"

        result = read_doc(missing, "fallback text")

        assert result == "fallback text"

    def test_caches_content(self, tmp_path):
        """Should cache content on first read."""
        test_file = tmp_path / "cached.txt"
        test_file.write_text("original", encoding="utf-8")

        # First read
        result1 = read_doc(test_file, "fallback")

        # Modify file
        test_file.write_text("modified", encoding="utf-8")

        # Second read should return cached value
        result2 = read_doc(test_file, "fallback")

        assert result1 == result2 == "original"


class TestBuildService:
    """Test build_service function."""

    @patch("src.providers._shared.QueryService")
    @patch("src.providers._shared.O2HttpClient")
    @patch("src.providers._shared.get_settings")
    def test_creates_service_with_endpoint(self, mock_settings, mock_client, mock_service):
        """Should create QueryService with provided endpoint."""
        mock_settings.return_value = MagicMock(
            org_id="default",
            auth_token=""
        )

        build_service(
            endpoint="https://test.com",
            bearer_token="token123",
            organization="test-org"
        )

        mock_client.assert_called_once()
        mock_service.assert_called_once()

    @patch("src.providers._shared.get_settings")
    def test_requires_endpoint(self, mock_settings):
        """Should raise ValueError if endpoint is missing."""
        mock_settings.return_value = MagicMock(
            endpoint="",
            org_id="default"
        )

        with pytest.raises(ValueError, match="endpoint is required"):
            build_service(endpoint="", bearer_token="token", organization="")

    @patch("src.providers._shared.get_settings")
    def test_requires_bearer_token(self, mock_settings):
        """Should raise ValueError if bearer_token is missing."""
        mock_settings.return_value = MagicMock(
            endpoint="",
            auth_token="",
            org_id="default"
        )

        with pytest.raises(ValueError, match="bearer_token is required"):
            build_service(
                endpoint="https://test.com",
                bearer_token="",
                organization=""
            )

    @patch("src.providers._shared.QueryService")
    @patch("src.providers._shared.O2HttpClient")
    @patch("src.providers._shared.get_settings")
    def test_adds_api_path_if_missing(self, mock_settings, mock_client, mock_service):
        """Should append /api to endpoint if missing."""
        mock_settings.return_value = MagicMock(
            org_id="default",
            auth_token=""
        )

        build_service(
            endpoint="https://test.com",
            bearer_token="token",
            organization=""
        )

        # Check that /api was added
        call_args = mock_client.call_args
        assert call_args[1]["base_url"].endswith("/api")

    @patch("src.providers._shared.QueryService")
    @patch("src.providers._shared.O2HttpClient")
    @patch("src.providers._shared.get_settings")
    def test_handles_session_token(self, mock_settings, mock_client, mock_service):
        """Should handle session tokens correctly."""
        mock_settings.return_value = MagicMock(
            org_id="default",
            auth_token=""
        )

        build_service(
            endpoint="https://test.com",
            bearer_token="session xyz123",
            organization="org"
        )

        # Session token should be passed as bearer_token
        call_args = mock_client.call_args
        assert "bearer_token" in call_args[1]

    @patch("src.providers._shared.QueryService")
    @patch("src.providers._shared.O2HttpClient")
    @patch("src.providers._shared.get_settings")
    def test_uses_organization_parameter(self, mock_settings, mock_client, mock_service):
        """Should use provided organization."""
        mock_settings.return_value = MagicMock(
            org_id="default",
            auth_token=""
        )

        build_service(
            endpoint="https://test.com",
            bearer_token="token",
            organization="custom-org"
        )

        call_args = mock_client.call_args
        assert call_args[1]["org_id"] == "custom-org"


class TestPathConstants:
    """Test path constants are defined."""

    def test_agent_guide_defined(self):
        """AGENT_GUIDE should be a Path."""
        assert isinstance(AGENT_GUIDE, Path)

    def test_datafusion_sql_doc_defined(self):
        """DATAFUSION_SQL_DOC should be a Path."""
        assert isinstance(DATAFUSION_SQL_DOC, Path)

    def test_o2_functions_doc_defined(self):
        """O2_FUNCTIONS_DOC should be a Path."""
        assert isinstance(O2_FUNCTIONS_DOC, Path)

    def test_o2_guide_doc_defined(self):
        """O2_GUIDE_DOC should be a Path."""
        assert isinstance(O2_GUIDE_DOC, Path)

    def test_retry_guide_defined(self):
        """RETRY_GUIDE should be a Path."""
        assert isinstance(RETRY_GUIDE, Path)

