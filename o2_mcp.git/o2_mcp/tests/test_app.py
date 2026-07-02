"""Tests for app.py — ASGI application module."""
import pytest
from unittest.mock import patch, MagicMock
import os


class TestAppModule:
    """Test app.py module structure."""
    
    def test_version_constant(self):
        """Should define VERSION constant."""
        from app import _VERSION
        assert _VERSION == "1.0.0"
    
    def test_module_has_app(self):
        """Should have app attribute."""
        import app
        assert hasattr(app, 'app')
    
    def test_module_has_main(self):
        """Should have main function."""
        import app
        assert hasattr(app, 'main')
        assert callable(app.main)
    
    @patch("app.uvicorn.run")
    def test_main_calls_uvicorn(self, mock_run):
        """main() should call uvicorn.run."""
        from app import main
        main()
        mock_run.assert_called_once()
    
    @patch("app.uvicorn.run")
    def test_main_uses_correct_app_string(self, mock_run):
        """main() should pass correct app string."""
        from app import main
        main()
        args = mock_run.call_args[0]
        assert args[0] == "app:app"
    
    @patch("app.uvicorn.run")
    @patch.dict(os.environ, {"APP_PORT": "9000"})
    def test_main_respects_port_env(self, mock_run):
        """main() should respect APP_PORT env var."""
        from app import main
        main()
        args, kwargs = mock_run.call_args
        assert kwargs["port"] == 9000
    
    @patch("app.uvicorn.run")
    @patch.dict(os.environ, {"APP_HOST": "127.0.0.1"})
    def test_main_respects_host_env(self, mock_run):
        """main() should respect APP_HOST env var."""
        from app import main
        main()
        args, kwargs = mock_run.call_args
        assert kwargs["host"] == "127.0.0.1"

