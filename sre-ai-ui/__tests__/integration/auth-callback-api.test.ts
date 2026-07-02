/**
 * @jest-environment node
 *
 * Integration tests for the auth callback API route.
 * Tests GET /api/auth/callback handler function directly.
 *
 * Uses the `node` environment so that the Web Fetch API globals (Request,
 * Response, Headers) are available — these are provided by the Next.js runtime
 * but are not present in jest-environment-jsdom.
 */

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  consumePKCECookie: jest.fn(),
  exchangeCodeForTokens: jest.fn(),
  fetchUserInfo: jest.fn(),
  mapUserInfo: jest.fn(),
  setSessionCookie: jest.fn(),
}));

import { GET } from "@/app/api/auth/callback/route";
import {
  consumePKCECookie,
  exchangeCodeForTokens,
  fetchUserInfo,
  mapUserInfo,
  setSessionCookie,
} from "@/lib/auth-server";

const mockConsumePKCECookie = consumePKCECookie as jest.MockedFunction<typeof consumePKCECookie>;
const mockExchangeCodeForTokens = exchangeCodeForTokens as jest.MockedFunction<typeof exchangeCodeForTokens>;
const mockFetchUserInfo = fetchUserInfo as jest.MockedFunction<typeof fetchUserInfo>;
const mockMapUserInfo = mapUserInfo as jest.MockedFunction<typeof mapUserInfo>;
const mockSetSessionCookie = setSessionCookie as jest.MockedFunction<typeof setSessionCookie>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const SESSION_FIXTURE = {
  sub: "user-sub-001",
  name: "Jane Doe",
  email: "jane.doe@example.com",
  loginId: "jdoe",
  win_nbr: "W1234567",
  user_type: "S",
  expires_at: Math.floor(Date.now() / 1000) + 10800,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeRequest(params: Record<string, string>) {
  const url = new URL("http://localhost:3000/api/auth/callback");
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  return { url: url.toString(), nextUrl: new URL(url.toString()) } as unknown as import("next/server").NextRequest;
}

// ─── GET /api/auth/callback ───────────────────────────────────────────────────

describe("GET /api/auth/callback", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    delete process.env.NEXTAUTH_URL;
  });

  // ── PingFed error param ──────────────────────────────────────────────────────

  it("redirects to /login?error=... when PingFed returns an error param", async () => {
    const req = makeRequest({ error: "access_denied" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain("access_denied");
  });

  it("uses error_description in the redirect when both error and error_description are present", async () => {
    const req = makeRequest({
      error: "access_denied",
      error_description: "The user denied access",
    });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain(encodeURIComponent("The user denied access"));
    expect(location).not.toContain(encodeURIComponent("access_denied"));
  });

  it("falls back to error in the redirect when error_description is not present", async () => {
    const req = makeRequest({ error: "server_error" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain(encodeURIComponent("server_error"));
  });

  // ── Missing code or state ────────────────────────────────────────────────────

  it("redirects to login?error=missing_code_or_state when code is missing", async () => {
    const req = makeRequest({ state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("error=missing_code_or_state");
  });

  it("redirects to login?error=missing_code_or_state when state is missing", async () => {
    const req = makeRequest({ code: "auth-code-abc" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("error=missing_code_or_state");
  });

  it("redirects to login?error=missing_code_or_state when both code and state are missing", async () => {
    const req = makeRequest({});

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("error=missing_code_or_state");
  });

  // ── Invalid state / PKCE ─────────────────────────────────────────────────────

  it("redirects to login?error=invalid_state when consumePKCECookie returns null", async () => {
    mockConsumePKCECookie.mockResolvedValue(null);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("error=invalid_state");
  });

  // ── Successful auth flow ─────────────────────────────────────────────────────

  it("redirects to app base on a successful auth flow", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockResolvedValue({
      expires_in: 3600,
    });
    mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
    mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
    mockSetSessionCookie.mockResolvedValue(undefined);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    // NextResponse.redirect normalises bare origins to include a trailing slash
    expect(location?.replace(/\/$/, "")).toBe("http://localhost:3000");
  });

  it("redirects to NEXTAUTH_URL on a successful auth flow when NEXTAUTH_URL is set", async () => {
    process.env.NEXTAUTH_URL = "https://my-app.example.com";
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockResolvedValue({
      expires_in: 3600,
    });
    mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
    mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
    mockSetSessionCookie.mockResolvedValue(undefined);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location?.replace(/\/$/, "")).toBe("https://my-app.example.com");
  });

  it("redirects to returnTo path after successful auth when returnTo is stored in PKCE cookie", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123", returnTo: "/?session=abc-123" });
    mockExchangeCodeForTokens.mockResolvedValue({ expires_in: 3600 });
    mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
    mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
    mockSetSessionCookie.mockResolvedValue(undefined);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });
    const response = await GET(req);

    expect(response.headers.get("Location")).toContain("/?session=abc-123");
  });

  it("redirects to app root when no returnTo is stored in PKCE cookie", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockResolvedValue({ expires_in: 3600 });
    mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
    mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
    mockSetSessionCookie.mockResolvedValue(undefined);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });
    const response = await GET(req);

    expect(response.headers.get("Location")?.replace(/\/$/, "")).toBe("http://localhost:3000");
  });

  it("calls exchangeCodeForTokens with the code and verifier from consumePKCECookie", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockResolvedValue({
      expires_in: 3600,
    });
    mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
    mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
    mockSetSessionCookie.mockResolvedValue(undefined);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });
    await GET(req);

    expect(mockExchangeCodeForTokens).toHaveBeenCalledWith("auth-code-abc", "verifier123");
  });

  it("calls setSessionCookie with the mapped session", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockResolvedValue({
      expires_in: 3600,
    });
    mockFetchUserInfo.mockResolvedValue({ sub: "user-sub-001" });
    mockMapUserInfo.mockReturnValue(SESSION_FIXTURE);
    mockSetSessionCookie.mockResolvedValue(undefined);

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });
    await GET(req);

    expect(mockSetSessionCookie).toHaveBeenCalledWith(SESSION_FIXTURE);
  });

  // ── Catch block ──────────────────────────────────────────────────────────────

  it("redirects to login?error=... when consumePKCECookie throws", async () => {
    mockConsumePKCECookie.mockRejectedValue(new Error("Cookie store unavailable"));

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain(encodeURIComponent("Cookie store unavailable"));
  });

  it("redirects to login?error=... when exchangeCodeForTokens throws", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockRejectedValue(new Error("Token exchange failed"));

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain(encodeURIComponent("Token exchange failed"));
  });

  it("redirects to login?error=... when fetchUserInfo throws", async () => {
    mockConsumePKCECookie.mockResolvedValue({ verifier: "verifier123" });
    mockExchangeCodeForTokens.mockResolvedValue({
      expires_in: 3600,
    });
    mockFetchUserInfo.mockRejectedValue(new Error("UserInfo endpoint unreachable"));

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain(encodeURIComponent("UserInfo endpoint unreachable"));
  });

  it("uses req.nextUrl.origin as base for error redirect when NEXTAUTH_URL is not set", async () => {
    mockConsumePKCECookie.mockRejectedValue(new Error("boom"));

    const req = makeRequest({ code: "auth-code-abc", state: "state123" });

    const response = await GET(req);

    const location = response.headers.get("Location");
    expect(location).toMatch(/^http:\/\/localhost:3000\/login\?error=/);
  });
});
