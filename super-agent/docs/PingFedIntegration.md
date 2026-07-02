# PingFederate Integration Guide

> **Status:** Draft — implementation pending.
> This document is designed to be consumed by an LLM to implement the integration.

---

## 1. Overview

The super-agent (A2A Health Agent) currently has **no authentication middleware**.
User identity is resolved loosely from request headers (`loginId`, `wm_llm_gw.user_name`)
or the JSON body (`user_id`). This document describes how to integrate
**PingFederate (PingFed) OAuth 2.0 / OIDC** token validation into the FastAPI
application so that every inbound request is authenticated via a JWT access token
issued by Walmart's PingFederate identity provider.

---

## 2. Goals

| # | Goal |
|---|------|
| 1 | Validate PingFed-issued JWT access tokens on **all** protected endpoints. |
| 2 | Extract the authenticated user identity from the token and make it available to downstream code (replacing the current header-sniffing logic). |
| 3 | Allow specific endpoints to remain **unauthenticated** (`/health`, `/docs`, `/redoc`, `/openapi.json`). |
| 4 | Support **both** opaque and JWT token formats (prefer local JWT validation; fall back to PingFed introspection for opaque tokens if needed). |
| 5 | Keep the implementation behind a feature flag so it can be enabled/disabled per environment. |
| 6 | Zero breaking changes to existing tests — unauthenticated mode must remain the default in `AGENT_ENV=local` / test environments. |

---

## 3. Architecture

```
┌──────────┐       ┌──────────────┐       ┌───────────────────┐
│  Client  │──────▶│  PingFed     │──────▶│  super-agent      │
│  (UI /   │  1.   │  Auth Server │  2.   │  FastAPI app      │
│  CLI)    │ OAuth │              │ JWT   │                   │
└──────────┘ flow  └──────────────┘       │  ┌─────────────┐  │
                                          │  │ AuthMiddleware│ │
                                          │  │ (new)        │ │
                                          │  └──────┬──────┘  │
                                          │         ▼         │
                                          │  ┌─────────────┐  │
                                          │  │ Routers      │ │
                                          │  │ /query, etc. │ │
                                          │  └─────────────┘  │
                                          └───────────────────┘
```

**Flow:**
1. Client authenticates with PingFederate and receives a JWT access token.
2. Client sends requests to super-agent with `Authorization: Bearer <token>`.
3. `PingFedAuthMiddleware` intercepts the request, validates the token, and injects
   the authenticated user into the request state.
4. Routers read the user from `request.state.user` instead of sniffing headers.

---

## 4. Configuration — New Settings

Add the following fields to the `Settings` class in `src/app/config.py`:

```python
# ── PingFed Authentication ────────────────────────────────────────────────
# Set PINGFED_AUTH_ENABLED=true to enforce JWT validation on all protected endpoints.
pingfed_auth_enabled: bool = False

# PingFed OIDC discovery endpoint (well-known URL).
# Example: https://fed.walmart.com/.well-known/openid-configuration
pingfed_issuer_url: str = ""

# JWKS URI — used to fetch PingFed's public signing keys for local JWT validation.
# If empty, auto-discovered from the OIDC well-known endpoint.
pingfed_jwks_uri: str = ""

# Expected audience claim in the JWT. Must match the OAuth client_id registered
# in PingFed for the super-agent.
pingfed_audience: str = ""

# Token issuer claim to validate (`iss`). If empty, derived from pingfed_issuer_url.
pingfed_token_issuer: str = ""

# Comma-separated list of allowed signing algorithms (default: RS256).
pingfed_algorithms: str = "RS256"

# How long (seconds) to cache the JWKS keyset before re-fetching.
pingfed_jwks_cache_ttl: int = 3600

# Paths that do NOT require authentication (glob patterns).
pingfed_public_paths: list[str] = [
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
]
```

### Environment Variables

| Variable | Required | Example |
|----------|----------|---------|
| `PINGFED_AUTH_ENABLED` | No (default `false`) | `true` |
| `PINGFED_ISSUER_URL` | Yes (when enabled) | `https://fed.walmart.com` |
| `PINGFED_JWKS_URI` | No (auto-discovered) | `https://fed.walmart.com/ext/oauth/jwks` |
| `PINGFED_AUDIENCE` | Yes (when enabled) | `super-agent-prod` |
| `PINGFED_TOKEN_ISSUER` | No | `https://fed.walmart.com` |
| `PINGFED_ALGORITHMS` | No (default `RS256`) | `RS256,ES256` |
| `PINGFED_JWKS_CACHE_TTL` | No (default `3600`) | `1800` |
| `PINGFED_PUBLIC_PATHS` | No | `["/health","/docs"]` |

