"""
PingFederate SSO authentication package.

Self-contained — no dependency on other internal packages.
Can be extracted to its own repo without modification.

Public API
----------
    from app.pingfed import get_token, invalidate, warm, close

    # get_token() is universal — works for ANY PingFed-protected service.
    # The hostname determines which login strategy is used.

    # O2 cluster tokens (session-based, Dex → PingFed)
    token: str = await get_token("intl.logs.prod.walmart.com")

    # DX Hub token (platform-hub JWT)
    token: str = await get_token("dx.walmart.com")

    # Prometheus MMS token (oauth2-proxy cookie)
    token: str = await get_token("prometheus.query.prod.mms.walmart.net")

    # Common operations
    await invalidate("intl.logs.prod.walmart.com")   # force re-login on next get_token()
    await warm("intl.logs.prod.walmart.com")         # pre-warm at startup
    await close()                                    # graceful shutdown

    # Backward-compat aliases (thin wrappers):
    hub_jwt: str = await get_hub_token()             # == get_token("dx.walmart.com")
    await invalidate_hub()                           # == invalidate("dx.walmart.com")
    await warm_hub()                                 # == warm("dx.walmart.com")
"""
from app.pingfed.store import (
    get_token,
    get_full_tokens,
    invalidate,
    warm,
    get_hub_token,
    invalidate_hub,
    warm_hub,
    close,
)

__all__ = [
    "get_token",
    "get_full_tokens",
    "invalidate",
    "warm",
    "get_hub_token",
    "invalidate_hub",
    "warm_hub",
    "close",
]
