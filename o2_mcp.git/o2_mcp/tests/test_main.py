"""Tests for src/__main__.py — Module entry point."""
import pytest
from unittest.mock import patch


class TestMainModule:
    """Test __main__.py execution."""


    def test_imports_main_from_server(self):
        """Should import main from src.server."""
        from src.__main__ import main
        from src.server import main as server_main
        # They should be the same function
        assert main is server_main

