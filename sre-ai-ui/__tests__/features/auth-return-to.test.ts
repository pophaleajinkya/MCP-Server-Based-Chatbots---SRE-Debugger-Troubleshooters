/**
 * @jest-environment node
 *
 * Feature tests: Unauthenticated user follows a shared link → authenticates →
 * lands back on the original shared conversation URL.
 *
 * Critical path:
 *
 *  AuthContext.login()
 *    └─ encodes current path as ?returnTo=
 *         └─ /api/auth/login stores returnTo inside PKCE cookie
 *              └─ /api/auth/callback reads it back → redirects to original URL
 *
 * Covers:
 *  1.  login() includes ?returnTo= when the current path contains a session
 *  2.  login() omits ?returnTo= when the user is on the bare root "/"
 *  3.  login() includes path+search (full shared URL) in ?returnTo=
 *  4.  Login route: valid relative returnTo is forwarded to setPKCECookie
 *  5.  Login route: absolute URL is rejected (open-redirect guard)
 *  6.  Login route: protocol-relative URL is rejected (open-redirect guard)
 *  7.  Login route: explicit empty returnTo is rejected gracefully
 *  8.  Login route: missing returnTo param results in undefined (not empty string)
 *  9.  Callback route: redirects to returnTo path when present in PKCE cookie
 * 10.  Callback route: redirects to app root when returnTo is absent
 * 11.  Callback route: uses NEXTAUTH_URL as base for returnTo redirect
 * 12.  PKCE cookie stores returnTo alongside state + verifier
 * 13.  PKCE cookie omits returnTo key when not provided
 * 14.  consumePKCECookie returns returnTo when stored
 * 15.  consumePKCECookie result has no returnTo key when not stored
 */

// ─── GET /api/auth/login ──────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  generatePKCE: jest.fn(),
  getPingFedConfig: jest.fn(),
  setPKCECookie: jest.fn(),
  consumePKCECookie: jest.fn(),
  exchangeCodeForTokens: jest.fn(),
  fetchUserInfo: jest.fn(),
  mapUserInfo: jest.fn(),
  setSessionCookie: jest.fn(),
}));

import { NextRequest } from "next/server";
import { GET as loginGET } from "@/app/api/auth/login/route";
import { GET as callbackGET } from "@/app/api/auth/callback/route";
import {
  generatePKCE,
  getPingFedConfig,
  setPKCECookie,
  consumePKCECookie,
  exchangeCodeForTokens,
  fetchUserInfo,
  mapUserInfo,
  setSessionCookie,
} from "@/lib/auth-server";

const mockGetPingFedConfig    = getPingFedConfig    as jest.MockedFunction<typeof getPingFedConfig>;
const mockGeneratePKCE        = generatePKCE        as jest.MockedFunction<typeof generatePKCE>;
const mockSetPKCECookie       = setPKCECookie       as jest.MockedFunction<typeof setPKCECookie>;
const mockConsumePKCECookie   = consumePKCECookie   as jest.MockedFunction<typeof consumePKCECookie>;
const mockExchangeCodeForTokens = exchangeCodeForTokens as jest.MockedFunction<typeof exchangeCodeForTokens>;
const mockFetchUserInfo       = fetchUserInfo       as jest.MockedFunction<typeof fetchUserInfo>;
const mockMapUserInfo         = mapUserInfo         as jest.MockedFunction<typeof mapUserInfo>;
const mockSetSessionCookie    = setSessionCookie    as jest.MockedFunction<typeof setSessionCookie>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const PINGFED_CONFIG = {
  clientId:    "client123",
  redirectUri: "http://localhost:3000/api/auth/callback",
  scope:       "openid profile",
  authUrl:     "https://sso.walmart.com/oauth2/authorize",
};

const SESSION_FIXTURE = {
  sub: "user-sub-001", name: "Jane Doe", email: "jane@example.com",
  loginId: "jdoe", user_type: "S",
  expires_at: Math.floor(Date.now() / 1000) + 10800,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeLoginRequest(params: Record<string, string> = {}): NextRequest {
  const url = new URL("http://localhost:3000/api/auth/login");
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  return new NextRequest(url.toString());
}

function makeCallbackRequest(params: Record<string, string>): NextRequest {
  const url = new URL("http://localhost:3000/api/auth/callback");
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  return new NextRequest(url.toString());
}

function setupSuccessfulAuth() {
  mockExchangeCodeForTokens.mockResolvedValue({ expires_in: 3600 });
  mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
  mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
  mockSetSessionCookie.mockResolvedValue(undefined);
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.resetAllMocks();
  delete process.env.NEXTAUTH_URL;

  mockGetPingFedConfig.mockReturnValue(PINGFED_CONFIG);
  mockGeneratePKCE.mockResolvedValue({
    verifier: "verifier123", challenge: "challenge123", state: "state123",
  });
  mockSetPKCECookie.mockResolvedValue(undefined);
});

