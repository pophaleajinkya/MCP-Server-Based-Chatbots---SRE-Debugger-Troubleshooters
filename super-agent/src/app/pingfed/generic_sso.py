"""
Generic PingFederate SSO login for any service behind PingFed / oauth2-proxy.

Works with:
  - oauth2-proxy (e.g. prometheus.query.prod.mms.walmart.net → _oauth2_proxy cookie)
  - DX Hub       (e.g. dx.walmart.com → hub-ping cookie)
  - Any service that redirects to pfedprod.wal-mart.com for authentication

Flow (identical for all services):
  1. GET base_url → 302 to PingFederate (directly or via Platform SSO IDP)
  2. Follow meta-refresh loops at PingFed
  3. POST credentials to PingFederate login form
  4. Follow SAML/auto-submit redirects back to the target service
  5. Extract the named auth cookie

Pure HTTP — no Playwright/browser required.  Works in WCNP production pods.

Usage:
    tokens = login(
        base_url="https://prometheus.query.prod.mms.walmart.net",
        username="SVC_intl_sre_ops@homeoffice.Wal-Mart.com",
        password="...",
        cookie_name="_oauth2_proxy",
    )
    # → {"access_token": "<cookie value>"}
"""
from __future__ import annotations

import logging
import warnings
from typing import Callable, Optional

from app.pingfed._pfed import (
    follow_auto_submit_forms,
    has_meta_refresh,
    is_pfed_login_form,
    submit_credentials,
)

log = logging.getLogger(__name__)

UPN_SUFFIX = "@homeoffice.wal-mart.com"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _upn(username: str) -> str:
    """Append UPN suffix if not already present."""
    return username if "@" in username else f"{username}{UPN_SUFFIX}"


def _create_session():
    """Create a requests.Session configured for internal Walmart services."""
    import requests

    s = requests.Session()
    # verify=False is intentional: internal Walmart services use self-signed certs
    s.verify = False  # noqa: S501
    s.trust_env = False
    s.headers["User-Agent"] = BROWSER_UA
    s._default_timeout = (120, 300)  # type: ignore[attr-defined]
    return s


def login(
    base_url: str,
    username: str,
    password: str,
    cookie_name: str,
    token_parser: Optional[Callable[[str], Optional[dict]]] = None,
) -> Optional[dict]:
    """Authenticate against a PingFed-protected service and extract an auth cookie.

    Args:
        base_url:      Target service root URL (e.g. "https://prometheus.query.prod.mms.walmart.net").
        username:      SSO username.  UPN suffix appended automatically if missing.
        password:      SSO password.
        cookie_name:   Name of the auth cookie to extract after login
                       (e.g. "_oauth2_proxy", "hub-ping").
        token_parser:  Optional callable to transform the raw cookie value into a
                       token dict.  When None the raw cookie value is returned as
                       ``{"access_token": <raw_value>}``.

    Returns:
        On success: {"access_token": str, ...} (shape depends on token_parser)
        On failure: None
    """
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    upn = _upn(username)
    session = _create_session()
    timeout = (120, 300)

    try:
        # Step 1: GET target service → redirects to PingFed (directly or via IDP)
        resp = session.get(base_url, timeout=30)  # noqa: S501 — verify=False set on session (internal Walmart certs)
        log.info(
            "generic_sso: %s → initial redirect → %s (status %d)",
            base_url, resp.url, resp.status_code,
        )

        at_pf = "pfedprod" in resp.url or "pfedcert" in resp.url
        if not at_pf:
            # Not redirected to PingFed — maybe already authenticated
            for c in session.cookies:
                if c.name == cookie_name:
                    return _parse_cookie(c.value, cookie_name, token_parser)
            log.warning(
                "generic_sso: %s not redirected to PingFed (URL: %s)",
                base_url, resp.url,
            )
            return None

        # Step 2: Follow any meta-refresh loops before submitting credentials
        for _ in range(5):
            if has_meta_refresh(resp.text) and not is_pfed_login_form(resp.text):
                resp = session.get(resp.url, timeout=30)  # noqa: S501 — verify=False set on session (internal Walmart certs)
            else:
                break

        # Step 3: Submit credentials using shared _pfed helpers
        resp = submit_credentials(session, resp.url, upn, password, timeout=timeout)

        # Step 4: Follow auto-submit forms (SAML assertions back to target)
        resp = follow_auto_submit_forms(session, resp, timeout=timeout)

        # Step 5: Extract the named auth cookie
        for c in session.cookies:
            if c.name == cookie_name:
                result = _parse_cookie(c.value, cookie_name, token_parser)
                if result:
                    log.info(
                        "generic_sso: login successful for %s (cookie=%s, token_len=%d)",
                        base_url, cookie_name, len(result.get("access_token", "")),
                    )
                    return result

        log.warning(
            "generic_sso: login succeeded but %s cookie not found for %s",
            cookie_name, base_url,
        )
        return None

    except Exception as exc:
        log.error("generic_sso: login failed for %s: %s", base_url, exc)
        return None


def _parse_cookie(
    raw: str,
    cookie_name: str,
    token_parser: Optional[Callable[[str], Optional[dict]]],
) -> Optional[dict]:
    """Transform a raw cookie value into a token dict."""
    if token_parser is not None:
        return token_parser(raw)
    # Default: use the raw cookie value as the access_token
    if raw:
        return {"access_token": raw}
    log.warning("generic_sso: empty cookie value for %s", cookie_name)
    return None
