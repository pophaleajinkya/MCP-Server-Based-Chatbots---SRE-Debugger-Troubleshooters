/**
 * @jest-environment node
 *
 * Additional tests for src/lib/auth-server.ts covering functions not tested
 * in auth-server.test.ts:
 *  - exchangeCodeForTokens
 *  - fetchUserInfo
 *  - extractUserType (all branches)
 *  - mapUserInfo (win_nbr present/absent)
 */

// ─── Module under test ────────────────────────────────────────────────────────

import {
  exchangeCodeForTokens,
  fetchUserInfo,
  extractUserType,
  mapUserInfo,
  buildLLMGatewayHeaders,
  type AuthSession,
} from "../../src/lib/auth-server";

// ─── Test environment variables ───────────────────────────────────────────────

const ENV: Record<string, string> = {
  PINGFED_CLIENT_ID: "test-client",
  PINGFED_CLIENT_SECRET: "test-secret",
  PINGFED_REDIRECT_URI: "http://localhost:3000/callback",
  PINGFED_AUTH_URL: "http://pingfed/auth",
  PINGFED_TOKEN_URL: "http://pingfed/token",
  PINGFED_USERINFO_URL: "http://pingfed/userinfo",
};

// Keep a reference to the real fetch so we can restore it after each test
const originalFetch = global.fetch;

beforeEach(() => {
  Object.entries(ENV).forEach(([k, v]) => {
    process.env[k] = v;
  });
});

afterEach(() => {
  global.fetch = originalFetch;
  Object.keys(ENV).forEach((k) => delete process.env[k]);
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Create a minimal fetch mock that resolves to the given status and body. */
function mockFetch(status: number, body: unknown): void {
  const jsonBody = typeof body === "string" ? body : JSON.stringify(body);
  global.fetch = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
    text: jest.fn().mockResolvedValue(jsonBody),
  });
}

// ─── exchangeCodeForTokens ────────────────────────────────────────────────────

describe("exchangeCodeForTokens", () => {
  it("successful exchange returns token JSON", async () => {
    const tokenResponse = {
      id_token: "id-xyz",
      expires_in: 3600,
    };
    mockFetch(200, tokenResponse);

    const result = await exchangeCodeForTokens("auth-code-123", "verifier-abc");

    expect(result).toEqual(tokenResponse);
  });

  it("throws when response is not ok, with status and body in message", async () => {
    mockFetch(400, "invalid_grant");

    await expect(
      exchangeCodeForTokens("bad-code", "verifier")
    ).rejects.toThrow("Token exchange failed (400): invalid_grant");
  });

  it("sends correct grant_type=authorization_code", async () => {
    mockFetch(200, { });

    await exchangeCodeForTokens("code-999", "verifier-999");

    const fetchMock = global.fetch as jest.Mock;
    const [, options] = fetchMock.mock.calls[0];
    const sentBody = options.body as string;

    expect(sentBody).toContain("grant_type=authorization_code");
  });

  it("sends the provided code in the request body", async () => {
    mockFetch(200, { });

    await exchangeCodeForTokens("my-code-777", "verifier-777");

    const fetchMock = global.fetch as jest.Mock;
    const [, options] = fetchMock.mock.calls[0];
    const sentBody = options.body as string;

    expect(sentBody).toContain("code=my-code-777");
  });

  it("sends the code_verifier in the request body", async () => {
    mockFetch(200, { });

    await exchangeCodeForTokens("code", "my-verifier-abc");

    const fetchMock = global.fetch as jest.Mock;
    const [, options] = fetchMock.mock.calls[0];
    const sentBody = options.body as string;

    expect(sentBody).toContain("code_verifier=my-verifier-abc");
  });

  it("sends clientId and clientSecret in the request body", async () => {
    mockFetch(200, { });

    await exchangeCodeForTokens("code", "verifier");

    const fetchMock = global.fetch as jest.Mock;
    const [, options] = fetchMock.mock.calls[0];
    const sentBody = options.body as string;

    expect(sentBody).toContain(`client_id=${ENV.PINGFED_CLIENT_ID}`);
    expect(sentBody).toContain(`client_secret=${ENV.PINGFED_CLIENT_SECRET}`);
  });

  it("POSTs to the configured token URL", async () => {
    mockFetch(200, { });

    await exchangeCodeForTokens("code", "verifier");

    const fetchMock = global.fetch as jest.Mock;
    const [url, options] = fetchMock.mock.calls[0];

    expect(url).toBe(ENV.PINGFED_TOKEN_URL);
    expect(options.method).toBe("POST");
  });

  it("throws with a descriptive message when response is 401", async () => {
    mockFetch(401, "unauthorized");

    await expect(
      exchangeCodeForTokens("code", "verifier")
    ).rejects.toThrow(/Token exchange failed \(401\)/);
  });
});

