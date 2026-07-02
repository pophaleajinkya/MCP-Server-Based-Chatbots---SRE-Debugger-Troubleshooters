"""Shared helpers for all providers.

Centralises path constants, the doc cache, and the singleton
Valid8HttpClient + Valid8Service so each provider module stays
focused on its own tools/resources.
"""
from __future__ import annotations

from pathlib import Path

from src.config import get_settings
from src.http_client import Valid8HttpClient
from src.services.valid8_service import Valid8Service

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
# Singleton Valid8 HTTP client & service
# ---------------------------------------------------------------------------
_valid8_client: Valid8HttpClient | None = None
_valid8_service: Valid8Service | None = None


def get_valid8_service() -> Valid8Service:
    """Return a singleton Valid8Service backed by a singleton HTTP client.

    Authentication is via X-API-Key + X-Tenant headers, configured in
    Settings and passed per-request by the service layer.
    """
    global _valid8_client, _valid8_service
    if _valid8_service is None:
        _valid8_client = Valid8HttpClient()
        _valid8_service = Valid8Service(_valid8_client)
    return _valid8_service
