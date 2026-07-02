/**
 * @jest-environment node
 *
 * Tests for src/middleware.ts
 *
 * The middleware:
 *  - Allows public paths through unconditionally
 *  - Allows Next.js internals (_next/*) through unconditionally
 *  - Allows paths that contain a "." (static files) through unconditionally
 *  - Redirects unauthenticated requests (no sre_ai_session cookie) to /login
 *  - Passes authenticated requests through and injects identity headers
 *  - Redirects + deletes the cookie when the session cookie contains corrupt JSON
 */

import { NextRequest, NextResponse } from "next/server";
import { middleware } from "@/middleware";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal NextRequest for the given path.
 * If cookieValue is supplied it is stored under the SESSION_COOKIE name
 * ("sre_ai_session") that the middleware reads.
 */
function makeRequest(path: string, cookieValue?: string): NextRequest {
  const url = `http://localhost:3000${path}`;
  const req = new NextRequest(url);
  if (cookieValue !== undefined) {
    req.cookies.set("sre_ai_session", cookieValue);
  }
  return req;
}

/**
 * Returns true when the response is a redirect (307 Temporary Redirect or a
 * Location header is present, which Next.js uses for NextResponse.redirect).
 */
function isRedirect(response: NextResponse): boolean {
  return (
    response.status === 307 ||
    response.status === 308 ||
    response.headers.get("location") !== null
  );
}

// ---------------------------------------------------------------------------
// A valid session payload that the middleware can JSON.parse successfully.
// ---------------------------------------------------------------------------
const VALID_SESSION = JSON.stringify({
  sub: "uid-001",
  name: "Jane Doe",
  email: "jane@example.com",
  loginId: "jdoe",
  user_type: "S",
});

// ---------------------------------------------------------------------------
// Public paths — must pass through without a cookie
// ---------------------------------------------------------------------------

