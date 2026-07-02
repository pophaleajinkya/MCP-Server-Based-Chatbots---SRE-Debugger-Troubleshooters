/**
 * Unit tests for src/lib/auth-server.ts
 *
 * Coverage targets: extractUserType, mapUserInfo, getPingFedConfig,
 * generatePKCE, session cookie helpers, and PKCE cookie helpers.
 */

import { cookies } from "next/headers";

// next/headers is mocked globally in jest.setup.ts; we re-declare it here so
// TypeScript is happy and we can override the return value per test.
jest.mock("next/headers");

const mockCookies = cookies as jest.MockedFunction<typeof cookies>;

// ---------------------------------------------------------------------------
// Helper: build a fresh mock cookie store for each test
// ---------------------------------------------------------------------------
function makeMockCookieStore() {
  return {
    get: jest.fn(),
    set: jest.fn(),
    delete: jest.fn(),
  };
}

// ---------------------------------------------------------------------------
// Imports under test (must come AFTER jest.mock calls)
// ---------------------------------------------------------------------------
import {
  extractUserType,
  mapUserInfo,
  getPingFedConfig,
  generatePKCE,
  setSessionCookie,
  getSessionCookie,
  clearSessionCookie,
  setPKCECookie,
  consumePKCECookie,
  SESSION_COOKIE,
  PKCE_STATE_COOKIE,
  type AuthSession,
} from "../../src/lib/auth-server";

// ---------------------------------------------------------------------------
// Polyfill Web Crypto and TextEncoder/TextDecoder for the jsdom environment.
// jsdom in older Next.js / ts-jest setups may not expose these globals.
// ---------------------------------------------------------------------------
beforeAll(() => {
  // Polyfill TextEncoder / TextDecoder (missing in some jsdom versions)
  if (typeof globalThis.TextEncoder === "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { TextEncoder, TextDecoder } = require("util");
    Object.defineProperty(globalThis, "TextEncoder", { value: TextEncoder, writable: true });
    Object.defineProperty(globalThis, "TextDecoder", { value: TextDecoder, writable: true });
  }

  // Polyfill crypto.subtle if not available (jsdom does not ship Web Crypto)
  if (typeof globalThis.crypto === "undefined" || !globalThis.crypto.subtle) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { webcrypto } = require("crypto");
    Object.defineProperty(globalThis, "crypto", {
      value: webcrypto,
      writable: true,
      configurable: true,
    });
  }
});

// ---------------------------------------------------------------------------
// extractUserType
// ---------------------------------------------------------------------------
describe("extractUserType", () => {
  it('returns "ASSOCIATE" when employeeType is "H" (Hourly)', () => {
    expect(extractUserType({ employeeType: "H" })).toBe("ASSOCIATE");
  });

  it('returns "ASSOCIATE" when employeeType is "S" (Salaried)', () => {
    expect(extractUserType({ employeeType: "S" })).toBe("ASSOCIATE");
  });

  it('returns "VENDOR" when wm-Type is "V" (no matching employeeType)', () => {
    expect(extractUserType({ "wm-Type": "V" })).toBe("VENDOR");
  });

  it('returns "ASSOCIATE" when wm-Type is "A" (no matching employeeType)', () => {
    expect(extractUserType({ "wm-Type": "A" })).toBe("ASSOCIATE");
  });

  it("prefers employeeType over wm-Type when both are present", () => {
    // employeeType "H" wins even though wm-Type "A" would also yield "ASSOCIATE"
    expect(extractUserType({ employeeType: "H", "wm-Type": "A" })).toBe("ASSOCIATE");
  });

  it('falls through to wm-Type check when employeeType is unrecognised', () => {
    expect(extractUserType({ employeeType: "X", "wm-Type": "V" })).toBe("VENDOR");
  });

  it('returns "ASSOCIATE" (default) when both employeeType and wm-Type are unrecognised', () => {
    expect(extractUserType({ employeeType: "X", "wm-Type": "Z" })).toBe("ASSOCIATE");
  });

  it('returns "ASSOCIATE" (default) for empty claims', () => {
    expect(extractUserType({})).toBe("ASSOCIATE");
  });

  it('returns "ASSOCIATE" (default) when claims only contain unrelated keys', () => {
    expect(extractUserType({ foo: "bar", baz: 42 })).toBe("ASSOCIATE");
  });

  it('handles case-insensitive employeetype key', () => {
    expect(extractUserType({ employeetype: "S" })).toBe("ASSOCIATE");
  });

  it('handles case-insensitive wm-type key', () => {
    expect(extractUserType({ "wm-type": "V" })).toBe("VENDOR");
  });

  it('finds wm-type via Object.keys fallback when key is non-standard casing (e.g. "WM-TYPE")', () => {
    // Neither "wm-Type" nor "wm-type" match directly — falls through to Object.keys scan
    expect(extractUserType({ "WM-TYPE": "V" })).toBe("VENDOR");
  });

  it('finds wm-type via Object.keys fallback and returns ASSOCIATE for "A" value', () => {
    expect(extractUserType({ "WM-TYPE": "A" })).toBe("ASSOCIATE");
  });

  it('passes through valid LLM Gateway user_type values', () => {
    expect(extractUserType({ user_type: "TECH_DEVELOPMENT" })).toBe("TECH_DEVELOPMENT");
    expect(extractUserType({ user_type: "NO_END_USER" })).toBe("NO_END_USER");
    expect(extractUserType({ user_type: "RETAIL_CUSTOMER" })).toBe("RETAIL_CUSTOMER");
  });
});