---

## 5. New Files to Create

### 5.1 `src/app/auth/__init__.py`

Empty init or re-export `PingFedAuthMiddleware`.

### 5.2 `src/app/auth/pingfed.py`

This module contains:

#### 5.2.1 `JWKSClient` — JWKS Key Fetcher

```python
"""PingFederate JWT validation utilities."""

import time
import logging
from typing import Any

import httpx
from jose import jwt, JWTError

log = logging.getLogger(__name__)


class JWKSClient:
    """Fetches and caches PingFed's JWKS (JSON Web Key Set).
    
    Caches the key set for `cache_ttl` seconds to avoid hitting the JWKS
    endpoint on every request.
    """

    def __init__(self, jwks_uri: str, cache_ttl: int = 3600) -> None:
        self._jwks_uri = jwks_uri
        self._cache_ttl = cache_ttl
        self._keys: list[dict[str, Any]] = []
        self._last_fetch: float = 0.0

    async def get_signing_keys(self) -> list[dict[str, Any]]:
        """Return cached JWKS keys, refreshing if stale."""
        now = time.monotonic()
        if not self._keys or (now - self._last_fetch) > self._cache_ttl:
            await self._refresh()
        return self._keys

    async def _refresh(self) -> None:
        """Fetch JWKS from PingFed."""
        async with httpx.AsyncClient(verify=True) as client:
            resp = await client.get(self._jwks_uri, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        self._keys = data.get("keys", [])
        self._last_fetch = time.monotonic()
        log.info("Refreshed JWKS — %d keys loaded from %s", len(self._keys), self._jwks_uri)
```

#### 5.2.2 `validate_token()` — JWT Validation

```python
async def validate_token(
    token: str,
    jwks_client: JWKSClient,
    audience: str,
    issuer: str,
    algorithms: list[str],
) -> dict[str, Any]:
    """Decode and validate a PingFed JWT access token.

    Returns the decoded token claims on success.
    Raises ValueError with a descriptive message on failure.
    """
    keys = await jwks_client.get_signing_keys()
    if not keys:
        raise ValueError("No JWKS keys available — cannot validate token")

    try:
        claims = jwt.decode(
            token,
            {"keys": keys},
            algorithms=algorithms,
            audience=audience,
            issuer=issuer,
            options={
                "verify_aud": bool(audience),
                "verify_iss": bool(issuer),
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except JWTError as exc:
        raise ValueError(f"Token validation failed: {exc}") from exc

    return claims
```

#### 5.2.3 `extract_user_from_claims()` — User Identity

```python
def extract_user_from_claims(claims: dict[str, Any]) -> dict[str, str]:
    """Extract user identity fields from decoded JWT claims.

    Returns a dict with keys: user_id, user_name, user_type, email.
    Adapts to Walmart PingFed claim names.
    """
    return {
        "user_id": claims.get("sub", ""),
        "user_name": claims.get("preferred_username") or claims.get("sub", ""),
        "email": claims.get("email", ""),
        "user_type": claims.get("user_type", "ASSOCIATE"),
    }
```

### 5.3 `src/app/auth/middleware.py` — ASGI Middleware

```python
"""PingFederate authentication middleware (pure ASGI)."""

import fnmatch
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.pingfed import JWKSClient, validate_token, extract_user_from_claims
from app.config import get_settings

log = logging.getLogger(__name__)


class PingFedAuthMiddleware:
    """Pure ASGI middleware that validates PingFed JWT tokens.

    Skips validation for paths listed in settings.pingfed_public_paths.
    On success, sets request.state.authenticated_user with decoded identity.
    On failure, returns 401 JSON response.
    """

    def __init__(self, app: ASGIApp, jwks_client: JWKSClient) -> None:
        self.app = app
        self._jwks_client = jwks_client

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        settings = get_settings()

        # Skip auth for public paths
        if self._is_public_path(request.url.path, settings.pingfed_public_paths):
            await self.app(scope, receive, send)
            return

        # Extract Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header. Expected: Bearer <token>"},
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:]  # Strip "Bearer "

        try:
            claims = await validate_token(
                token=token,
                jwks_client=self._jwks_client,
                audience=settings.pingfed_audience,
                issuer=settings.pingfed_token_issuer or settings.pingfed_issuer_url,
                algorithms=settings.pingfed_algorithms.split(","),
            )
        except ValueError as exc:
            log.warning("PingFed token validation failed: %s", exc)
            response = JSONResponse(
                status_code=401,
                content={"detail": str(exc)},
            )
            await response(scope, receive, send)
            return

        # Inject authenticated user into request state
        scope.setdefault("state", {})
        scope["state"]["authenticated_user"] = extract_user_from_claims(claims)
        scope["state"]["token_claims"] = claims

        await self.app(scope, receive, send)

    @staticmethod
    def _is_public_path(path: str, public_patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in public_patterns)
```

