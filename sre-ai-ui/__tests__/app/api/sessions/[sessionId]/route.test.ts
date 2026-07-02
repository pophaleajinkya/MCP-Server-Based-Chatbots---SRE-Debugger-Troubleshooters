/**
 * Tests for DELETE /api/sessions/[sessionId]
 *
 * next/server (specifically NextResponse) references global Request which is
 * not available in jsdom. We fully mock next/server here and polyfill the
 * Web Fetch API globals from @whatwg-node/fetch so that fetch() calls work.
 */

// ─── Web Fetch API polyfill (must run before any next/server import) ──────────
const {
  fetch: nodeFetch,
  Response: NodeResponse,
  Headers: NodeHeaders,
  Request: NodeRequest,
} = require("@whatwg-node/fetch");

if (!global.fetch)    (global as Record<string, unknown>).fetch    = nodeFetch;
if (!global.Response) (global as Record<string, unknown>).Response = NodeResponse;
if (!global.Headers)  (global as Record<string, unknown>).Headers  = NodeHeaders;
if (!global.Request)  (global as Record<string, unknown>).Request  = NodeRequest;

// ─── Mock next/server completely to avoid loading Next.js web runtime ────────
// NextResponse.json is replaced with a factory that builds a plain Response.
jest.mock("next/server", () => ({
  NextResponse: {
    json: (body: unknown, init?: ResponseInit) => {
      const { Response: R } = require("@whatwg-node/fetch");
      return new R(JSON.stringify(body), {
        ...init,
        headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
      });
    },
  },
}));

// ─── Mock auth-server before the route module is loaded ──────────────────────
jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
  buildLLMGatewayHeaders: jest.fn().mockReturnValue({}),
}));

import { type NextRequest } from "next/server";
import { DELETE } from "@/app/api/sessions/[sessionId]/route";
import {
  getSessionCookie,
  buildLLMGatewayHeaders,
} from "@/lib/auth-server";

const mockGetSessionCookie = getSessionCookie as jest.MockedFunction<typeof getSessionCookie>;
const mockBuildLLMGatewayHeaders = buildLLMGatewayHeaders as jest.MockedFunction<
  typeof buildLLMGatewayHeaders
>;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeReq(
  queryParams: Record<string, string> = {},
  headerMap: Record<string, string> = {}
): NextRequest {
  const url = new URL("http://localhost/api/sessions/test-session-id");
  Object.entries(queryParams).forEach(([k, v]) => url.searchParams.set(k, v));
  return {
    nextUrl: url,
    headers: {
      get: (key: string) => headerMap[key.toLowerCase()] ?? null,
    },
  } as unknown as NextRequest;
}

function makeParams(sessionId: string): { params: Promise<{ sessionId: string }> } {
  return {
    params: Promise.resolve({ sessionId }),
  };
}

function makeSession(overrides: Partial<{ loginId: string; }> = {}) {
  return {
    sub: "user-sub",
    name: "Test User",
    email: "test@example.com",
    loginId: overrides.loginId ?? "testuser",
    user_type: "ASSOCIATE",
    expires_at: Math.floor(Date.now() / 1000) + 3600,
  };
}