// ---------------------------------------------------------------------------
// mapUserInfo
// ---------------------------------------------------------------------------
describe("mapUserInfo", () => {
  const ACCESS_TOKEN = "dummy";

  it("maps all fields when all claims are present", () => {
    const claims = {
      sub: "user-sub-001",
      name: "Alice Example",
      email: "alice@example.com",
      loginId: "alice",
      win_nbr: "W12345",
      employeeType: "H",
    };
    const result = mapUserInfo(claims, ACCESS_TOKEN);

    expect(result.sub).toBe("user-sub-001");
    expect(result.name).toBe("Alice Example");
    expect(result.email).toBe("alice@example.com");
    expect(result.loginId).toBe("alice");
    expect(result.win_nbr).toBe("W12345");
    expect(result.user_type).toBe("ASSOCIATE");
  });

  it("falls back name to loginId when name claim is absent", () => {
    const claims = { sub: "s1", email: "e@x.com", loginId: "jdoe" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.name).toBe("jdoe");
  });

  it("falls back loginId to sub when loginId claim is absent", () => {
    const claims = { sub: "fallback-sub", email: "e@x.com" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.loginId).toBe("fallback-sub");
  });

  it("falls back name to empty string when both name and loginId are absent", () => {
    const claims = { sub: "s2", email: "e@x.com" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    // name falls back to loginId which is absent, so String(undefined ?? "") = ""
    expect(result.name).toBe("");
  });

  it("omits win_nbr when the claim is absent", () => {
    const claims = { sub: "s3", name: "Bob", email: "b@x.com", loginId: "bob" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.win_nbr).toBeUndefined();
  });

  it("calls extractUserType and propagates the result", () => {
    const claims = { sub: "s4", "wm-Type": "A" };
    const result = mapUserInfo(claims, ACCESS_TOKEN);
    expect(result.user_type).toBe("ASSOCIATE");
  });

  it("sub falls back to empty string when sub claim is absent", () => {
    const result = mapUserInfo({}, "tok");
    expect(result.sub).toBe("");
  });

  it("loginId falls back to empty string when both loginId and sub are absent", () => {
    const result = mapUserInfo({ email: "e@x.com" }, "tok");
    expect(result.loginId).toBe("");
  });

  it("name falls back to empty string when name, loginId, and sub are all absent", () => {
    const result = mapUserInfo({}, "tok");
    expect(result.name).toBe("");
  });
});

// ---------------------------------------------------------------------------
// getPingFedConfig
// ---------------------------------------------------------------------------
describe("getPingFedConfig", () => {
  const REQUIRED_VARS: Record<string, string> = {
    PINGFED_CLIENT_ID: process.env.PINGFED_CLIENT_ID ?? "dummy",
    PINGFED_CLIENT_SECRET: process.env.PINGFED_CLIENT_SECRET ?? "dummy",
    PINGFED_REDIRECT_URI: process.env.PINGFED_REDIRECT_URI ?? "http://localhost:3000/api/auth/callback",
    PINGFED_AUTH_URL: process.env.PINGFED_AUTH_URL ?? "http://localhost/as/authorization.oauth2",
    PINGFED_TOKEN_URL: process.env.PINGFED_TOKEN_URL ?? "http://localhost/as/token.oauth2",
    PINGFED_USERINFO_URL: process.env.PINGFED_USERINFO_URL ?? "http://localhost/idp/userinfo.openid",
  };

  // Capture the original values of only the vars we touch so we can restore them
  // precisely. Avoid replacing the entire process.env object — that causes
  // side-effects in the jsdom environment (e.g. wiping NODE_ENV).
  const ALL_PINGFED_VARS = [
    ...Object.keys(REQUIRED_VARS),
    "PINGFED_LOGOUT_URL",
    "PINGFED_SCOPE",
  ];
  let savedValues: Record<string, string | undefined>;

  beforeEach(() => {
    savedValues = {};
    ALL_PINGFED_VARS.forEach((k) => {
      savedValues[k] = process.env[k];
      delete process.env[k];
    });
  });

  afterEach(() => {
    ALL_PINGFED_VARS.forEach((k) => {
      if (savedValues[k] === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = savedValues[k];
      }
    });
  });

  it("returns the correct config object when all required env vars are set", () => {
    Object.assign(process.env, REQUIRED_VARS);
    const cfg = getPingFedConfig();

    expect(cfg.clientId).toBe(REQUIRED_VARS.PINGFED_CLIENT_ID);
    expect(cfg.clientSecret).toBe(REQUIRED_VARS.PINGFED_CLIENT_SECRET);
    expect(cfg.redirectUri).toBe(REQUIRED_VARS.PINGFED_REDIRECT_URI);
    expect(cfg.authUrl).toBe(REQUIRED_VARS.PINGFED_AUTH_URL);
    expect(cfg.tokenUrl).toBe(REQUIRED_VARS.PINGFED_TOKEN_URL);
    expect(cfg.userInfoUrl).toBe(REQUIRED_VARS.PINGFED_USERINFO_URL);
  });

  it('defaults logoutUrl to "" when PINGFED_LOGOUT_URL is not set', () => {
    Object.assign(process.env, REQUIRED_VARS);
    const cfg = getPingFedConfig();
    expect(cfg.logoutUrl).toBe("");
  });

  it("uses PINGFED_LOGOUT_URL when provided", () => {
    Object.assign(process.env, REQUIRED_VARS);
    process.env.PINGFED_LOGOUT_URL = "https://ping.example.com/idp/startSLO.ping";
    const cfg = getPingFedConfig();
    expect(cfg.logoutUrl).toBe("https://ping.example.com/idp/startSLO.ping");
  });

  it('defaults scope to "openid profile email" when PINGFED_SCOPE is not set', () => {
    Object.assign(process.env, REQUIRED_VARS);
    const cfg = getPingFedConfig();
    expect(cfg.scope).toBe("openid profile email");
  });

  it("uses PINGFED_SCOPE when provided", () => {
    Object.assign(process.env, REQUIRED_VARS);
    process.env.PINGFED_SCOPE = "openid profile";
    const cfg = getPingFedConfig();
    expect(cfg.scope).toBe("openid profile");
  });

  it.each(Object.keys(REQUIRED_VARS))(
    "throws an Error with a descriptive message when %s is missing",
    (missingVar) => {
      // Set all vars except the one under test
      const envWithout = { ...REQUIRED_VARS };
      delete (envWithout as Record<string, string>)[missingVar];
      Object.assign(process.env, envWithout);

      expect(() => getPingFedConfig()).toThrow(Error);
      expect(() => getPingFedConfig()).toThrow(/PingFed configuration is incomplete/);
      expect(() => getPingFedConfig()).toThrow(/PINGFED_CLIENT_ID/);
    }
  );

  it("throws when all required env vars are missing", () => {
    expect(() => getPingFedConfig()).toThrow(/PingFed configuration is incomplete/);
  });
});

// ---------------------------------------------------------------------------
// generatePKCE
// ---------------------------------------------------------------------------
describe("generatePKCE", () => {
  it("returns an object with verifier, challenge, and state strings", async () => {
    const result = await generatePKCE();
    expect(typeof result.verifier).toBe("string");
    expect(typeof result.challenge).toBe("string");
    expect(typeof result.state).toBe("string");
  });

  it("verifier is longer than 32 characters", async () => {
    const { verifier } = await generatePKCE();
    expect(verifier.length).toBeGreaterThan(32);
  });

  it("challenge is different from verifier", async () => {
    const { verifier, challenge } = await generatePKCE();
    expect(challenge).not.toBe(verifier);
  });

  it("challenge is valid base64url (no +, /, or = characters)", async () => {
    const { challenge } = await generatePKCE();
    expect(challenge).not.toMatch(/[+/=]/);
  });

  it("verifier is valid base64url (no +, /, or = characters)", async () => {
    const { verifier } = await generatePKCE();
    expect(verifier).not.toMatch(/[+/=]/);
  });

  it("state is valid base64url (no +, /, or = characters)", async () => {
    const { state } = await generatePKCE();
    expect(state).not.toMatch(/[+/=]/);
  });

  it("state is random (consecutive calls produce different values)", async () => {
    const [first, second] = await Promise.all([generatePKCE(), generatePKCE()]);
    expect(first.state).not.toBe(second.state);
  });

  it("verifier is random (consecutive calls produce different values)", async () => {
    const [first, second] = await Promise.all([generatePKCE(), generatePKCE()]);
    expect(first.verifier).not.toBe(second.verifier);
  });

  it("challenge matches the SHA-256 / base64url of the verifier", async () => {
    const { verifier, challenge } = await generatePKCE();

    // Recompute the expected challenge from the returned verifier
    const encoder = new TextEncoder();
    const data = encoder.encode(verifier);
    const digest = await crypto.subtle.digest("SHA-256", data);
    const bytes = new Uint8Array(digest);
    let str = "";
    bytes.forEach((b) => (str += String.fromCharCode(b)));
    const expected = btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");

    expect(challenge).toBe(expected);
  });
});

// ---------------------------------------------------------------------------
// Session cookie helpers
// ---------------------------------------------------------------------------
describe("setSessionCookie", () => {
  it("calls cookieStore.set with the serialised session and expected options", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    const session: AuthSession = {
      sub: "u1",
      name: "Alice",
      email: "alice@example.com",
      loginId: "alice",
      user_type: "H",
      expires_at: Math.floor(Date.now() / 1000) + 10800,
    };

    await setSessionCookie(session);

    expect(mockStore.set).toHaveBeenCalledTimes(1);
    const [name, value, opts] = mockStore.set.mock.calls[0];
    expect(name).toBe(SESSION_COOKIE);
    expect(JSON.parse(value)).toEqual(session);
    expect(opts).toMatchObject({
      httpOnly: true,
      path: "/",
      sameSite: "lax",
    });
  });

  it("sets a positive maxAge on the cookie", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    await setSessionCookie({
      sub: "u2",
      name: "Bob",
      email: "b@x.com",
      loginId: "bob",
      user_type: "S",
      expires_at: Math.floor(Date.now() / 1000) + 10800,
    });

    const [, , opts] = mockStore.set.mock.calls[0];
    expect(opts.maxAge).toBeGreaterThan(0);
  });
});