---

## 6. Integration Points — Changes to Existing Files

### 6.1 `src/app/factory.py` — Register the Middleware

In `create_app()`, conditionally add `PingFedAuthMiddleware` **after** `CORSMiddleware`
(so CORS preflight OPTIONS requests are handled before auth):

```python
# In create_app(), after CORSMiddleware is added:

if s.pingfed_auth_enabled:
    from app.auth.pingfed import JWKSClient
    from app.auth.middleware import PingFedAuthMiddleware

    jwks_uri = s.pingfed_jwks_uri or f"{s.pingfed_issuer_url}/.well-known/openid-configuration"
    # NOTE: If using OIDC discovery, resolve jwks_uri from the discovery doc at startup.
    jwks_client = JWKSClient(jwks_uri=jwks_uri, cache_ttl=s.pingfed_jwks_cache_ttl)
    application.add_middleware(PingFedAuthMiddleware, jwks_client=jwks_client)
    log.info("PingFed authentication middleware enabled (issuer=%s)", s.pingfed_issuer_url)
```

### 6.2 `src/app/routers/query.py` — Use Authenticated User

Replace `_resolve_user_id()` to prefer the authenticated user from middleware:

```python
def _resolve_user_id(req: QueryRequest, request: Request) -> str:
    # 1. Prefer PingFed-authenticated identity (set by middleware)
    auth_user = getattr(request.state, "authenticated_user", None)
    if auth_user and auth_user.get("user_id"):
        return auth_user["user_id"]

    # 2. Fall back to existing header/body resolution (unauthenticated mode)
    uid = (
        req.user_id
        or request.headers.get("loginId")
        or request.headers.get("wm_llm_gw.user_name")
    )
    if not uid:
        raise HTTPException(
            status_code=422,
            detail=(
                "user_id is required. Supply it in the JSON body as 'user_id', "
                "or via the 'loginId' / 'wm_llm_gw.user_name' request header."
            ),
        )
    return uid
```

### 6.3 `src/app/request_context.py` — Optional Enhancement

When PingFed auth is enabled, `wm_llm_gw.user_name` can be auto-populated from
the authenticated user's identity, so the frontend doesn't need to send it separately.
In `extract_llm_headers()`, add a fallback:

```python
def extract_llm_headers(request: Request) -> dict[str, str]:
    headers = {k: request.headers.get(k, "") for k in LLM_HEADER_KEYS}
    
    # Auto-fill user_name from PingFed token if header is missing
    auth_user = getattr(request.state, "authenticated_user", None)
    if auth_user and not headers.get("wm_llm_gw.user_name"):
        headers["wm_llm_gw.user_name"] = auth_user.get("user_name", "")
    
    return headers
```

---

## 7. Dependencies

Add to `pyproject.toml` → `dependencies`:

```toml
"python-jose[cryptography]>=3.3.0",
```

This provides JWT decoding with RSA/EC key support.

---

## 8. OIDC Discovery (Optional Enhancement)

Instead of hardcoding `PINGFED_JWKS_URI`, resolve it from the OIDC discovery
endpoint at application startup (in `lifespan()`):

```python
async def _discover_jwks_uri(issuer_url: str) -> str:
    """Fetch JWKS URI from PingFed's OIDC discovery endpoint."""
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(verify=True) as client:
        resp = await client.get(discovery_url, timeout=10.0)
        resp.raise_for_status()
        config = resp.json()
    return config["jwks_uri"]
```

Call this in `lifespan()` and store the `JWKSClient` on `app.state` rather than
constructing it inline in `create_app()`.

---