// ─── fetchUserInfo ────────────────────────────────────────────────────────────

describe("fetchUserInfo", () => {
  it("successful call returns user info JSON", async () => {
    const userInfoResponse = {
      sub: "user-001",
      name: "Alice Test",
      email: "alice@example.com",
      loginId: "alice",
    };
    mockFetch(200, userInfoResponse);

    const result = await fetchUserInfo("my-access-token");

    expect(result).toEqual(userInfoResponse);
  });

  it("throws when response is not ok with status in message", async () => {
    mockFetch(401, "unauthorized");

    await expect(fetchUserInfo("bad-token")).rejects.toThrow(
      "UserInfo request failed (401)"
    );
  });

  it("sends Bearer authorization header", async () => {
    mockFetch(200, { sub: "u1" });

    await fetchUserInfo("my-bearer-token-xyz");

    const fetchMock = global.fetch as jest.Mock;
    const [, options] = fetchMock.mock.calls[0];
    const authHeader = options.headers["Authorization"] as string;

    expect(authHeader).toBe("Bearer my-bearer-token-xyz");
  });

  it("GETs the configured userInfo URL", async () => {
    mockFetch(200, { sub: "u1" });

    await fetchUserInfo("token");

    const fetchMock = global.fetch as jest.Mock;
    const [url] = fetchMock.mock.calls[0];

    expect(url).toBe(ENV.PINGFED_USERINFO_URL);
  });

  it("throws with 403 status in message", async () => {
    mockFetch(403, "forbidden");

    await expect(fetchUserInfo("token")).rejects.toThrow(
      /UserInfo request failed \(403\)/
    );
  });
});

// ─── extractUserType ──────────────────────────────────────────────────────────

describe("extractUserType", () => {
  it('employeeType "H" → "ASSOCIATE"', () => {
    expect(extractUserType({ employeeType: "H" })).toBe("ASSOCIATE");
  });

  it('employeeType "S" → "ASSOCIATE"', () => {
    expect(extractUserType({ employeeType: "S" })).toBe("ASSOCIATE");
  });

  it('wm-Type "V" → "VENDOR" (when no matching employeeType)', () => {
    expect(extractUserType({ "wm-Type": "V" })).toBe("VENDOR");
  });

  it('wm-Type "A" → "ASSOCIATE" (when no matching employeeType)', () => {
    expect(extractUserType({ "wm-Type": "A" })).toBe("ASSOCIATE");
  });

  it('no known type → "ASSOCIATE" (default for internal tool)', () => {
    expect(extractUserType({})).toBe("ASSOCIATE");
  });

  it('unknown employeeType and unknown wm-Type → "ASSOCIATE"', () => {
    expect(extractUserType({ employeeType: "X", "wm-Type": "Z" })).toBe("ASSOCIATE");
  });

  it("employeeType takes priority over wm-Type when both are present", () => {
    expect(extractUserType({ employeeType: "S", "wm-Type": "V" })).toBe("ASSOCIATE");
  });

  it("falls through to wm-Type when employeeType is unrecognised", () => {
    expect(extractUserType({ employeeType: "X", "wm-Type": "A" })).toBe("ASSOCIATE");
  });
});

// ─── mapUserInfo ──────────────────────────────────────────────────────────────

describe("mapUserInfo", () => {
  const ACCESS_TOKEN = "test-access-token";

  it("name falls back to loginId when name is absent", () => {
    const claims = { sub: "u1", loginId: "jdoe", email: "j@example.com" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.name).toBe("jdoe");
  });

  it("loginId falls back to sub when loginId is absent", () => {
    const claims = { sub: "sub-fallback", email: "e@example.com" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.loginId).toBe("sub-fallback");
  });

  it("win_nbr is included when present in claims", () => {
    const claims = {
      sub: "u2",
      name: "Bob",
      email: "bob@example.com",
      loginId: "bob",
      win_nbr: "W99999",
    };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.win_nbr).toBe("W99999");
  });

  it("win_nbr is undefined when not in claims", () => {
    const claims = { sub: "u3", name: "Carol", email: "carol@example.com", loginId: "carol" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.win_nbr).toBeUndefined();
  });

  it("maps sub correctly", () => {
    const claims = { sub: "my-sub-123", name: "Test", email: "t@t.com", loginId: "tuser" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.sub).toBe("my-sub-123");
  });

  it("maps email correctly", () => {
    const claims = { sub: "u4", email: "myemail@example.com", loginId: "u4" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.email).toBe("myemail@example.com");
  });

  it("computes expires_at as current time plus expiresIn", () => {
    const before = Math.floor(Date.now() / 1000);
    const expiresIn = 7200;
    const result = mapUserInfo({ sub: "u6" }, ACCESS_TOKEN, expiresIn);
    const after = Math.floor(Date.now() / 1000);

    expect(result.expires_at).toBeGreaterThanOrEqual(before + expiresIn);
    expect(result.expires_at).toBeLessThanOrEqual(after + expiresIn);
  });

  it("uses default expiresIn of 3 hours (10800 seconds)", () => {
    const before = Math.floor(Date.now() / 1000);
    const result = mapUserInfo({ sub: "u7" }, ACCESS_TOKEN);
    const after = Math.floor(Date.now() / 1000);

    expect(result.expires_at).toBeGreaterThanOrEqual(before + 10800);
    expect(result.expires_at).toBeLessThanOrEqual(after + 10800);
  });

  it("derives user_type via extractUserType", () => {
    const claims = { sub: "u8", "wm-Type": "A" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.user_type).toBe("ASSOCIATE");
  });

  it("win_nbr is converted to string when present", () => {
    const claims = {
      sub: "u9",
      win_nbr: 12345, // number, not string
    };
    const result = mapUserInfo(claims as Record<string, unknown>, ACCESS_TOKEN);
    expect(result.win_nbr).toBe("12345");
    expect(typeof result.win_nbr).toBe("string");
  });
});