describe("getSessionCookie", () => {
  it("returns the parsed session when the cookie exists and is valid JSON", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    const session: AuthSession = {
      sub: "u3",
      name: "Carol",
      email: "carol@x.com",
      loginId: "carol",
      user_type: "standard",
      expires_at: Math.floor(Date.now() / 1000) + 10800,
    };
    mockStore.get.mockReturnValue({ value: JSON.stringify(session) });

    const result = await getSessionCookie();
    expect(result).toEqual(session);
  });

  it("returns null when the cookie is absent", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue(undefined);

    expect(await getSessionCookie()).toBeNull();
  });

  it("returns null when the cookie value is an empty string", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({ value: "" });

    expect(await getSessionCookie()).toBeNull();
  });

  it("returns null when the cookie contains corrupt (non-JSON) data", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({ value: "not-valid-json{{" });

    expect(await getSessionCookie()).toBeNull();
  });

  it("looks up the cookie under the SESSION_COOKIE name", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue(undefined);

    await getSessionCookie();

    expect(mockStore.get).toHaveBeenCalledWith(SESSION_COOKIE);
  });
});

describe("clearSessionCookie", () => {
  it("sets the SESSION_COOKIE to an empty value with maxAge=0 to expire it", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    await clearSessionCookie();

    // The implementation expires the cookie by calling set(..., "", { maxAge: 0 })
    // rather than delete(), so that the browser receives a Set-Cookie header that
    // instructs it to remove the cookie.
    expect(mockStore.set).toHaveBeenCalledWith(
      SESSION_COOKIE,
      "",
      expect.objectContaining({ maxAge: 0 })
    );
  });
});

