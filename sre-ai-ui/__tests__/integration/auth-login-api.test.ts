/**
 * @jest-environment node
 *
 * Integration tests for the auth login API route.
 * Tests GET /api/auth/login handler function directly.
 *
 * Uses the `node` environment so that the Web Fetch API globals (Request,
 * Response, Headers) are available — these are provided by the Next.js runtime
 * but are not present in jest-environment-jsdom.
 */

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  generatePKCE: jest.fn(),
  getPingFedConfig: jest.fn(),
  setPKCECookie: jest.fn(),
}));

import { GET } from "@/app/api/auth/login/route";
import { NextRequest } from "next/server";
import { generatePKCE, getPingFedConfig, setPKCECookie } from "@/lib/auth-server";

function makeLoginRequest(params: Record<string, string> = {}): NextRequest {
  const url = new URL("http://localhost:3000/api/auth/login");
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  return new NextRequest(url.toString());
}

const mockGetPingFedConfig = getPingFedConfig as jest.MockedFunction<typeof getPingFedConfig>;
const mockGeneratePKCE = generatePKCE as jest.MockedFunction<typeof generatePKCE>;
const mockSetPKCECookie = setPKCECookie as jest.MockedFunction<typeof setPKCECookie>;

// ─── GET /api/auth/login ──────────────────────────────────────────────────────

describe("GET /api/auth/login", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    delete process.env.NEXTAUTH_URL;

    (getPingFedConfig as jest.Mock).mockReturnValue({
      clientId: "client123",
      redirectUri: "http://localhost:3000/api/auth/callback",
      scope: "openid profile",
      authUrl: "https://sso.walmart.com/oauth2/authorize",
    });
    (generatePKCE as jest.Mock).mockResolvedValue({
      verifier: "verifier123",
      challenge: "challenge123",
      state: "state123",
    });
    (setPKCECookie as jest.Mock).mockResolvedValue(undefined);
  });

  // ── Success path ─────────────────────────────────────────────────────────────

  it("returns a redirect response on the success path", async () => {
    const response = await GET(makeLoginRequest());

    expect(response.status).toBe(307);
  });

  it("redirects to the PingFed authorization URL on the success path", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("https://sso.walmart.com/oauth2/authorize");
  });

  it("includes client_id in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("client_id=client123");
  });

  it("includes the code_challenge in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("code_challenge=challenge123");
  });

  it("includes code_challenge_method=S256 in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("code_challenge_method=S256");
  });

  it("includes the state in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("state=state123");
  });

  it("includes response_type=code in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("response_type=code");
  });

  it("includes the redirect_uri in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain(encodeURIComponent("http://localhost:3000/api/auth/callback"));
  });

  it("includes the scope in the authorization URL", async () => {
    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toContain("scope=");
    expect(location).toContain("openid");
  });

  it("calls setPKCECookie with state and verifier when no returnTo is provided", async () => {
    await GET(makeLoginRequest());

    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("passes returnTo to setPKCECookie when a valid relative returnTo param is provided", async () => {
    await GET(makeLoginRequest({ returnTo: "/?session=abc-123" }));

    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", "/?session=abc-123");
  });

  it("ignores returnTo when it is an absolute URL (open-redirect guard)", async () => {
    await GET(makeLoginRequest({ returnTo: "https://evil.com/steal" }));

    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("ignores returnTo when it is a protocol-relative URL (open-redirect guard)", async () => {
    await GET(makeLoginRequest({ returnTo: "//evil.com/steal" }));

    expect(mockSetPKCECookie).toHaveBeenCalledWith("state123", "verifier123", undefined);
  });

  it("calls generatePKCE exactly once", async () => {
    await GET(makeLoginRequest());

    expect(mockGeneratePKCE).toHaveBeenCalledTimes(1);
  });

  it("calls getPingFedConfig exactly once", async () => {
    await GET(makeLoginRequest());

    expect(mockGetPingFedConfig).toHaveBeenCalledTimes(1);
  });

  // ── Error / catch path ───────────────────────────────────────────────────────

  it("redirects to /login?error=... when getPingFedConfig throws", async () => {
    mockGetPingFedConfig.mockImplementation(() => {
      throw new Error("PingFed configuration is incomplete.");
    });

    const response = await GET(makeLoginRequest());

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain(encodeURIComponent("PingFed configuration is incomplete."));
  });

  it("redirects to /login?error=... when generatePKCE throws", async () => {
    mockGeneratePKCE.mockRejectedValue(new Error("PKCE generation failed"));

    const response = await GET(makeLoginRequest());

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain(encodeURIComponent("PKCE generation failed"));
  });

  it("redirects to /login?error=... when setPKCECookie throws", async () => {
    mockSetPKCECookie.mockRejectedValue(new Error("Cookie write error"));

    const response = await GET(makeLoginRequest());

    expect(response.status).toBe(307);
    const location = response.headers.get("Location");
    expect(location).toContain("/login?error=");
    expect(location).toContain(encodeURIComponent("Cookie write error"));
  });

  it("uses req.nextUrl.origin as base for error redirect when NEXTAUTH_URL is not set", async () => {
    mockGetPingFedConfig.mockImplementation(() => {
      throw new Error("bad config");
    });

    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toMatch(/^http:\/\/localhost:3000\/login\?error=/);
  });

  it("uses NEXTAUTH_URL as base for error redirect when it is set", async () => {
    process.env.NEXTAUTH_URL = "https://prod.example.com";
    mockGetPingFedConfig.mockImplementation(() => {
      throw new Error("bad config");
    });

    const response = await GET(makeLoginRequest());

    const location = response.headers.get("Location");
    expect(location).toMatch(/^https:\/\/prod\.example\.com\/login\?error=/);
  });
});