// ─── buildLLMGatewayHeaders ────────────────────────────────────────────────────

describe("buildLLMGatewayHeaders", () => {
  const baseSession: AuthSession = {
    sub: "u1",
    name: "Alice",
    email: "alice@example.com",
    loginId: "alice",
    user_type: "ASSOCIATE",
    expires_at: Math.floor(Date.now() / 1000) + 3600,
  };

  it("returns empty object when session is null", () => {
    expect(buildLLMGatewayHeaders(null)).toEqual({});
  });

  it("returns user_type and loginId headers from session", () => {
    const headers = buildLLMGatewayHeaders(baseSession);
    expect(headers["wm_llm_gw.user_type"]).toBe("ASSOCIATE");
    expect(headers["wm_llm_gw.user_name"]).toBe("alice");
    expect(headers["loginId"]).toBe("alice");
  });

  it("includes user IP from x-forwarded-for when req is provided", () => {
    const req = {
      headers: {
        get: (name: string) => {
          if (name === "x-forwarded-for") return "1.2.3.4, 5.6.7.8";
          if (name === "user-agent") return "TestAgent/1.0";
          return null;
        },
      },
    };
    const headers = buildLLMGatewayHeaders(baseSession, req);
    expect(headers["wm_llm_gw.user_ip"]).toBe("1.2.3.4");
    expect(headers["wm_llm_gw.user_agent"]).toBe("TestAgent/1.0");
  });

  it("falls back to x-real-ip when x-forwarded-for is absent", () => {
    const req = {
      headers: {
        get: (name: string) => {
          if (name === "x-real-ip") return "10.0.0.1";
          return null;
        },
      },
    };
    const headers = buildLLMGatewayHeaders(baseSession, req);
    expect(headers["wm_llm_gw.user_ip"]).toBe("10.0.0.1");
  });

  it("omits user_ip when neither x-forwarded-for nor x-real-ip is present", () => {
    const req = {
      headers: {
        get: () => null,
      },
    };
    const headers = buildLLMGatewayHeaders(baseSession, req);
    expect(headers["wm_llm_gw.user_ip"]).toBeUndefined();
    expect(headers["wm_llm_gw.user_agent"]).toBeUndefined();
  });

  it("omits user_type header when session.user_type is empty", () => {
    const session = { ...baseSession, user_type: "" };
    const headers = buildLLMGatewayHeaders(session);
    expect(headers["wm_llm_gw.user_type"]).toBeUndefined();
  });

  it("omits loginId headers when session.loginId is empty", () => {
    const session = { ...baseSession, loginId: "" };
    const headers = buildLLMGatewayHeaders(session);
    expect(headers["wm_llm_gw.user_name"]).toBeUndefined();
    expect(headers["loginId"]).toBeUndefined();
  });

  it("omits Authorization header when session.access_token is empty", () => {
    const session = { ...baseSession, };
    const headers = buildLLMGatewayHeaders(session);
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("works with req but no user-agent", () => {
    const req = {
      headers: {
        get: (name: string) => {
          if (name === "x-forwarded-for") return "9.8.7.6";
          return null;
        },
      },
    };
    const headers = buildLLMGatewayHeaders(baseSession, req);
    expect(headers["wm_llm_gw.user_ip"]).toBe("9.8.7.6");
    expect(headers["wm_llm_gw.user_agent"]).toBeUndefined();
  });
});
