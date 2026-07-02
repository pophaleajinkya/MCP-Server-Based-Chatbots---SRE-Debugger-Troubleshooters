/**
 * @jest-environment node
 *
 * Integration tests for the streaming chat API route.
 * Tests POST /api/chat/stream handler directly.
 *
 * Uses the `node` environment so Web Fetch API globals (NextRequest, Response)
 * are available — required for Next.js route handlers.
 */

import { POST } from "@/app/api/chat/stream/route";
import { NextRequest } from "next/server";
import type { AuthSession } from "@/lib/auth-server";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/agents", () => ({
  loadAgents: jest.fn(),
}));

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

import { loadAgents } from "@/lib/agents";
import { getSessionCookie } from "@/lib/auth-server";

const mockLoadAgents = loadAgents as jest.MockedFunction<typeof loadAgents>;
const mockGetSessionCookie = getSessionCookie as jest.MockedFunction<typeof getSessionCookie>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const AGENT_FIXTURE = {
  id: "test-agent",
  name: "Test Agent",
  url: "http://agent.example.com/a2a",
  emoji: "🤖",
  description: "A test agent",
};

const SESSION_FIXTURE: AuthSession = {
  sub: "user-sub-001",
  name: "Jane Doe",
  email: "jane.doe@example.com",
  loginId: "jdoe",
  user_type: "S",
  expires_at: Math.floor(Date.now() / 1000) + 10800,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makePostRequest(body: object, extraHeaders: Record<string, string> = {}): NextRequest {
  return new NextRequest("http://localhost:3000/api/chat/stream", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

function makeSSEStream(chunks: string[]): ReadableStream {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(new TextEncoder().encode(chunk));
      }
      controller.close();
    },
  });
}