// ---------------------------------------------------------------------------
// PKCE cookie helpers
// ---------------------------------------------------------------------------
describe("setPKCECookie", () => {
  it("calls cookieStore.set with serialised state+verifier and expected options", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    await setPKCECookie("state-abc", "verifier-xyz");

    expect(mockStore.set).toHaveBeenCalledTimes(1);
    const [name, value, opts] = mockStore.set.mock.calls[0];
    expect(name).toBe(PKCE_STATE_COOKIE);
    expect(JSON.parse(value)).toEqual({ state: "state-abc", verifier: "verifier-xyz" });
    expect(opts).toMatchObject({
      httpOnly: true,
      path: "/",
      sameSite: "lax",
    });
  });

  it("uses a short maxAge (≤ 300 s) for the PKCE cookie", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    await setPKCECookie("s", "v");

    const [, , opts] = mockStore.set.mock.calls[0];
    expect(opts.maxAge).toBeLessThanOrEqual(300);
    expect(opts.maxAge).toBeGreaterThan(0);
  });

  it("stores returnTo in the cookie when provided", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    await setPKCECookie("state-abc", "verifier-xyz", "/?session=test-id");

    const [, value] = mockStore.set.mock.calls[0];
    expect(JSON.parse(value)).toEqual({
      state: "state-abc",
      verifier: "verifier-xyz",
      returnTo: "/?session=test-id",
    });
  });

  it("does not include returnTo key when not provided", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);

    await setPKCECookie("state-abc", "verifier-xyz");

    const [, value] = mockStore.set.mock.calls[0];
    expect(JSON.parse(value)).not.toHaveProperty("returnTo");
  });
});

