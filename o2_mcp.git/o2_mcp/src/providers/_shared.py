"""Shared helpers for all providers.

Centralises path constants, the doc cache, and the per-request
QueryService factory so each provider module stays focused on its
own tools/resources.
"""
from __future__ import annotations

import re as _re
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.http_client import O2HttpClient, _bearer_to_basic, _is_full_cookie_json, _is_session_token
from src.services.query_service import QueryService

# ---------------------------------------------------------------------------
# Data directory layout
# ---------------------------------------------------------------------------
_DATA_DIR      = Path(__file__).parent.parent.parent / "data"
_RESOURCES_DIR = _DATA_DIR / "resources"
_PROMPTS_DIR   = _DATA_DIR / "prompts"

AGENT_GUIDE        = _RESOURCES_DIR / "AGENT.md"
DATAFUSION_SQL_DOC = _RESOURCES_DIR / "datafusion_sql.md"
O2_FUNCTIONS_DOC   = _RESOURCES_DIR / "openobserve_functions.md"
O2_GUIDE_DOC       = _RESOURCES_DIR / "openobserve.md"
RETRY_GUIDE        = _PROMPTS_DIR   / "retry_guide.md"

# ---------------------------------------------------------------------------
# Doc cache — populated on first read, lives for process lifetime
# ---------------------------------------------------------------------------
_doc_cache: dict[Path, str] = {}


def read_doc(path: Path, fallback: str) -> str:
    """Return cached doc text, reading from disk only on first access."""
    if path not in _doc_cache:
        _doc_cache[path] = path.read_text(encoding="utf-8") if path.exists() else fallback
    return _doc_cache[path]


# ---------------------------------------------------------------------------
# Per-request QueryService factory
# ---------------------------------------------------------------------------

def build_service(endpoint: str, bearer_token: str, organization: str) -> QueryService:
    """Build a QueryService from per-request parameters.

    Args:
        endpoint:     O2 API base URL (e.g. https://intl.logs.prod.walmart.com)
        bearer_token: Raw PingFederate access_token; converted to Basic auth internally.
        organization: O2 org ID (e.g. "default").

    Raises:
        ValueError: When endpoint or auth token cannot be resolved.
    """
    cfg = get_settings()

    ep = (endpoint or cfg.endpoint or "").rstrip("/")
    if not ep:
        raise ValueError(
            "endpoint is required. Pass it from wcnp_get_o2_config output, "
            "or set O2_ENDPOINT env var."
        )
    if not ep.endswith("/api"):
        ep += "/api"

    token = (bearer_token or "").strip()

    if token:
        # Session tokens (full cookie JSON or bare "session <id>") must be passed
        # as bearer_token so O2HttpClient uses the Cookie header, not Basic auth.
        # JWT access tokens are converted to Basic auth as before.
        if _is_full_cookie_json(token) or _is_session_token(token):
            return QueryService(
                O2HttpClient(base_url=ep, bearer_token=token, org_id=organization or cfg.org_id or "default")
            )
        else:
            auth_token = _bearer_to_basic(token)
    elif cfg.auth_token:
        auth_token = cfg.auth_token
    else:
        raise ValueError(
            "bearer_token is required. "
            "Call pingfed_playwright_token(cluster_lb=...) and pass auth['token'] here."
        )

    org = organization or cfg.org_id or "default"
    return QueryService(O2HttpClient(base_url=ep, auth_token=auth_token, org_id=org))


# Re-export for provider modules that need regex
RE = _re