function makeSuccessResponse(events: object[]): Response {
  const sseChunks = events.map((e) => `data: ${JSON.stringify(e)}\n\n`);
  return new Response(makeSSEStream(sseChunks), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function parseSSEError(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  const dataLine = text.trim().replace(/^data: /, "");
  return JSON.parse(dataLine);
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("POST /api/chat/stream", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);
    mockGetSessionCookie.mockReturnValue(null);
  });

  // ── Input validation ────────────────────────────────────────────────────────

  it("returns SSE error event when query is missing from body", async () => {
    const req = makePostRequest({ sessionId: "sess-1" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(response.headers.get("Content-Type")).toContain("text/event-stream");
    expect(event.type).toBe("error");
    expect(String(event.message)).toMatch(/query is required/i);
  });

  it("returns SSE error event when query is an empty string", async () => {
    const req = makePostRequest({ query: "" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(event.type).toBe("error");
    expect(String(event.message)).toMatch(/non-empty string/i);
  });

  it("returns SSE error event when query is whitespace only", async () => {
    const req = makePostRequest({ query: "   " });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(event.type).toBe("error");
    expect(String(event.message)).toMatch(/non-empty string/i);
  });

  it("returns SSE error event when no agents are configured", async () => {
    mockLoadAgents.mockReturnValue([]);
    const req = makePostRequest({ query: "hello" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(event.type).toBe("error");
    expect(String(event.message)).toMatch(/no agents configured/i);
  });

  // ── Stream URL derivation ───────────────────────────────────────────────────

  it("calls the /a2a/stream URL derived from the agent /a2a URL", async () => {
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));
    const req = makePostRequest({ query: "hello" });
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://agent.example.com/a2a/stream",
      expect.any(Object)
    );
  });

  it("uses the first agent when no agentId is specified", async () => {
    const secondAgent = { ...AGENT_FIXTURE, id: "agent-2", url: "http://agent2.example.com/a2a" };
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE, secondAgent]);
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));

    const req = makePostRequest({ query: "hello" });
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://agent.example.com/a2a/stream",
      expect.any(Object)
    );
  });

  it("selects matching agent when agentId is provided", async () => {
    const secondAgent = { ...AGENT_FIXTURE, id: "agent-2", url: "http://agent2.example.com/a2a" };
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE, secondAgent]);
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));

    const req = makePostRequest({ query: "hello", agentId: "agent-2" });
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://agent2.example.com/a2a/stream",
      expect.any(Object)
    );
  });

  it("falls back to first agent when agentId is not found", async () => {
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));
    const req = makePostRequest({ query: "hello", agentId: "ghost-agent" });
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://agent.example.com/a2a/stream",
      expect.any(Object)
    );
  });

  // ── Successful stream piping ────────────────────────────────────────────────

  it("returns response with text/event-stream Content-Type on success", async () => {
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "hi" }]));
    const req = makePostRequest({ query: "hi" });
    const response = await POST(req);

    expect(response.headers.get("Content-Type")).toContain("text/event-stream");
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
  });

  it("sets X-Accel-Buffering: no to prevent proxy buffering", async () => {
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));
    const req = makePostRequest({ query: "buffering test" });
    const response = await POST(req);

    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
  });

  // ── Backend error handling ──────────────────────────────────────────────────

  it("returns SSE error event when backend returns HTTP 500", async () => {
    mockFetch.mockResolvedValue(
      new Response("Internal Server Error", { status: 500, statusText: "Internal Server Error" })
    );
    const req = makePostRequest({ query: "fail" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(event.type).toBe("error");
    expect(String(event.message)).toMatch(/HTTP 500/);
  });

  it("includes a 5xx hint when backend returns HTTP 503", async () => {
    mockFetch.mockResolvedValue(
      new Response("", { status: 503, statusText: "Service Unavailable" })
    );
    const req = makePostRequest({ query: "fail" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(String(event.hint)).toMatch(/5xx error/i);
  });

  it("includes a 4xx hint when backend returns HTTP 404", async () => {
    mockFetch.mockResolvedValue(
      new Response("", { status: 404, statusText: "Not Found" })
    );
    const req = makePostRequest({ query: "missing" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(String(event.hint)).toMatch(/4xx error/i);
  });

  it("returns SSE error event with 'not reachable' hint on ECONNREFUSED", async () => {
    mockFetch.mockRejectedValue(new Error("connect ECONNREFUSED 127.0.0.1:8080"));
    const req = makePostRequest({ query: "network fail" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(event.type).toBe("error");
    expect(String(event.hint)).toMatch(/not reachable/i);
  });

  it("returns SSE error event with DNS hint on ENOTFOUND", async () => {
    mockFetch.mockRejectedValue(new Error("getaddrinfo ENOTFOUND bad.host.invalid"));
    const req = makePostRequest({ query: "dns fail" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(String(event.hint)).toMatch(/dns resolution failed/i);
  });

  it("includes agentId and agentName in SSE error payload when backend fails", async () => {
    mockFetch.mockResolvedValue(
      new Response("", { status: 502, statusText: "Bad Gateway" })
    );
    const req = makePostRequest({ query: "error test" });
    const response = await POST(req);
    const event = await parseSSEError(response);

    expect(event.agentId).toBe(AGENT_FIXTURE.id);
    expect(event.agentName).toBe(AGENT_FIXTURE.name);
  });

  // ── Session headers forwarding ──────────────────────────────────────────────

  it("does not include Authorization Bearer header", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));

    const req = makePostRequest({ query: "auth test" });
    await POST(req);

    const [, init] = mockFetch.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("includes loginId header when session exists", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));

    const req = makePostRequest({ query: "login test" });
    await POST(req);

    const [, init] = mockFetch.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["loginId"]).toBe(SESSION_FIXTURE.loginId);
  });

  it("includes user type and name headers when session exists", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));

    const req = makePostRequest({ query: "headers test" });
    await POST(req);

    const [, init] = mockFetch.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["wm_llm_gw.user_type"]).toBe(SESSION_FIXTURE.user_type);
    // user_name is the user identifier (loginId), not the display name
    expect(headers["wm_llm_gw.user_name"]).toBe(SESSION_FIXTURE.loginId);
  });

  it("does not include auth headers when no session exists", async () => {
    mockGetSessionCookie.mockReturnValue(null);
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));

    const req = makePostRequest({ query: "anon test" });
    await POST(req);

    const [, init] = mockFetch.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Authorization"]).toBeUndefined();
    expect(headers["loginId"]).toBeUndefined();
  });

  // ── Request body construction ───────────────────────────────────────────────

  it("sends jsonrpc 2.0 formatted body to the agent", async () => {
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));
    const req = makePostRequest({ query: "jsonrpc test", sessionId: "sess-abc" });
    await POST(req);

    const [, init] = mockFetch.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.jsonrpc).toBe("2.0");
    expect(body.method).toBe("message/stream");
    expect(body.params.message.role).toBe("user");
    expect(body.params.message.parts[0].text).toBe("jsonrpc test");
  });

  it("forwards sessionId to the agent request params", async () => {
    mockFetch.mockResolvedValue(makeSuccessResponse([{ type: "complete", text: "ok" }]));
    const req = makePostRequest({ query: "session test", sessionId: "my-session-123" });
    await POST(req);

    const [, init] = mockFetch.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.params.configuration.sessionId).toBe("my-session-123");
  });
});