describe("public paths — pass through without authentication", () => {
  test("GET /login passes through", () => {
    const res = middleware(makeRequest("/login"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /api/auth/login passes through", () => {
    const res = middleware(makeRequest("/api/auth/login"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /api/auth/callback passes through", () => {
    const res = middleware(makeRequest("/api/auth/callback"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /api/auth/user passes through", () => {
    const res = middleware(makeRequest("/api/auth/user"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /api/auth/logout passes through", () => {
    const res = middleware(makeRequest("/api/auth/logout"));
    expect(isRedirect(res)).toBe(false);
  });

  test("nested path under /api/auth/login passes through", () => {
    // The middleware uses startsWith(p + "/") so sub-paths are also public.
    const res = middleware(makeRequest("/api/auth/login/extra"));
    expect(isRedirect(res)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Next.js internals — always allowed
// ---------------------------------------------------------------------------

describe("Next.js internals — pass through without authentication", () => {
  test("GET /_next/static/chunks/main.js passes through", () => {
    const res = middleware(makeRequest("/_next/static/chunks/main.js"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /_next/image?url=... passes through", () => {
    const res = middleware(makeRequest("/_next/image?url=foo.png&w=64&q=75"));
    expect(isRedirect(res)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Paths that contain a dot — treated as static assets and allowed through
// ---------------------------------------------------------------------------

describe("static asset paths (contain a dot) — pass through without authentication", () => {
  test("GET /favicon.svg passes through", () => {
    const res = middleware(makeRequest("/favicon.svg"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /logo.png passes through", () => {
    const res = middleware(makeRequest("/logo.png"));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /assets/styles.css passes through", () => {
    const res = middleware(makeRequest("/assets/styles.css"));
    expect(isRedirect(res)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Unauthenticated requests — must redirect to /login
// ---------------------------------------------------------------------------

describe("unauthenticated page requests — redirect to /login", () => {
  test("GET / with no cookie redirects to /login", () => {
    const res = middleware(makeRequest("/"));
    expect(isRedirect(res)).toBe(true);
    const location = res.headers.get("location");
    expect(location).toContain("/login");
  });

  test("GET /dashboard with no cookie redirects to /login", () => {
    const res = middleware(makeRequest("/dashboard"));
    expect(isRedirect(res)).toBe(true);
    const location = res.headers.get("location");
    expect(location).toContain("/login");
  });

  test("redirect preserves the origin host in the Location URL", () => {
    const res = middleware(makeRequest("/protected"));
    const location = res.headers.get("location");
    expect(location).toMatch(/^http:\/\/localhost:3000\/login/);
  });
});

// ---------------------------------------------------------------------------
// Unauthenticated API requests — must return JSON 401 (not HTML redirect)
// ---------------------------------------------------------------------------

describe("unauthenticated API requests — return JSON 401", () => {
  test("GET /api/chat with no cookie returns 401 JSON", async () => {
    const res = middleware(makeRequest("/api/chat"));
    expect(isRedirect(res)).toBe(false);
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body).toEqual({ error: "Not authenticated" });
  });

  test("GET /api/agents with no cookie returns 401 JSON", async () => {
    const res = middleware(makeRequest("/api/agents"));
    expect(isRedirect(res)).toBe(false);
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body).toEqual({ error: "Not authenticated" });
  });

  test("GET /api/sessions with no cookie returns 401 JSON", async () => {
    const res = middleware(makeRequest("/api/sessions"));
    expect(isRedirect(res)).toBe(false);
    expect(res.status).toBe(401);
  });

  test("content-type is application/json for unauthenticated API routes", async () => {
    const res = middleware(makeRequest("/api/chat"));
    expect(res.headers.get("content-type")).toMatch(/application\/json/);
  });
});

// ---------------------------------------------------------------------------
// Authenticated requests — pass through
// ---------------------------------------------------------------------------

describe("authenticated requests — pass through", () => {
  test("GET / with a valid JSON session cookie is NOT redirected", () => {
    const res = middleware(makeRequest("/", VALID_SESSION));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /api/chat with a valid JSON session cookie is NOT redirected", () => {
    const res = middleware(makeRequest("/api/chat", VALID_SESSION));
    expect(isRedirect(res)).toBe(false);
  });

  test("GET /dashboard with a valid JSON session cookie is NOT redirected", () => {
    const res = middleware(makeRequest("/dashboard", VALID_SESSION));
    expect(isRedirect(res)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Identity headers — set from parsed cookie payload
// ---------------------------------------------------------------------------

describe("identity headers — injected when authenticated", () => {
  let res: NextResponse;

  beforeEach(() => {
    res = middleware(makeRequest("/", VALID_SESSION));
  });

  test("x-user-login-id header is present", () => {
    expect(res.headers.get("x-user-login-id")).not.toBeNull();
  });

  test("x-user-login-id header matches loginId from session", () => {
    expect(res.headers.get("x-user-login-id")).toBe("jdoe");
  });

  test("x-user-type header is present", () => {
    expect(res.headers.get("x-user-type")).not.toBeNull();
  });

  test("x-user-type header matches user_type from session", () => {
    expect(res.headers.get("x-user-type")).toBe("S");
  });

  test("x-user-name header is present", () => {
    expect(res.headers.get("x-user-name")).not.toBeNull();
  });

  test("x-user-name header matches name from session", () => {
    expect(res.headers.get("x-user-name")).toBe("Jane Doe");
  });

  test("headers are empty strings when the fields are absent from the session", () => {
    const minimal = JSON.stringify({ sub: "x" }); // no loginId / user_type / name
    const r = middleware(makeRequest("/", minimal));
    expect(r.headers.get("x-user-login-id")).toBe("");
    expect(r.headers.get("x-user-type")).toBe("");
    expect(r.headers.get("x-user-name")).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Corrupt cookie — redirect to /login and delete the cookie
// ---------------------------------------------------------------------------

describe("corrupt session cookie — redirect and delete cookie", () => {
  test("redirects to /login when cookie is not valid JSON (page route)", () => {
    const res = middleware(makeRequest("/", "NOT_VALID_JSON{{{"));
    expect(isRedirect(res)).toBe(true);
    const location = res.headers.get("location");
    expect(location).toContain("/login");
  });

  test("returns 401 JSON when cookie is not valid JSON (API route)", async () => {
    const res = middleware(makeRequest("/api/agents", "NOT_VALID_JSON{{{"));
    expect(isRedirect(res)).toBe(false);
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body).toEqual({ error: "Invalid session" });
  });

  test("the sre_ai_session cookie is deleted (Set-Cookie header clears it)", () => {
    const res = middleware(makeRequest("/", "broken"));
    // Next.js deletes a cookie by setting it with an expired/empty value via Set-Cookie.
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toMatch(/sre_ai_session/);
  });

  test("redirects to /login when cookie is empty string", () => {
    // An empty string parses as a falsy session value, so the middleware
    // redirects before even attempting JSON.parse.
    const req = makeRequest("/");
    req.cookies.set("sre_ai_session", "");
    const res = middleware(req);
    expect(isRedirect(res)).toBe(true);
    const location = res.headers.get("location");
    expect(location).toContain("/login");
  });

  test("redirects to /login when cookie contains a bare number", () => {
    // A bare number is valid JSON (parses to a primitive), so the middleware
    // will parse it but fail when accessing properties — falls through to
    // redirect with cookie deletion because `parsed.loginId` etc. are undefined,
    // not because JSON.parse throws.  We only assert the redirect here.
    const res = middleware(makeRequest("/", "null"));
    // null is valid JSON: parsed = null, so reading parsed.loginId throws → corrupt path
    expect(isRedirect(res)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// OAuth callback redirect — lines 38-42
// ---------------------------------------------------------------------------

describe("OAuth callback redirect — /?code=...&state=... → /api/auth/callback", () => {
  test("redirects to /api/auth/callback preserving query params", () => {
    const req = new NextRequest("http://localhost:3000/?code=abc123&state=xyz789");
    const res = middleware(req);
    expect(isRedirect(res)).toBe(true);
    const location = res.headers.get("location")!;
    expect(location).toContain("/api/auth/callback");
    expect(location).toContain("code=abc123");
    expect(location).toContain("state=xyz789");
  });

  test("does NOT redirect when only code param is present (no state)", () => {
    const req = new NextRequest("http://localhost:3000/?code=abc123");
    const res = middleware(req);
    // Without both code AND state, it should not hit the callback redirect
    // Instead it redirects to /login (no cookie)
    const location = res.headers.get("location") ?? "";
    expect(location).not.toContain("/api/auth/callback");
  });

  test("does NOT redirect when only state param is present (no code)", () => {
    const req = new NextRequest("http://localhost:3000/?state=xyz789");
    const res = middleware(req);
    const location = res.headers.get("location") ?? "";
    expect(location).not.toContain("/api/auth/callback");
  });
});

// ---------------------------------------------------------------------------
// Expired token — lines 59-65
// ---------------------------------------------------------------------------

describe("expired session token — redirect to /login and delete cookie", () => {
  const expired = JSON.stringify({
    sub: "uid-001",
    name: "Jane Doe",
    loginId: "jdoe",
    user_type: "S",
    expires_at: Math.floor(Date.now() / 1000) - 3600, // expired 1 hour ago
  });

  test("redirects to /login when access token has expired (page route)", () => {
    const res = middleware(makeRequest("/", expired));
    expect(isRedirect(res)).toBe(true);
    const location = res.headers.get("location");
    expect(location).toContain("/login");
  });

  test("returns 401 JSON when access token has expired (API route)", async () => {
    const res = middleware(makeRequest("/api/agents", expired));
    expect(isRedirect(res)).toBe(false);
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body).toEqual({ error: "Session expired" });
  });

  test("deletes the session cookie when token is expired", () => {
    const expiredMinimal = JSON.stringify({
      sub: "uid-001",
      loginId: "jdoe",
      expires_at: Math.floor(Date.now() / 1000) - 60,
    });
    const res = middleware(makeRequest("/", expiredMinimal));
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toMatch(/sre_ai_session/);
  });

  test("does NOT redirect when token has not expired yet", () => {
    const valid = JSON.stringify({
      sub: "uid-001",
      name: "Jane Doe",
      loginId: "jdoe",
      user_type: "S",
      expires_at: Math.floor(Date.now() / 1000) + 3600, // expires in 1 hour
    });
    const res = middleware(makeRequest("/", valid));
    expect(isRedirect(res)).toBe(false);
  });
});
