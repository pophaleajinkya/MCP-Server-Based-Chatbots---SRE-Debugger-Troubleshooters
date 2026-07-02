/**
 * @jest-environment node
 *
 * Integration tests for auth API routes.
 * Tests handler functions directly without spinning up a real HTTP server.
 *
 * Uses the `node` environment so that the Web Fetch API globals (Request,
 * Response, Headers) are available — these are provided by the Next.js runtime
 * but are not present in jest-environment-jsdom.
 */

import { POST } from "@/app/api/auth/logout/route";
import { GET } from "@/app/api/auth/user/route";
import type { AuthSession } from "@/lib/auth-server";

// ─── Mock auth-server ────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  clearSessionCookie: jest.fn(),
  getPingFedConfig: jest.fn(),
  getSessionCookie: jest.fn(),
  isAdminUser: jest.fn().mockReturnValue(false),
  SESSION_COOKIE: "sre_ai_session",
}));

// Pull typed references after mock is registered
import {
  clearSessionCookie,
  getPingFedConfig,
  getSessionCookie,
} from "@/lib/auth-server";

const mockClearSessionCookie = clearSessionCookie as jest.MockedFunction<
  typeof clearSessionCookie
>;
const mockGetPingFedConfig = getPingFedConfig as jest.MockedFunction<
  typeof getPingFedConfig
>;
const mockGetSessionCookie = getSessionCookie as jest.MockedFunction<
  typeof getSessionCookie
>;

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Full PingFed config fixture returned by a happy-path getPingFedConfig mock. */
const PINGFED_CONFIG = {
  clientId: process.env.PINGFED_CLIENT_ID ?? "dummy",
  clientSecret: process.env.PINGFED_CLIENT_SECRET ?? "dummy",
  redirectUri: process.env.PINGFED_REDIRECT_URI ?? "http://localhost:3000/api/auth/callback",
  authUrl: process.env.PINGFED_AUTH_URL ?? "http://localhost/as/authorization.oauth2",
  tokenUrl: process.env.PINGFED_TOKEN_URL ?? "http://localhost/as/token.oauth2",
  userInfoUrl: process.env.PINGFED_USERINFO_URL ?? "http://localhost/idp/userinfo.openid",
  logoutUrl: process.env.PINGFED_LOGOUT_URL ?? "http://localhost/as/logout",
  scope: process.env.PINGFED_SCOPE ?? "openid profile email",
};

/** A realistic AuthSession fixture for session cookie tests. */
const SESSION_FIXTURE: AuthSession = {
  sub: "user-sub-001",
  name: "Jane Doe",
  email: "jane.doe@example.com",
  loginId: "jdoe",
  win_nbr: "W1234567",
  user_type: "S",
  isAdmin: false,
  expires_at: Math.floor(Date.now() / 1000) + 10800,
};

/**
 * Build a minimal NextRequest-compatible mock.
 * The logout route reads req?.nextUrl?.origin as a fallback when NEXTAUTH_URL
 * is not set, so every call that omits NEXTAUTH_URL must supply this.
 */
function makeReq(origin = "http://localhost:3000") {
  return { nextUrl: { origin } } as any;
}

// ─── /api/auth/logout — POST ──────────────────────────────────────────────────
//
// KEY BEHAVIOUR NOTES (current implementation):
//
// 1. The route sets the session cookie directly on the NextResponse object via
//    res.cookies.set(..., "", { maxAge: 0 }) — it does NOT call clearSessionCookie().
//    Tests that previously asserted clearSessionCookie() was called are updated
//    to verify the cookie-clearing behaviour on the response instead.
//
// 2. In the test environment NODE_ENV === "test", so isLocalDev === true.
//    The route short-circuits to `${appBase}/login` without calling getPingFedConfig().
//    Tests that require PingFed SLO behaviour must set NODE_ENV to a non-dev/test
//    value (e.g. "production") and restore it afterward.
//
// 3. The route parameter `req` is required: it reads req?.nextUrl?.origin as a
//    base-URL fallback when NEXTAUTH_URL is not set. Always pass makeReq() or
//    set NEXTAUTH_URL.

