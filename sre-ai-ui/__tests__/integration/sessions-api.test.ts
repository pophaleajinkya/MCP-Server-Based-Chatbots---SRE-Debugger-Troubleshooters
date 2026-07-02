/**
 * @jest-environment node
 *
 * Integration tests for the sessions API route.
 * Tests GET /api/sessions handler directly.
 */

import { GET } from "@/app/api/sessions/route";
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

const SESSIONS_RESPONSE = {
  sessions: [
    { session_id: "sess-1", title: "First chat", last_update_time: 2000, user_id: "jdoe" },
    { session_id: "sess-2", title: "Second chat", last_update_time: 1000, user_id: "jdoe" },
  ],
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeGetRequest(url: string): NextRequest {
  return new NextRequest(url, { method: "GET" });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("GET /api/sessions", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetSessionCookie.mockReturnValue(null);
  });

  // ── Auth / userId resolution ────────────────────────────────────────────────

  it("returns 401 with empty sessions when no userId is available", async () => {
    const req = makeGetRequest("http://localhost:3000/api/sessions");
    const response = await GET(req);
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body.sessions).toEqual([]);
  });

  it("uses session cookie loginId as userId when authenticated", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(SESSIONS_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest("http://localhost:3000/api/sessions");
    await GET(req);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining(`user_id=${SESSION_FIXTURE.loginId}`),
      expect.any(Object)
    );
  });

  it("falls back to user_id query param when no session cookie exists", async () => {
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(SESSIONS_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest("http://localhost:3000/api/sessions?user_id=guest_user");
    await GET(req);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("user_id=guest_user"),
      expect.any(Object)
    );
  });

  it("prefers session cookie loginId over query param user_id", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(SESSIONS_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest("http://localhost:3000/api/sessions?user_id=other_user");
    await GET(req);

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain(`user_id=${SESSION_FIXTURE.loginId}`);
    expect(calledUrl).not.toContain("user_id=other_user");
  });

  // ── Successful response ────────────────────────────────────────────────────

  it("returns sessions array from the backend on success", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(SESSIONS_RESPONSE), { status: 200 })
    );

    const req = makeGetRequest("http://localhost:3000/api/sessions");
    const response = await GET(req);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.sessions).toHaveLength(2);
    expect(body.sessions[0].session_id).toBe("sess-1");
    expect(body.sessions[1].session_id).toBe("sess-2");
  });

  it("URL-encodes special characters in the userId query param", async () => {
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ sessions: [] }), { status: 200 })
    );

    const req = makeGetRequest("http://localhost:3000/api/sessions?user_id=user%40example.com");
    await GET(req);

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toContain("user_id=user%40example.com");
  });

  // ── Backend error handling ──────────────────────────────────────────────────

  it("returns empty sessions with backend status code when backend is not ok", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(new Response("Not Found", { status: 404 }));

    const req = makeGetRequest("http://localhost:3000/api/sessions");
    const response = await GET(req);
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.sessions).toEqual([]);
  });

  it("returns empty sessions with 200 when fetch throws a network error", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

    const req = makeGetRequest("http://localhost:3000/api/sessions");
    const response = await GET(req);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.sessions).toEqual([]);
  });

  it("returns empty sessions with 200 when backend returns 500", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response("Internal Server Error", { status: 500 })
    );

    const req = makeGetRequest("http://localhost:3000/api/sessions");
    const response = await GET(req);
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body.sessions).toEqual([]);
  });
});
