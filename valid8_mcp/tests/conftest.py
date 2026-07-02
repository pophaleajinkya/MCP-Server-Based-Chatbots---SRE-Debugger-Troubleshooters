"""Shared test fixtures.

Mocks the Valid8HttpClient so tests never hit the real Valid8 API.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def mock_valid8_client():
    """Return a mock Valid8HttpClient."""
    client = MagicMock()
    client.base_url = "https://valid8.walmart.com"
    return client


@pytest.fixture
def mock_valid8_service(mock_valid8_client):
    """Return a Valid8Service backed by the mock client."""
    from src.services.valid8_service import Valid8Service
    return Valid8Service(mock_valid8_client)


@pytest.fixture
def patched_service(mock_valid8_service):
    """Patch get_valid8_service() in every provider module so tools use the mock.

    The tool modules use ``from src.providers._shared import get_valid8_service``,
    which creates a local reference. We must patch at each usage site.
    """
    with (
        patch(
            "src.providers._shared.get_valid8_service",
            return_value=mock_valid8_service,
        ),
        patch(
            "src.providers.ca_tools.get_valid8_service",
            return_value=mock_valid8_service,
        ),
        patch(
            "src.providers.mx_tools.get_valid8_service",
            return_value=mock_valid8_service,
        ),
    ):
        yield mock_valid8_service