function makeUpstreamResponse(overrides: { status?: number; ok?: boolean } = {}): Response {
  return {
    ok: overrides.ok ?? true,
    status: overrides.status ?? 200,
    headers: new NodeHeaders(),
    json: jest.fn().mockResolvedValue({}),
    text: jest.fn().mockResolvedValue(""),
  } as unknown as Response;
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("DELETE /api/sessions/[sessionId]", () => {
  let mockFetch: jest.SpyInstance;

  beforeEach(() => {
    mockFetch = jest.spyOn(global, "fetch");
    mockGetSessionCookie.mockResolvedValue(null);
    mockBuildLLMGatewayHeaders.mockReturnValue({});
  });

  afterEach(() => {
    mockFetch.mockRestore();
    jest.resetAllMocks();
  });

  // ── Authorization ────────────────────────────────────────────────────────────

  describe("authorization", () => {
    it("returns 401 when no session cookie and no user_id query param", async () => {
      mockGetSessionCookie.mockResolvedValue(null);
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body).toEqual({ error: "unauthorized" });
    });

    it("proceeds when userId is provided via query param (no session cookie)", async () => {
      mockGetSessionCookie.mockResolvedValue(null);
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ user_id: "query-user" });
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual({ terminated: true });
    });

    it("uses loginId from session cookie over query param", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession({ loginId: "cookie-user" }));
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ user_id: "query-user" });
      await DELETE(req, makeParams("session-abc"));

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("user_id=cookie-user");
    });

    it("falls back to query param when session has no loginId", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession({ loginId: "" }));
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ user_id: "fallback-user" });
      await DELETE(req, makeParams("session-abc"));

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("user_id=fallback-user");
    });
  });

  // ── Happy path ───────────────────────────────────────────────────────────────

  describe("successful termination", () => {
    it("returns { terminated: true, status: 200 } when upstream returns 200", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 200, ok: true }));
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual({ terminated: true });
    });

    it("returns { terminated: true, status: 200 } when upstream returns 204", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 204, ok: true }));
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual({ terminated: true });
    });

    it("returns { terminated: true, status: 200 } when upstream returns 404 (already gone)", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 404, ok: false }));
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual({ terminated: true });
    });
  });

  // ── Non-success upstream responses ───────────────────────────────────────────

  describe("non-success upstream responses", () => {
    it("returns { terminated: false } with upstream status when upstream returns 500", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 500, ok: false }));
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ terminated: false });
    });

    it("returns { terminated: false } with upstream status when upstream returns 403", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse({ status: 403, ok: false }));
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      expect(res.status).toBe(403);
      const body = await res.json();
      expect(body).toEqual({ terminated: false });
    });
  });

  // ── Upstream fetch failure ───────────────────────────────────────────────────

  describe("upstream fetch failure (network error)", () => {
    it("returns { terminated: false, status: 200 } when fetch throws", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));
      const req = makeReq();
      const res = await DELETE(req, makeParams("session-abc"));

      // Backend unreachable is treated as a soft failure
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual({ terminated: false });
    });

    it("does not propagate the network error to the caller", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockRejectedValue(new Error("DNS resolution failed"));
      const req = makeReq();

      await expect(DELETE(req, makeParams("session-abc"))).resolves.not.toThrow();
    });
  });

  // ── URL construction ─────────────────────────────────────────────────────────

  describe("upstream URL construction", () => {
    it("encodes the sessionId in the upstream URL", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession({ loginId: "user1" }));
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session/with/slashes"));

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("session%2Fwith%2Fslashes");
    });

    it("encodes userId in the upstream URL query param", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession({ loginId: "user with spaces" }));
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("user_id=user%20with%20spaces");
    });

    it("calls fetch with DELETE method", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      const [, options] = mockFetch.mock.calls[0];
      expect(options.method).toBe("DELETE");
    });

    it("calls fetch with cache: no-store", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      const [, options] = mockFetch.mock.calls[0];
      expect(options.cache).toBe("no-store");
    });

    it("constructs URL with sessions path and user_id param", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession({ loginId: "user1" }));
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("/sessions/");
      expect(calledUrl).toContain("user_id=user1");
    });
  });

  // ── Header building ──────────────────────────────────────────────────────────

  describe("LLM gateway headers", () => {
    it("calls buildLLMGatewayHeaders with the session and request", async () => {
      const session = makeSession();
      mockGetSessionCookie.mockResolvedValue(session);
      mockBuildLLMGatewayHeaders.mockReturnValue({
        Authorization: "Bearer token-abc",
        "wm_llm_gw.user_name": "testuser",
      });
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      expect(mockBuildLLMGatewayHeaders).toHaveBeenCalledWith(session, req);
    });

    it("passes built headers to the fetch call", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      const builtHeaders = { Authorization: "Bearer token-abc", "x-custom": "value" };
      mockBuildLLMGatewayHeaders.mockReturnValue(builtHeaders);
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      const [, options] = mockFetch.mock.calls[0];
      expect(options.headers).toEqual(builtHeaders);
    });

    it("calls buildLLMGatewayHeaders with null session when no cookie", async () => {
      mockGetSessionCookie.mockResolvedValue(null);
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq({ user_id: "some-user" });
      await DELETE(req, makeParams("session-abc"));

      expect(mockBuildLLMGatewayHeaders).toHaveBeenCalledWith(null, req);
    });
  });

  // ── Session cookie resolution ────────────────────────────────────────────────

  describe("session cookie resolution", () => {
    it("calls getSessionCookie to resolve the session", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession());
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("session-abc"));

      expect(mockGetSessionCookie).toHaveBeenCalledTimes(1);
    });

    it("awaits the params promise to get the sessionId", async () => {
      mockGetSessionCookie.mockResolvedValue(makeSession({ loginId: "user1" }));
      mockFetch.mockResolvedValue(makeUpstreamResponse());
      const req = makeReq();
      await DELETE(req, makeParams("my-session-id-123"));

      const [calledUrl] = mockFetch.mock.calls[0];
      expect(calledUrl).toContain("my-session-id-123");
    });
  });
});