## 9. Testing Strategy

### 9.1 Unit Tests — `tests/unit/test_pingfed_auth.py`

| Test Case | Description |
|-----------|-------------|
| `test_valid_token_passes` | Mock JWKS + valid JWT → request proceeds, `request.state.authenticated_user` is set. |
| `test_expired_token_returns_401` | Token with past `exp` → 401. |
| `test_wrong_audience_returns_401` | Token with mismatched `aud` → 401. |
| `test_wrong_issuer_returns_401` | Token with mismatched `iss` → 401. |
| `test_missing_auth_header_returns_401` | No `Authorization` header → 401. |
| `test_malformed_token_returns_401` | `Bearer garbage` → 401. |
| `test_public_paths_skip_auth` | `/health`, `/docs` proceed without token. |
| `test_jwks_cache_refresh` | Keys are cached and refreshed after TTL expires. |
| `test_auth_disabled_skips_middleware` | `PINGFED_AUTH_ENABLED=false` → no middleware registered. |
| `test_user_extracted_from_claims` | Decoded claims map to correct `user_id`, `user_name`, `email`. |

### 9.2 Integration Tests

- Full `/query` round-trip with a mock PingFed JWT.
- Verify `user_id` in session storage matches the token's `sub` claim.
- Verify LLM headers are auto-populated from token claims.

### 9.3 Test Fixtures

Create a `tests/conftest.py` fixture that generates test JWTs signed with a
test RSA key pair, and a mock JWKS endpoint serving the corresponding public key.
Use `pytest-httpx` or `respx` to mock the JWKS fetch.

---

## 10. Rollout Plan

| Phase | Environment | `PINGFED_AUTH_ENABLED` | Notes |
|-------|------------|------------------------|-------|
| 0 | local / test | `false` | No change — existing behaviour. |
| 1 | dev | `true` | Validate with dev PingFed instance. UI sends Bearer token. |
| 2 | stage | `true` | Full E2E validation with stage PingFed. |
| 3 | prod | `true` | Production rollout. Monitor 401 rates. |

---

## 11. Security Considerations

- **Always validate `exp`, `iss`, `aud`** — never skip these checks.
- **Use HTTPS** for JWKS endpoint fetches (enforce `verify=True`).
- **Cache JWKS keys** to avoid DDOS on PingFed; but support forced refresh when
  a `kid` is not found in the cache (key rotation scenario).
- **Do not log tokens** — log only validation outcomes and user IDs.
- **Rate-limit 401s** if abuse is detected (optional, via reverse proxy).
- **Token should not be stored** — validate on each request, discard after.

---

## 12. Claim Mapping Reference

Standard PingFed / OIDC claims expected in the JWT:

| JWT Claim | Maps To | Usage |
|-----------|---------|-------|
| `sub` | `user_id` | Primary user identifier, used as Redis session key prefix. |
| `preferred_username` | `user_name` | Display name / loginId. Falls back to `sub`. |
| `email` | `email` | Optional, for logging / audit. |
| `exp` | — | Token expiry (validated). |
| `iat` | — | Token issued-at (validated). |
| `iss` | — | Issuer (validated against `PINGFED_TOKEN_ISSUER`). |
| `aud` | — | Audience (validated against `PINGFED_AUDIENCE`). |
| `user_type` | `user_type` | Walmart-specific; maps to `wm_llm_gw.user_type`. |

---

## 13. File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/app/auth/__init__.py` | **Create** | Package init. |
| `src/app/auth/pingfed.py` | **Create** | JWKSClient, validate_token, extract_user_from_claims. |
| `src/app/auth/middleware.py` | **Create** | PingFedAuthMiddleware (ASGI). |
| `src/app/config.py` | **Edit** | Add `pingfed_*` settings fields. |
| `src/app/factory.py` | **Edit** | Conditionally register PingFedAuthMiddleware. |
| `src/app/routers/query.py` | **Edit** | Prefer `request.state.authenticated_user` in `_resolve_user_id()`. |
| `src/app/request_context.py` | **Edit** | Auto-fill `wm_llm_gw.user_name` from token claims. |
| `pyproject.toml` | **Edit** | Add `python-jose[cryptography]` dependency. |
| `tests/unit/test_pingfed_auth.py` | **Create** | Unit tests for auth module. |



======= MOre details =====
# PingFederate Token Validation Integration