describe("POST /api/auth/logout", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    delete process.env.NEXTAUTH_URL;
    delete process.env.PINGFED_LOGOUT_URL;
  });

  it("sets the session cookie to empty with maxAge=0 on every call (clears the cookie)", async () => {
    process.env.NEXTAUTH_URL = "http://localhost:3000";
    const response = await POST(makeReq());
    // The response must instruct the browser to delete the session cookie
    const cookieHeader = response.headers.get("set-cookie") ?? "";
    expect(cookieHeader).toContain("sre_ai_session");
    expect(cookieHeader).toContain("Max-Age=0");
  });

  it("returns JSON with a logoutUrl field", async () => {
    process.env.NEXTAUTH_URL = "http://localhost:3000";

    const response = await POST(makeReq());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toHaveProperty("logoutUrl");
    expect(typeof body.logoutUrl).toBe("string");
  });

  it("returns /login fallback URL in test/dev environment (isLocalDev=true)", async () => {
    // NODE_ENV is "test" here, so the route always uses the /login fallback
    process.env.NEXTAUTH_URL = "http://localhost:3000";

    const response = await POST(makeReq("http://localhost:3000"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.logoutUrl).toBe("http://localhost:3000/login");
  });

  it("appends /login to the appBase derived from NEXTAUTH_URL", async () => {
    process.env.NEXTAUTH_URL = "http://localhost:3000";

    const response = await POST(makeReq());
    const body = await response.json();

    expect(body.logoutUrl).toContain("/login");
  });

  it("returns the /login fallback URL when NEXTAUTH_URL is set", async () => {
    process.env.NEXTAUTH_URL = "http://localhost:3000";

    const response = await POST(makeReq());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.logoutUrl).toBe("http://localhost:3000/login");
  });

  it("uses req.nextUrl.origin as the base when NEXTAUTH_URL is not set", async () => {
    // NEXTAUTH_URL deliberately not set
    const mockReq = { nextUrl: { origin: "https://mock-origin.com" } } as any;

    const response = await POST(mockReq);
    const body = await response.json();

    expect(body.logoutUrl).toBe("https://mock-origin.com/login");
  });

  it("sets Max-Age=0 on the session cookie even when origin comes from req", async () => {
    // NEXTAUTH_URL not set — falls back to req.nextUrl.origin
    const response = await POST(makeReq("https://mock-origin.com"));
    const cookieHeader = response.headers.get("set-cookie") ?? "";
    expect(cookieHeader).toContain("sre_ai_session");
    expect(cookieHeader).toContain("Max-Age=0");
  });

  it("builds logoutUrl using NEXTAUTH_URL when it is set", async () => {
    process.env.NEXTAUTH_URL = "https://my-app.example.com";

    const response = await POST(makeReq());
    const body = await response.json();

    expect(body.logoutUrl).toContain("my-app.example.com");
  });

  it("returns /login fallback at the configured app base when NEXTAUTH_URL is a prod URL", async () => {
    process.env.NEXTAUTH_URL = "https://prod.example.com";

    const response = await POST(makeReq());
    const body = await response.json();

    expect(body.logoutUrl).toBe("https://prod.example.com/login");
  });
});

// ─── /api/auth/user — GET ─────────────────────────────────────────────────────

describe("GET /api/auth/user", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  it("returns 401 when there is no session cookie", async () => {
    mockGetSessionCookie.mockReturnValue(null);

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "Not authenticated" });
  });

  it("returns 200 with user data when a session cookie exists", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const response = await GET();

    expect(response.status).toBe(200);
  });

  it("returns the correct user fields when a session exists", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const response = await GET();
    const body = await response.json();

    expect(body.sub).toBe(SESSION_FIXTURE.sub);
    expect(body.name).toBe(SESSION_FIXTURE.name);
    expect(body.email).toBe(SESSION_FIXTURE.email);
    expect(body.loginId).toBe(SESSION_FIXTURE.loginId);
    expect(body.user_type).toBe(SESSION_FIXTURE.user_type);
  });

  it("does NOT expose access_token in the response body", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const response = await GET();
    const body = await response.json();

    expect(body).not.toHaveProperty("access_token");
    expect(body.access_token).toBeUndefined();
  });

  it("includes win_nbr in the response when present in session", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const response = await GET();
    const body = await response.json();

    expect(body.win_nbr).toBe(SESSION_FIXTURE.win_nbr);
  });

  it("omits win_nbr from the response when not present in session", async () => {
    const sessionWithoutWinNbr: AuthSession = {
      ...SESSION_FIXTURE,
      win_nbr: undefined,
    };
    mockGetSessionCookie.mockReturnValue(sessionWithoutWinNbr);

    const response = await GET();
    const body = await response.json();

    expect(body.win_nbr).toBeUndefined();
  });
});
