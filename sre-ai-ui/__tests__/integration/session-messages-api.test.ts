/**
 * @jest-environment node
 *
 * Integration tests for GET /api/sessions/[sessionId]/messages
 *
 * Tests the route handler directly without an HTTP server.
 * Mocks:
 *   - @/lib/auth-server (getSessionCookie)
 *   - global.fetch
 */

import { GET } from "@/app/api/sessions/[sessionId]/messages/route";
import { NextRequest } from "next/server";
import type { AuthSession } from "@/lib/auth-server";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
  SESSION_COOKIE: "sre_ai_session",
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

const SESSION_ID = "sess-abc-123";

const MESSAGES_RESPONSE = {
  session_id: SESSION_ID,
  messages: [
    { role: "user", content: "Hello", timestamp: 1000 },
    { role: "assistant", content: "Hi there!", timestamp: 2000 },
  ],
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeGetRequest(sessionId: string, searchParams?: string): NextRequest {
  const url = searchParams
    ? `http://localhost:3000/api/sessions/${sessionId}/messages?${searchParams}`
    : `http://localhost:3000/api/sessions/${sessionId}/messages`;
  return new NextRequest(url, { method: "GET" });
}

/** Builds the params object that Next.js passes to the route handler. */
function makeParams(sessionId: string): { params: Promise<{ sessionId: string }> } {
  return { params: Promise.resolve({ sessionId }) };
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("GET /api/sessions/[sessionId]/messages", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default: no session cookie, no user_id query param
    mockGetSessionCookie.mockResolvedValue(null);
  });

  // ── Auth / userId resolution ───────────────────────────────────────────────

  it("returns 401 with empty messages when there is no session and no user_id query param", async () => {
    const req = makeGetRequest(SESSION_ID);
    const response = await GET(req, makeParams(SESSION_ID));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body.session_id).toBe(SESSION_ID);
    expect(body.messages).toEqual([]);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("returns 401 when no session and no user_id even with a different URL format", async () => {
    // Ensure we test an alternative sessionId to confirm the returned session_id is correct
    const altSessionId = "other-session-xyz";
    const req = makeGetRequest(altSessionId);
    const response = await GET(req, makeParams(altSessionId));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body.session_id).toBe(altSessionId);
    expect(body.messages).toEqual([]);
  });

  it("uses session.loginId as userId when a session cookie exists", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(MESSAGES_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest(SESSION_ID);
    await GET(req, makeParams(SESSION_ID));

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain(`user_id=${SESSION_FIXTURE.loginId}`);
  });

  it("uses the user_id query param when no session cookie exists", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(MESSAGES_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest(SESSION_ID, "user_id=guest_user");
    await GET(req, makeParams(SESSION_ID));

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain("user_id=guest_user");
  });

  // ── Successful fetch ───────────────────────────────────────────────────────

  it("returns 200 with the messages from the backend on a successful fetch", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(MESSAGES_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest(SESSION_ID);
    const response = await GET(req, makeParams(SESSION_ID));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.session_id).toBe(SESSION_ID);
    expect(body.messages).toHaveLength(2);
    expect(body.messages[0]).toMatchObject({ role: "user", content: "Hello" });
    expect(body.messages[1]).toMatchObject({ role: "assistant", content: "Hi there!" });
  });

  // ── Non-ok fetch responses ─────────────────────────────────────────────────

  it("returns 404 with empty messages when the backend fetch returns 404", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(new Response("Not Found", { status: 404 }));

    const req = makeGetRequest(SESSION_ID);
    const response = await GET(req, makeParams(SESSION_ID));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.session_id).toBe(SESSION_ID);
    expect(body.messages).toEqual([]);
  });

  it("returns 500 with empty messages when the backend fetch returns 500", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(new Response("Internal Server Error", { status: 500 }));

    const req = makeGetRequest(SESSION_ID);
    const response = await GET(req, makeParams(SESSION_ID));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body.session_id).toBe(SESSION_ID);
    expect(body.messages).toEqual([]);
  });

  // ── Network error (fetch throws) ───────────────────────────────────────────

  it("returns 200 with empty messages when fetch throws a network error", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

    const req = makeGetRequest(SESSION_ID);
    const response = await GET(req, makeParams(SESSION_ID));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.session_id).toBe(SESSION_ID);
    expect(body.messages).toEqual([]);
  });

  // ── URL encoding ──────────────────────────────────────────────────────────

  it("URL-encodes the sessionId in the backend fetch URL", async () => {
    const specialSessionId = "sess/with spaces&special=chars";
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ session_id: specialSessionId, messages: [] }), { status: 200 })
    );

    const req = makeGetRequest(encodeURIComponent(specialSessionId));
    await GET(req, makeParams(specialSessionId));

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain(encodeURIComponent(specialSessionId));
  });

  it("URL-encodes the userId in the backend fetch URL", async () => {
    const specialUserId = "user@example.com";
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(MESSAGES_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest(SESSION_ID, `user_id=${encodeURIComponent(specialUserId)}`);
    await GET(req, makeParams(SESSION_ID));

    const [calledUrl] = mockFetch.mock.calls[0];
    // encodeURIComponent("user@example.com") === "user%40example.com"
    expect(calledUrl).toContain("user_id=user%40example.com");
  });

  it("constructs the fetch URL with both sessionId and userId correctly", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(MESSAGES_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest(SESSION_ID);
    await GET(req, makeParams(SESSION_ID));

    const [calledUrl, fetchOptions] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain(`/sessions/${encodeURIComponent(SESSION_ID)}/messages`);
    expect(calledUrl).toContain(`user_id=${encodeURIComponent(SESSION_FIXTURE.loginId)}`);
    expect(fetchOptions).toMatchObject({ cache: "no-store" });
  });
});