> **Status: Planned — Not Yet Implemented**
> This document serves as a complete implementation guide for adding PingFed Bearer token validation to the super-agent. It is intended as context for AI coding assistants (Claude, Copilot, etc.) so the full picture does not need to be re-explained.

---

## Background

The super-agent is a FastAPI-based AI agent (Python) built on Google ADK, serving as a WCNP Health Agent for Walmart's SRE/Kubernetes platform. All API calls currently flow through `/query` and `/query_api` endpoints in `src/app/routers/query.py`.

Clients (e.g. `sre-ai.prod.walmart.com`) send requests with a **PingFederate Bearer token** in the `Authorization` header:

```
Authorization: Bearer <pingfed_access_token>
```

Currently, **no token validation is performed**. The goal is to add a middleware that validates this token on every API call before the request reaches the router.

---

## Walmart PingFed Introspection Endpoints

PingFederate token validation must use the **introspection endpoint** (recommended over public key validation because it also checks token revocation).

| Environment | Introspection URL |
|---|---|
| **DEV** | `https://pfeddev.wal-mart.com/as/introspect.oauth2` |
| **CERT / STAGE** | `https://pfedcert.wal-mart.com/as/introspect.oauth2` |
| **PROD** | `https://pfedprod.wal-mart.com/as/introspect.oauth2` |

### Introspection Request Spec

| Property | Value |
|---|---|
| Method | `POST` |
| Content-Type | `application/x-www-form-urlencoded` |
| Auth | Client credentials — `client_id` + `client_secret` (HTTP Basic Auth or form params) |
| Required body param | `token=<bearer_token_value>` |
| Optional body param | `token_type_hint=access_token` |

### Introspection Response

- ✅ **Valid token**: `{ "active": true, "userId": "...", "win": "...", ... }`
- ❌ **Invalid/expired/revoked token**: `{ "active": false }`