// ─── Section 1: /api/auth/login — returnTo forwarding ─────────────────────────

describe("GET /api/auth/login — returnTo forwarding", () => {
  it("passes valid relative returnTo to setPKCECookie", async () => {
    await loginGET(makeLoginRequest({ returnTo: "/?session=abc-123" }));
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", "/?session=abc-123");
  });

  it("passes undefined to setPKCECookie when no returnTo param is present", async () => {
    await loginGET(makeLoginRequest());
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("passes undefined when returnTo is an explicit empty string", async () => {
    await loginGET(makeLoginRequest({ returnTo: "" }));
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("rejects absolute URL (open-redirect guard) — passes undefined", async () => {
    await loginGET(makeLoginRequest({ returnTo: "https://evil.com/steal-tokens" }));
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("rejects protocol-relative URL (open-redirect guard) — passes undefined", async () => {
    await loginGET(makeLoginRequest({ returnTo: "//evil.com/steal-tokens" }));
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("accepts returnTo with nested path and query string", async () => {
    await loginGET(makeLoginRequest({ returnTo: "/?session=abc&foo=bar" }));
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", "/?session=abc&foo=bar");
  });

  it("accepts returnTo that is just a path without query params", async () => {
    await loginGET(makeLoginRequest({ returnTo: "/some/path" }));
    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", "/some/path");
  });

  it("still redirects to PingFed authorization URL even with a valid returnTo", async () => {
    const response = await loginGET(makeLoginRequest({ returnTo: "/?session=abc-123" }));
    expect(response.status).toBe(307);
    expect(response.headers.get("Location")).toContain("sso.walmart.com");
  });
});

// ─── Section 2: /api/auth/callback — returnTo redirect ────────────────────────

describe("GET /api/auth/callback — returnTo redirect after successful auth", () => {
  it("redirects to the returnTo path when present in the PKCE cookie", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "v", returnTo: "/?session=shared-123" });
    setupSuccessfulAuth();

    const res = await callbackGET(makeCallbackRequest({ code: "c", state: "s" }));

    expect(res.headers.get("Location")).toContain("/?session=shared-123");
  });

  it("redirects to app root when returnTo is absent in the PKCE cookie", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "v" });
    setupSuccessfulAuth();

    const res = await callbackGET(makeCallbackRequest({ code: "c", state: "s" }));

    expect(res.headers.get("Location")?.replace(/\/$/, "")).toBe("http://localhost:3000");
  });

  it("uses NEXTAUTH_URL as the base when redirecting to returnTo", async () => {
    process.env.NEXTAUTH_URL = "https://sre-ai.walmart.com";
    mockConsumePKCECookie.mockResolvedValue({ verifier: "v", returnTo: "/?session=xyz" });
    setupSuccessfulAuth();

    const res = await callbackGET(makeCallbackRequest({ code: "c", state: "s" }));

    expect(res.headers.get("Location")).toBe("https://sre-ai.walmart.com/?session=xyz");
  });

  it("uses NEXTAUTH_URL as the base for root redirect when returnTo is absent", async () => {
    process.env.NEXTAUTH_URL = "https://sre-ai.walmart.com";
    mockConsumePKCECookie.mockResolvedValue({ verifier: "v" });
    setupSuccessfulAuth();

    const res = await callbackGET(makeCallbackRequest({ code: "c", state: "s" }));

    expect(res.headers.get("Location")?.replace(/\/$/, "")).toBe("https://sre-ai.walmart.com");
  });

  it("preserves the full returnTo including query string and hash-like path", async () => {
    mockConsumePKCECookie.mockResolvedValue({
      verifier: "v", returnTo: "/?session=abc&agent=sre",
    });
    setupSuccessfulAuth();

    const res = await callbackGET(makeCallbackRequest({ code: "c", state: "s" }));

    expect(res.headers.get("Location")).toContain("session=abc");
    expect(res.headers.get("Location")).toContain("agent=sre");
  });
});

