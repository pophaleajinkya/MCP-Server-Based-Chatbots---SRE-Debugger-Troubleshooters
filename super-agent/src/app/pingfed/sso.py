"""
SSO login for PingFederate-protected services (e.g. intl.logs.prod.walmart.com).

Two strategies tried in order:
  1. HTTP path  — follow the Dex → PingFederate redirect chain with plain HTTP
                  (fast, no browser; works when PF session cookies are warm)
  2. Browser    — headless Playwright → SSO button → PF form → auth_tokens cookie
                  (always works; slower ~10-20 s)

Returns {"access_token": ..., "refresh_token": ...} on success, None on failure.

Credentials:
    username / password — passed explicitly by the caller (from config/env).
    UPN suffix (@homeoffice.wal-mart.com) is appended automatically if missing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import unquote, urlparse

import requests

from app.pingfed._pfed import (
    NeedsCredentials,
    follow_auto_submit_forms,
    has_meta_refresh,
    is_pfed_login_form,
    submit_credentials,
)

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

UPN_SUFFIX  = "@homeoffice.wal-mart.com"
COOKIE_NAME = "auth_tokens"
BROWSER_UA  = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# verify=False is intentional: internal Walmart staging services use self-signed certs
_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501


# ── Helpers ────────────────────────────────────────────────────────────────────

def _upn(username: str) -> str:
    return username if "@" in username else f"{username}{UPN_SUFFIX}"


def _parse_auth_tokens(raw: str) -> Optional[dict]:
    """Extract access_token / refresh_token from the auth_tokens cookie value."""
    try:
        parsed = json.loads(unquote(raw))
        if isinstance(parsed, dict) and parsed.get("access_token"):
            return parsed
    except Exception:
        pass
    # Regex fallback for malformed/double-encoded cookies.
    # access_token is required; refresh_token is optional.
    access  = re.search(r'"access_token"\s*:\s*"([^"]+)"', raw)
    if not access:
        return None
    refresh = re.search(r'"refresh_token"\s*:\s*"([^"]+)"', raw)
    result: dict = {"access_token": access.group(1)}
    if refresh:
        result["refresh_token"] = refresh.group(1)
    return result


def _create_session(timeout=(120, 300)) -> requests.Session:
    s = requests.Session()
    s.verify      = _HTTP_CLIENT_KWARGS["verify"]
    s.trust_env   = False
    s.headers["User-Agent"] = BROWSER_UA
    s._default_timeout = timeout  # type: ignore[attr-defined]
    return s


# ── HTTP path (fast) ──────────────────────────────────────────────────────────

def _http_login(
    base_url: str,
    username: str,
    password: str,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    """Follow the Dex → PingFederate redirect chain over plain HTTP.

    Returns parsed auth_tokens dict, or None if the HTTP path fails.
    Caller should fall back to _browser_login() on None.
    """
    if session is None:
        session = _create_session()
    timeout = getattr(session, "_default_timeout", (120, 300))

    resp = session.get(f"{base_url}/config/dex_login", **{**_HTTP_CLIENT_KWARGS, "timeout": timeout})
    resp.raise_for_status()
    dex_url = resp.text.strip().strip("'\"").replace(" ", "+")
    if not dex_url.startswith("http"):
        log.debug("pingfed: dex_login returned non-URL response: %r", dex_url[:80])
        return None
    resp = session.get(dex_url, **{**_HTTP_CLIENT_KWARGS, "timeout": timeout})

    # Follow any meta-refresh loops on the PF side (up to 3)
    for _ in range(3):
        at_pf = "pfedprod" in resp.url or "pfedcert" in resp.url
        if not at_pf:
            break
        if has_meta_refresh(resp.text) and not is_pfed_login_form(resp.text):
            resp = session.get(resp.url, **{**_HTTP_CLIENT_KWARGS, "timeout": timeout})
        else:
            break

    at_pf = "pfedprod" in resp.url or "pfedcert" in resp.url

    if not at_pf:
        # Already authenticated — look for cookie
        for c in session.cookies:
            if c.name == COOKIE_NAME:
                tokens = _parse_auth_tokens(c.value)
                if tokens and not tokens.get("refresh_token"):
                    log.warning(
                        "pingfed: already-authenticated path for %s — "
                        "refresh_token missing, forcing browser fallback.",
                        base_url,
                    )
                    return None
                return tokens
        return None

    resp = submit_credentials(session, resp.url, username, password, timeout=timeout)
    resp = follow_auto_submit_forms(session, resp, timeout=timeout)

    for c in session.cookies:
        if c.name == COOKIE_NAME:
            tokens = _parse_auth_tokens(c.value)
            if tokens and not tokens.get("refresh_token"):
                log.warning(
                    "pingfed: HTTP login for %s got access_token but missing refresh_token "
                    "— cookie may have been truncated. Falling back to browser login.",
                    base_url,
                )
                return None  # force browser fallback which gets the full cookie
            return tokens
    return None


# ── Browser path (reliable fallback) ─────────────────────────────────────────

async def _browser_login(
    base_url: str,
    username: str,
    password: str,
) -> Optional[dict]:
    """Headless Chromium login via Playwright."""
    from playwright.async_api import async_playwright

    pw      = await async_playwright().start()
    browser = None
    try:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=BROWSER_UA,
        )
        page = await context.new_page()

        log.info("pingfed: navigating to %s", base_url)
        await page.goto(base_url, wait_until="networkidle")
        await asyncio.sleep(1.5)

        # Click SSO login button
        for selector in [
            'button[data-test="sso-login-btn"]',
            'button:has-text("Login with SSO")',
            'a:has-text("Login with SSO")',
        ]:
            try:
                elem = page.locator(selector).first
                if await elem.is_visible(timeout=2000):
                    await elem.click()
                    await asyncio.sleep(3.0)
                    break
            except Exception:
                continue

        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(1.0)

        # Fill PingFederate form
        for selector in [
            "#username1", "#username",
            'input[name="username"]', 'input[name="pf.username"]',
            'input[type="text"]',
        ]:
            try:
                elem = page.locator(selector).first
                if await elem.is_visible(timeout=1000):
                    await elem.fill(username)
                    break
            except Exception:
                continue

        for selector in [
            "#password", 'input[name="password"]',
            'input[name="pf.pass"]', 'input[type="password"]',
        ]:
            try:
                elem = page.locator(selector).first
                if await elem.is_visible(timeout=1000):
                    await elem.fill(password)
                    break
            except Exception:
                continue

        await asyncio.sleep(0.5)

        for selector in [
            "a.ping-button", "#signOnButton",
            'button[type="submit"]', 'input[type="submit"]',
            'button:has-text("Sign In")', 'button:has-text("Sign On")',
            'button:has-text("Login")',
        ]:
            try:
                elem = page.locator(selector).first
                if await elem.is_visible(timeout=500):
                    await elem.click()
                    break
            except Exception:
                continue

        await asyncio.sleep(2.0)

        # Wait for redirect back to app
        try:
            hostname = urlparse(base_url).hostname or ""
            if hostname:
                await page.wait_for_url(f"**{hostname}**", timeout=30000)
            else:
                await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(2.0)

        # Extract auth_tokens cookie
        for c in await context.cookies():
            if c.get("name") == COOKIE_NAME and c.get("value"):
                tokens = _parse_auth_tokens(c["value"])
                if tokens:
                    log.info("pingfed: browser login successful")
                    return tokens

        log.warning("pingfed: auth_tokens cookie not found after browser login")
        return None

    finally:
        if browser:
            await browser.close()
        await pw.stop()


# ── Public API ─────────────────────────────────────────────────────────────────

async def login(
    base_url: str,
    username: str,
    password: str,
) -> Optional[dict]:
    """Authenticate against a PingFederate-protected service.

    Tries the fast HTTP path first; falls back to headless browser if it fails.

    Args:
        base_url:  Target service root URL (e.g. "https://intl.logs.prod.walmart.com").
        username:  SSO username. UPN suffix appended automatically if missing.
        password:  SSO password.

    Returns:
        {"access_token": str, "refresh_token": str} on success, None on failure.
    """
    upn = _upn(username)

    try:
        tokens = _http_login(base_url, upn, password)
        if tokens:
            log.info("pingfed: HTTP login successful for %s", base_url)
            return tokens
    except NeedsCredentials:
        pass
    except Exception as exc:
        log.debug("pingfed: HTTP login failed (%s), trying browser", exc)

    log.info("pingfed: falling back to browser login for %s", base_url)
    try:
        return await asyncio.wait_for(_browser_login(base_url, upn, password), timeout=120)
    except asyncio.TimeoutError:
        log.error("pingfed: browser login timed out after 120s for %s", base_url)
        return None