📖 **Source:** [Getting Started with OAuth 2.0 / OIDC 1.0 — DX Platform](https://dx.walmart.com/pingfederate/documentation/dx/Getting-Started-with-OAuth-2-0---OIDC-1-0-D0000001332)
📖 **Source:** [Access Control Methods — DX Platform](https://dx.walmart.com/papigateway/documentation/dx/Access-control-methods-D0000001735)

---

## Codebase Context

### Project Structure (relevant files)

```
super-agent/
└── src/
    ├── main.py                          # Uvicorn entry point
    ├── agent/agent.py                   # ADK root agent definition
    └── app/
        ├── config.py                    # ⭐ All settings via pydantic-settings + env vars
        ├── factory.py                   # ⭐ App factory — middleware + routers registered here
        ├── request_context.py           # contextvars for LLM header propagation
        ├── routers/
        │   ├── query.py                 # POST /query and /query_api — main endpoints
        │   ├── health.py                # GET /health — must be whitelisted
        │   ├── a2a.py                   # A2A protocol routes
        │   ├── sessions.py              # Session management
        │   ├── debug.py                 # Debug routes
        │   └── mcp_validate.py          # MCP server validation
        └── store/
            └── redis_session_service.py # Redis-backed ADK session store
```

### Existing Middleware Pattern to Follow

`factory.py` already contains `LLMHeaderMiddleware` — a **pure ASGI middleware** (not `BaseHTTPMiddleware`). The PingFed middleware must follow this exact same pattern for these reasons:
- Stays alive for the full request lifecycle including streaming responses
- `BaseHTTPMiddleware` has a known bug where its `finally` block clears context before streaming completes

```python
# Example structure of LLMHeaderMiddleware in factory.py (lines 234–258)
class LLMHeaderMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            set_llm_headers(extract_llm_headers(request))
            try:
                await self.app(scope, receive, send)
            finally:
                clear_llm_headers()
        else:
            await self.app(scope, receive, send)
```

### Existing Config Pattern

`config.py` uses `pydantic-settings`. All secrets are loaded from:
- Local `.env*` files
- `/secrets/.env*` (Akeyless-mounted secrets in WCNP)

Example of how existing secrets are defined:
```python
element_gateway_api_key: str = ""
redis_password: str = ""
```

The `agent_env` field already drives environment branching (`dev`, `stage`, `prod`, `local`).

### HTTP Client

`httpx.AsyncClient` is already created in `lifespan()` and stored at `app.state.http_client`. This can be reused or a dedicated client created for PingFed calls.

---

## Implementation Plan

### Step 1 — Prerequisites (Before Writing Code)

- [ ] Register the super-agent as an OAuth client with the Walmart PingFed team
- [ ] Obtain `client_id` and `client_secret` for DEV, STAGE, and PROD
- [ ] Store credentials in Akeyless secrets (same secret store as `redis_password`)
- [ ] Ensure `/secrets/.env*` includes the new fields at deploy time

### Step 2 — Add Config Fields in `src/app/config.py`

Add the following fields to the `Settings` class:

```python
# ── PingFed Token Validation ───────────────────────────────────────────────
pingfed_client_id: str = ""
pingfed_client_secret: str = ""
# If left empty, the middleware will auto-select based on agent_env
pingfed_introspection_url: str = ""
```

Add a computed property to auto-select the correct URL based on `agent_env`:

```python
@computed_field
@property
def pingfed_url(self) -> str:
    if self.pingfed_introspection_url:
        return self.pingfed_introspection_url
    return {
        "prod":  "https://pfedprod.wal-mart.com/as/introspect.oauth2",
        "stage": "https://pfedcert.wal-mart.com/as/introspect.oauth2",
        "cert":  "https://pfedcert.wal-mart.com/as/introspect.oauth2",
    }.get(self.agent_env, "https://pfeddev.wal-mart.com/as/introspect.oauth2")
```

### Step 3 — Create `PingFedAuthMiddleware` in `src/app/factory.py`

New class to add alongside `LLMHeaderMiddleware`:

**Behaviour:**
1. Skip non-HTTP scopes (WebSocket, lifespan) — pass through
2. Skip whitelisted public paths: `/health`, `/docs`, `/redoc`, `/openapi.json`
3. Extract `Authorization: Bearer <token>` header — return `401` if missing
4. `POST` to PingFed introspection URL with `token=<value>` + client credentials
5. Check `response["active"] == True` — return `401` if false
6. On PingFed unreachable / timeout — return `503` (fail closed — safer for a prod SRE tool)
7. Pass through to next middleware if token is valid

**Whitelisted paths (no auth required):**
```python
_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}
```

### Step 4 — Register Middleware in `create_app()` in `src/app/factory.py`

Add after `LLMHeaderMiddleware` registration:

```python
application.add_middleware(PingFedAuthMiddleware)
```

**Middleware execution order** (last registered = outermost):
```
Request → CORSMiddleware → LLMHeaderMiddleware → PingFedAuthMiddleware → Router
```

This ensures PingFed validation fires **before** any router or business logic.

### Step 5 — Unit Tests

Add tests in `tests/unit/` following the existing pattern:
- Test: valid token → request passes through
- Test: missing `Authorization` header → `401`
- Test: `active: false` from PingFed → `401`
- Test: PingFed unreachable → `503`
- Test: `/health` path → skips validation entirely
- Test: `/docs` path → skips validation entirely

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Middleware type | Pure ASGI (not `BaseHTTPMiddleware`) | Matches existing pattern; works with streaming |
| Fail behavior when PingFed is down | Fail closed → `503` | SRE tool in prod — security over availability |
| URL selection | Auto from `agent_env` + override via env var | Consistent with existing config patterns |
| HTTP client | Reuse `app.state.http_client` or dedicated | TBD — dedicated client gives better timeout control |
| Token type hint | `access_token` | All client tokens are access tokens |

---

## Akeyless / Secrets Setup

When ready to deploy, store the following in the Akeyless secret used by super-agent (same one that holds `REDIS_PASSWORD`, `ELEMENT_GATEWAY_API_KEY`, etc.):

```
PINGFED_CLIENT_ID=<your-client-id>
PINGFED_CLIENT_SECRET=<your-client-secret>
```

These will be auto-loaded by `config.py`'s glob-based `.env*` discovery from `/secrets/`.

---

## References

- [PingFed OAuth 2.0 / OIDC Getting Started — DX Platform](https://dx.walmart.com/pingfederate/documentation/dx/Getting-Started-with-OAuth-2-0---OIDC-1-0-D0000001332)
- [Access Control Methods — DX Platform](https://dx.walmart.com/papigateway/documentation/dx/Access-control-methods-D0000001735)
- [Can I validate the pingfed token using the public key — Wibey Loop](https://wibey.walmart.com/loop/reply/view/Can-I-validate-the-pingfed-token-using-the-public-key-SOR30877)

