"""
ADK tool: pingfed_token

Exposes PingFederate SSO authentication as a first-class ADK tool.
The agent (and any downstream MCP caller) can call this to get a live
bearer token for a specific Walmart internal service cluster (e.g. OpenObserve).

Token is shared across all pods via Redis — only one pod runs the
headless Playwright login per cluster; all others return the cached token instantly.

Future: move to a dedicated auth MCP server when the auth package is
extracted to its own repo.
"""
from __future__ import annotations

import json as _json
import logging

from app.config import get_settings
from app.pingfed import get_full_tokens, get_hub_token

log = logging.getLogger(__name__)


async def pingfed_token(cluster_lb: str) -> dict:
    """
    Obtain a live PingFederate bearer token for a Walmart internal service cluster.

    Each OpenObserve cluster (e.g. intl.logs.prod.walmart.com, gtp.logs.prod.walmart.com)
    requires its own token. Tokens are cached in Redis per cluster so only one pod
    performs the headless Playwright SSO login; all other pods reuse the cached token.
    Automatically refreshes the token in the background before it expires.

    Use this tool when:
    - A downstream service (e.g. OpenObserve) requires a Bearer token for authentication.
    - An MCP tool call returns a 4XX error (token expired or invalid).
    - You need to query a specific OpenObserve cluster and need its token.

    Parameters:
        cluster_lb: The load-balancer hostname of the target cluster.
                    Accepts bare hostname or full URL — scheme and path are stripped.
                    Examples:
                      "intl.logs.prod.walmart.com"
                      "gtp.logs.prod.walmart.com"
                      "https://intl.logs.prod.walmart.com"

    Returns:
        On success:  {
            "success": true,
            "token": "<bearer>",        # pass this as bearer_token to o2_mcp tools
            "token_type": "Bearer",
            "cluster_lb": "<host>"
        }
        On failure:  {"success": false, "error": "<reason>", "cluster_lb": "<host>"}

    Note:
        For O2 session tokens ("session ..."), the returned token already includes the
        full cookie JSON (access_token + refresh_token).  Pass it verbatim as the
        bearer_token parameter to execute_sql / search_around / etc.
    """
    if not cluster_lb or not cluster_lb.strip():
        return {
            "success": False,
            "error": "cluster_lb is required. Provide the OpenObserve cluster hostname.",
            "cluster_lb": "",
        }

    s = get_settings()
    if not s.sso_username or not s.sso_password:
        return {
            "success": False,
            "error": (
                "SSO not configured. "
                "Set SSO_USERNAME and SSO_PASSWORD environment variables."
            ),
            "cluster_lb": cluster_lb,
        }

    try:
        tokens = await get_full_tokens(cluster_lb)
        access_token = tokens.get("access_token", "").strip()
        refresh_token = tokens.get("refresh_token", "").strip()

        if not access_token:
            log.error("pingfed_token: empty access_token returned for %s", cluster_lb)
            return {
                "success": False,
                "error": "SSO login completed but returned an empty access_token. Check SSO credentials.",
                "cluster_lb": cluster_lb,
            }

        # For O2 session tokens the REST API requires BOTH access_token and
        # refresh_token in the auth_tokens cookie — build a compact cookie JSON
        # that http_client.py can use verbatim.
        if access_token.startswith("session "):
            if not refresh_token:
                # Incomplete SSO session — missing refresh_token means the login captured
                # only a partial cookie (e.g. regex fallback in sso.py).  Return error so
                # the agent knows to retry rather than silently passing a broken token.
                log.error(
                    "pingfed_token: session token missing refresh_token for %s — "
                    "SSO cookie was incomplete",
                    cluster_lb,
                )
                return {
                    "success": False,
                    "error": (
                        "SSO session token obtained but refresh_token is missing. "
                        "The login may have captured an incomplete cookie. "
                        "Retry in a few seconds or check SSO health."
                    ),
                    "cluster_lb": cluster_lb,
                }
            bearer = _json.dumps(
                {"access_token": access_token, "refresh_token": refresh_token},
                separators=(",", ":"),
            )
        else:
            bearer = access_token  # JWT flows: pass raw access_token as before

        log.info("pingfed_token: token dispensed for %s", cluster_lb)
        return {
            "success": True,
            "token": bearer,
            "token_type": "Bearer",
            "cluster_lb": cluster_lb,
        }
    except Exception as exc:
        log.error("pingfed_token: failed for %s — %s", cluster_lb, exc)
        return {"success": False, "error": str(exc), "cluster_lb": cluster_lb}


async def pingfed_hub() -> dict:
    """
    Obtain a live platform-hub JWT token for Walmart internal MCP servers.

    This token is produced by authenticating against dx.walmart.com via PingFederate
    SSO.  The resulting JWT has client_id=platform-hub which is whitelisted by
    MCP servers like ChangeIQ that validate tokens via PingFed introspection.

    The token is cached in Redis and shared across all pods — only one pod performs
    the SSO login; all others reuse the cached token.  Automatically refreshes
    in the background before expiry.

    Use this tool when:
    - An MCP server (e.g. ChangeIQ) requires a Bearer token with client_id=platform-hub.
    - A downstream tool call returns a 401/403 error indicating an expired or invalid token.
    - You need to authenticate against any Walmart internal service that accepts
      platform-hub tokens.

    Returns:
        On success:  {
            "success": true,
            "token": "<JWT>",        # pass as Bearer token to MCP servers
            "token_type": "Bearer"
        }
        On failure:  {"success": false, "error": "<reason>"}
    """
    s = get_settings()
    if not s.sso_username or not s.sso_password:
        return {
            "success": False,
            "error": (
                "SSO not configured. "
                "Set SSO_USERNAME and SSO_PASSWORD environment variables."
            ),
        }

    try:
        token = await get_hub_token()
        if not token:
            log.error("pingfed_hub: empty token returned")
            return {
                "success": False,
                "error": "DX SSO login completed but returned an empty token. Check SSO credentials.",
            }

        log.info("pingfed_hub: token dispensed (length=%d)", len(token))
        return {
            "success": True,
            "token": token,
            "token_type": "Bearer",
        }
    except Exception as exc:
        log.error("pingfed_hub: failed — %s", exc)
        return {"success": False, "error": str(exc)}
