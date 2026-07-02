"""
PingFederate HTML form parsing and HTTP submission helpers.

Handles the redirect chain: Dex → PingFederate → target app.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests


# ── Exceptions ─────────────────────────────────────────────────────────────────

class NeedsCredentials(Exception):
    """Raised when PingFederate requires credentials but none were provided."""


# ── HTML helpers ───────────────────────────────────────────────────────────────

class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action: Optional[str] = None
        self.method: str = "POST"
        self.fields: dict = {}

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "form":
            self.action = attr.get("action")
            self.method = attr.get("method", "POST").upper()
        elif tag == "input":
            name = attr.get("name")
            if name:
                self.fields[name] = attr.get("value", "")


def parse_form(html: str, base_url: str = "") -> Tuple[Optional[str], str, dict]:
    p = _FormParser()
    p.feed(html)
    action = p.action
    if action and base_url:
        action = urljoin(base_url, action)
    return action, p.method, p.fields


def has_meta_refresh(html: str) -> bool:
    return bool(re.search(r'<meta\s+http-equiv=["\']?refresh["\']?', html, re.IGNORECASE))


def has_auto_submit_form(html: str) -> bool:
    lower = html.lower()
    if "<form" not in lower:
        return False
    return (
        "onload" in lower
        or "samlrequest" in lower
        or "samlresponse" in lower
        or "wresult" in lower
        or ("document.forms" in lower and ".submit()" in lower)
    )


def is_pfed_login_form(html: str) -> bool:
    lower = html.lower()
    return "pf.username" in lower or "pf.pass" in lower


# ── Credential submission ──────────────────────────────────────────────────────

PFED_ADAPTER_ID = "AdpFormUPN"


def submit_credentials(
    session: requests.Session,
    pfed_url: str,
    username: str,
    password: str,
    timeout=(120, 300),
) -> requests.Response:
    resp = session.get(pfed_url, timeout=timeout)
    if has_meta_refresh(resp.text):
        resp = session.get(pfed_url, timeout=timeout)

    pfed_domain = urlparse(pfed_url).hostname or ""
    if pfed_domain:
        session.cookies.set("pf.chosenBU", "ho", domain=pfed_domain)
        session.cookies.set("pf.chosenDomain", "US", domain=pfed_domain)

    action, _, fields = parse_form(resp.text, base_url=resp.url)

    if action and fields:
        fields["pf.username"] = username
        fields["pf.pass"] = password
        fields["pf.ok"] = "clicked"
        if "pf.cancel" in fields:
            fields["pf.cancel"] = ""
        if "pf.adapterId" not in fields:
            fields["pf.adapterId"] = PFED_ADAPTER_ID
        return session.post(action, data=fields, timeout=timeout)

    # Fallback: direct POST
    return session.post(pfed_url, data={
        "pf.username": username,
        "pf.pass": password,
        "pf.adapterId": PFED_ADAPTER_ID,
        "pf.ok": "clicked",
        "pf.cancel": "",
    }, timeout=timeout)


def follow_auto_submit_forms(
    session: requests.Session,
    response: requests.Response,
    timeout=(120, 300),
    max_hops: int = 5,
) -> requests.Response:
    for _ in range(max_hops):
        if response.status_code not in (200, 401):
            break
        text = response.text
        if has_meta_refresh(text) and not has_auto_submit_form(text):
            response = session.get(response.url, timeout=timeout)
            continue
        if not has_auto_submit_form(text):
            break
        if is_pfed_login_form(text):
            break
        action, method, fields = parse_form(text, base_url=response.url)
        if not action or not fields:
            break
        if method == "POST":
            response = session.post(action, data=fields, timeout=timeout)
        else:
            response = session.get(action, params=fields, timeout=timeout)
    return response
