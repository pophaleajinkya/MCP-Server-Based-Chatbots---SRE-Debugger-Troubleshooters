"""
DX Hub SSO login — authenticates against dx.walmart.com via PingFederate.

Produces a ``platform-hub`` JWT token accepted by ChangeIQ and other
MCP servers that validate via PingFed introspection with whitelisted
``client_id=platform-hub``.

Flow:
  1. GET dx.walmart.com → 302 to pfedprod.wal-mart.com (PingFederate)
  2. POST credentials to PingFederate login form
  3. Follow SAML/auto-submit redirects back to dx.walmart.com
  4. Extract JWT from ``hub-ping`` cookie

This module reuses the existing ``_pfed.py`` helpers (submit_credentials,
follow_auto_submit_forms) for form parsing and SAML redirect handling.

Pure HTTP — no Playwright/browser required.  Works in WCNP production.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional
from urllib.parse import unquote

from app.pingfed._pfed import (
    follow_auto_submit_forms,
    has_meta_refresh,
    is_pfed_login_form,
    submit_credentials,
)

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DX_SSO_URL = "https://dx.walmart.com"
DX_TOKEN_COOKIE = "hub-ping"
UPN_SUFFIX = "@homeoffice.wal-mart.com"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# verify=False is intentional: internal Walmart staging services use self-signed certs
_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501


# ── Helpers ───────────────────────────────────────────────────────────────────

def _upn(username: str) -> str:
    """Append UPN suffix if not already present."""
    return username if "@" in username else f"{username}{UPN_SUFFIX}"


def _get_token_expiry(token: str) -> float:
    """Extract the ``exp`` claim from a JWT without full validation.

    Returns 0.0 if the token is not a valid JWT or has no exp claim.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return 0.0
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


def _create_session():
    """Create a requests.Session configured for internal Walmart services."""
    import requests

    s = requests.Session()
    s.verify = _HTTP_CLIENT_KWARGS["verify"]
    s.trust_env = False
    s.headers["User-Agent"] = BROWSER_UA
    s._default_timeout = (120, 300)  # type: ignore[attr-defined]
    return s


# ── Public API ────────────────────────────────────────────────────────────────

def login(username: str, password: str) -> Optional[dict]:
    """Authenticate against dx.walmart.com via PingFed SSO and extract the JWT.

    Args:
        username: SSO username. UPN suffix appended automatically if missing.
        password: SSO password.

    Returns:
        On success: {"access_token": "<JWT>", "expires_at": <epoch float>}
        On failure: None
    """
    import warnings
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    upn = _upn(username)
    session = _create_session()
    timeout = (120, 300)

    try:
        # Step 1: GET dx.walmart.com → PingFed redirect
        resp = session.get(DX_SSO_URL, timeout=30)
        log.info("hub_sso: initial redirect → %s (status %d)", resp.url, resp.status_code)

        at_pf = "pfedprod" in resp.url or "pfedcert" in resp.url
        if not at_pf:
            # Not redirected to PingFed — check if already authenticated
            for c in session.cookies:
                if c.name == DX_TOKEN_COOKIE:
                    return _parse_hub_cookie(c.value)
            log.warning("hub_sso: not redirected to PingFed (URL: %s)", resp.url)
            return None

        # Step 2: Follow any meta-refresh loops before submitting credentials
        for _ in range(3):
            if has_meta_refresh(resp.text) and not is_pfed_login_form(resp.text):
                resp = session.get(resp.url, timeout=30)
            else:
                break

        # Step 3: Submit credentials using shared _pfed helpers
        resp = submit_credentials(session, resp.url, upn, password, timeout=timeout)

        # Step 4: Follow auto-submit forms (SAML assertions)
        resp = follow_auto_submit_forms(session, resp, timeout=timeout)

        # Step 5: Extract JWT from hub-ping cookie
        for c in session.cookies:
            if c.name == DX_TOKEN_COOKIE:
                result = _parse_hub_cookie(c.value)
                if result:
                    log.info(
                        "hub_sso: obtained JWT (length=%d, client_id=platform-hub)",
                        len(result["access_token"]),
                    )
                    return result

        log.warning("hub_sso: login succeeded but no %s cookie found", DX_TOKEN_COOKIE)
        return None

    except Exception as exc:
        log.error("hub_sso: login failed: %s", exc)
        return None


def _parse_hub_cookie(raw: str) -> Optional[dict]:
    """Parse the hub-ping cookie value and extract the JWT token.

    The cookie is a URL-encoded JSON object with a "token" field containing the JWT.

    Returns:
        {"access_token": "<JWT>", "expires_at": <epoch float>} or None
    """
    try:
        parsed = json.loads(unquote(raw))
        token = parsed.get("token", "")
        if token:
            expires_at = _get_token_expiry(token)
            return {"access_token": token, "expires_at": expires_at}
    except Exception as exc:
        log.warning("hub_sso: failed to parse %s cookie: %s", DX_TOKEN_COOKIE, exc)
    return None