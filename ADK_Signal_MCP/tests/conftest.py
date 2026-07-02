"""Shared test fixtures.

Mocks the SignalHttpClient so tests never hit the real Signal API.
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
def mock_signal_client():
    """Return a mock SignalHttpClient."""
    client = MagicMock()
    client.base_url = "https://signal-api.walmart.com"
    return client


@pytest.fixture
def mock_signal_service(mock_signal_client):
    """Return a SignalService backed by the mock client."""
    from src.services.signal_service import SignalService
    return SignalService(mock_signal_client)


@pytest.fixture
def patched_service(mock_signal_service):
    """Patch get_signal_service() in every provider module so tools use the mock.

    The tool modules use ``from src.providers._shared import get_signal_service``,
    which creates a local reference. We must patch at each usage site.
    """
    with (
        patch(
            "src.providers._shared.get_signal_service",
            return_value=mock_signal_service,
        ),
        patch(
            "src.providers.inventory_tools.get_signal_service",
            return_value=mock_signal_service,
        ),
        patch(
            "src.providers.metadata_tools.get_signal_service",
            return_value=mock_signal_service,
        ),
        patch(
            "src.providers.oe_report_tools.get_signal_service",
            return_value=mock_signal_service,
        ),
    ):
        yield mock_signal_service
