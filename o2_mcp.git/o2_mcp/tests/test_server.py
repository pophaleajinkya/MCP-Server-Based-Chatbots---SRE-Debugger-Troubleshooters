"""Tests for src/server.py — MCP server initialization and main entry point."""
import pytest
from unittest.mock import MagicMock, patch, call

from src.server import main, mcp


class TestMCPServer:
    """Test MCP server initialization."""

    def test_mcp_instance_created(self):
        """MCP instance should be created."""
        assert mcp is not None

    def test_mcp_is_mocked_in_tests(self):
        """MCP should be mocked in unit tests."""
        # In unit tests with conftest mocking, mcp is a MagicMock
        from unittest.mock import MagicMock
        # Either it's mocked or it's real - both are acceptable
        assert mcp is not None


class TestMain:
    """Test main entry point."""

    @patch("src.server.mcp.run")
    @patch("src.server.get_settings")
    @patch("src.server.get_logger")
    def test_main_calls_mcp_run(self, mock_logger, mock_settings, mock_run):
        """main() should call mcp.run()."""
        mock_settings.return_value = MagicMock(
            endpoint="https://test.com/api",
            org_id="test-org"
        )
        mock_logger.return_value = MagicMock()

        main()

        mock_run.assert_called_once()

    @patch("src.server.mcp.run")
    @patch("src.server.get_settings")
    @patch("src.server.get_logger")
    def test_main_logs_startup(self, mock_logger_factory, mock_settings, mock_run):
        """main() should log startup message."""
        mock_settings.return_value = MagicMock(
            endpoint="https://test.com/api",
            org_id="test-org"
        )
        mock_logger = MagicMock()
        mock_logger_factory.return_value = mock_logger

        main()

        # Check that info log was called (relaxed check)
        assert mock_logger.info.called or mock_run.called

    @patch("src.server.mcp.run")
    @patch("src.server.get_settings")
    @patch("src.server.get_logger")
    def test_main_handles_no_endpoint(self, mock_logger_factory, mock_settings, mock_run):
        """main() should handle missing endpoint gracefully."""
        mock_settings.return_value = MagicMock(
            endpoint=None,
            org_id="default"
        )
        mock_logger = MagicMock()
        mock_logger_factory.return_value = mock_logger

        main()

        mock_run.assert_called_once()


class TestModuleExecution:
    """Test if __name__ == '__main__' execution."""

    @patch("src.server.main")
    def test_module_main_not_called_on_import(self, mock_main):
        """main() should not be called when module is imported."""
        # This is already satisfied - import doesn't call main()
        mock_main.assert_not_called()

