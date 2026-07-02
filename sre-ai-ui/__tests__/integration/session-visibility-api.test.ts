/**
 * @jest-environment node
 *
 * Integration tests for the session visibility API route.
 * Tests PATCH /api/sessions/[sessionId]/visibility handler directly.
 */

import { PATCH } from "@/app/api/sessions/[sessionId]/visibility/route";
import { NextRequest } from "next/server";
import type { AuthSession } from "@/lib/auth-server";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
  buildLLMGatewayHeaders: jest.fn((session: Record<string, string> | null) => {
    if (!session) return {};
    const h: Record<string, string> = {};
    if (session.user_type)    h["wm_llm_gw.user_type"] = session.user_type;
    if (session.loginId)      h["wm_llm_gw.user_name"] = session.loginId;
    if (session.loginId)      h["loginId"]              = session.loginId;
    if (session.access_token) h["Authorization"]        = `Bearer ${session.access_token}`;
    return h;
  }),
}));

const mockFetch = jest.fn();
global.fetch = mockFetch;

import { getSessionCookie } from "@/lib/auth-server";

const mockGetSessionCookie = getSessionCookie as jest.MockedFunction<typeof getSessionCookie>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const SESSION_FIXTURE: AuthSession = {
  sub: "user-sub-001",
  name: "Jane Doe",
  email: "jane.doe@example.com",
  loginId: "jdoe",
  user_type: "S",
  expires_at: Math.floor(Date.now() / 1000) + 10800,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makePatchRequest(body: unknown): NextRequest {
  return new NextRequest(
    "http://localhost:3000/api/sessions/sess-123/visibility",
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
}

function makeContext(sessionId: string) {
  return { params: Promise.resolve({ sessionId }) };
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("PATCH /api/sessions/[sessionId]/visibility", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetSessionCookie.mockResolvedValue(null);
  });

  // ── user_id injection ───────────────────────────────────────────────────────

  it("injects user_id from session loginId when body has no user_id", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    const req = makePatchRequest({ visible: true });
    await PATCH(req, makeContext("sess-123"));

    const [, fetchOptions] = mockFetch.mock.calls[0];
    const sentBody = JSON.parse(fetchOptions.body);
    expect(sentBody.user_id).toBe("jdoe");
    expect(sentBody.visible).toBe(true);
  });

  it("does not override user_id when body already has user_id", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    const req = makePatchRequest({ visible: false, user_id: "other-user" });
    await PATCH(req, makeContext("sess-456"));

    const [, fetchOptions] = mockFetch.mock.calls[0];
    const sentBody = JSON.parse(fetchOptions.body);
    expect(sentBody.user_id).toBe("other-user");
  });

  it("does not inject user_id when no session exists", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    const req = makePatchRequest({ visible: true });
    await PATCH(req, makeContext("sess-789"));

    const [, fetchOptions] = mockFetch.mock.calls[0];
    const sentBody = JSON.parse(fetchOptions.body);
    expect(sentBody.user_id).toBeUndefined();
  });

  // ── URL construction ────────────────────────────────────────────────────────

  it("URL-encodes the sessionId in the backend URL", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    const req = makePatchRequest({ visible: true });
    await PATCH(req, makeContext("sess/special&id"));

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain("sess%2Fspecial%26id");
    expect(calledUrl).toContain("/visibility");
  });

  // ── Successful response ─────────────────────────────────────────────────────

  it("returns the backend JSON response on success", async () => {
    const backendResponse = { session_id: "sess-123", visible: true };
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(backendResponse), { status: 200 })
    );

    const req = makePatchRequest({ visible: true });
    const response = await PATCH(req, makeContext("sess-123"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(backendResponse);
  });

  it("forwards PATCH method and correct headers to backend", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    const req = makePatchRequest({ visible: true });
    await PATCH(req, makeContext("sess-123"));

    const [, fetchOptions] = mockFetch.mock.calls[0];
    expect(fetchOptions.method).toBe("PATCH");
    expect(fetchOptions.headers["Content-Type"]).toBe("application/json");
    expect(fetchOptions.cache).toBe("no-store");
  });

  // ── Backend error handling ──────────────────────────────────────────────────

  it("returns error with backend status when backend responds with non-ok status", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response("Forbidden", { status: 403 })
    );

    const req = makePatchRequest({ visible: true });
    const response = await PATCH(req, makeContext("sess-123"));
    const body = await response.json();

    expect(response.status).toBe(403);
    expect(body.error).toBe("Failed");
  });

  it("returns 503 with Unavailable when fetch throws a network error", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

    const req = makePatchRequest({ visible: true });
    const response = await PATCH(req, makeContext("sess-123"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toBe("Unavailable");
  });

  it("returns error when backend returns 500", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response("Internal Server Error", { status: 500 })
    );

    const req = makePatchRequest({ visible: false });
    const response = await PATCH(req, makeContext("sess-123"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body.error).toBe("Failed");
  });
});
