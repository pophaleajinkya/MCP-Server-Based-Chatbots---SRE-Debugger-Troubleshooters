"""Shared helpers for all providers.

Centralises path constants, the doc cache, and the singleton
SignalHttpClient + SignalService so each provider module stays
focused on its own tools/resources.
"""
from __future__ import annotations

from pathlib import Path

from src.config import get_settings
from src.http_client import SignalHttpClient
from src.services.signal_service import SignalService

# ---------------------------------------------------------------------------
# Data directory layout
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_RESOURCES_DIR = _DATA_DIR / "resources"
_PROMPTS_DIR = _DATA_DIR / "prompts"

AGENT_GUIDE = _RESOURCES_DIR / "AGENT.md"
API_REFERENCE = _RESOURCES_DIR / "api_reference.md"

# ---------------------------------------------------------------------------
# Doc cache — populated on first read, lives for process lifetime
# ---------------------------------------------------------------------------
_doc_cache: dict[Path, str] = {}


def read_doc(path: Path, fallback: str) -> str:
    """Return cached doc text, reading from disk only on first access."""
    if path not in _doc_cache:
        _doc_cache[path] = (
            path.read_text(encoding="utf-8") if path.exists() else fallback
        )
    return _doc_cache[path]


# ---------------------------------------------------------------------------
# Singleton Signal HTTP client & service
# ---------------------------------------------------------------------------
_signal_client: SignalHttpClient | None = None
_signal_service: SignalService | None = None


def get_signal_service() -> SignalService:
    """Return a singleton SignalService backed by a singleton HTTP client."""
    global _signal_client, _signal_service
    if _signal_service is None:
        _signal_client = SignalHttpClient()
        _signal_service = SignalService(_signal_client)
    return _signal_service