describe("consumePKCECookie", () => {
  it("returns the verifier when state matches and cookie exists", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({
      value: JSON.stringify({ state: "expected-state", verifier: "my-verifier" }),
    });

    const result = await consumePKCECookie("expected-state");
    expect(result).toEqual({ verifier: "my-verifier" });
  });

  it("includes returnTo in the result when it was stored", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({
      value: JSON.stringify({ state: "s", verifier: "v", returnTo: "/?session=abc" }),
    });

    const result = await consumePKCECookie("s");
    expect(result).toEqual({ verifier: "v", returnTo: "/?session=abc" });
  });

  it("omits returnTo when it was not stored", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({
      value: JSON.stringify({ state: "s", verifier: "v" }),
    });

    const result = await consumePKCECookie("s");
    expect(result).toEqual({ verifier: "v" });
    expect(result).not.toHaveProperty("returnTo");
  });

  it("returns null when state does not match", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({
      value: JSON.stringify({ state: "actual-state", verifier: "my-verifier" }),
    });

    expect(await consumePKCECookie("wrong-state")).toBeNull();
  });

  it("returns null when the PKCE cookie is absent", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue(undefined);

    expect(await consumePKCECookie("any-state")).toBeNull();
  });

  it("returns null when the cookie contains corrupt JSON", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({ value: "{{bad json}}" });

    expect(await consumePKCECookie("any-state")).toBeNull();
  });

  it("deletes the PKCE cookie after reading it (even when state matches)", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({
      value: JSON.stringify({ state: "s", verifier: "v" }),
    });

    await consumePKCECookie("s");

    expect(mockStore.delete).toHaveBeenCalledWith(PKCE_STATE_COOKIE);
  });

  it("deletes the PKCE cookie even when state does not match", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue({
      value: JSON.stringify({ state: "correct", verifier: "v" }),
    });

    await consumePKCECookie("wrong");

    // The delete happens before the state comparison in the current implementation
    expect(mockStore.delete).toHaveBeenCalledWith(PKCE_STATE_COOKIE);
  });

  it("looks up the cookie under the PKCE_STATE_COOKIE name", async () => {
    const mockStore = makeMockCookieStore();
    mockCookies.mockResolvedValue(mockStore as any);
    mockStore.get.mockReturnValue(undefined);

    await consumePKCECookie("s");

    expect(mockStore.get).toHaveBeenCalledWith(PKCE_STATE_COOKIE);
  });
});
