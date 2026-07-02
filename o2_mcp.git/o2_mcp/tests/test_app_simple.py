"""Tests for app.py — Module structure only (app tests skipped)."""
import pytest


class TestAppModule:
    """Test app.py module."""
    
    def test_module_imports(self):
        """App module should import."""
        import app
        assert hasattr(app, '_VERSION')
        assert app._VERSION == "1.0.0"

