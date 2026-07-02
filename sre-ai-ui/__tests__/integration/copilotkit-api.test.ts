/**
 * @jest-environment node
 *
 * Integration tests for src/app/api/copilotkit/route.ts
 *
 * Tests the POST handler directly without spinning up a real HTTP server.
 * Uses the `node` environment so that Web Fetch API globals (Request, Response,
 * Headers, NextRequest) are available.
 */

import { NextRequest } from "next/server";

// ─── Mock A2AAgent ────────────────────────────────────────────────────────────

jest.mock("@/lib/a2a-copilotkit-adapter", () => ({
  A2AAgent: jest.fn().mockImplementation(() => ({})),
}));

// ─── Mock auth-server ─────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
}));

// ─── Pull typed references after mocks are registered ─────────────────────────

import { A2AAgent } from "@/lib/a2a-copilotkit-adapter";
import { getSessionCookie } from "@/lib/auth-server";
import { copilotRuntimeNextJSAppRouterEndpoint } from "@copilotkit/runtime";

// ─── Import the handler under test ───────────────────────────────────────────

import { POST } from "@/app/api/copilotkit/route";

// ─── Typed mock references ────────────────────────────────────────────────────

const mockA2AAgent = A2AAgent as jest.MockedClass<typeof A2AAgent>;
const mockGetSessionCookie = getSessionCookie as jest.MockedFunction<typeof getSessionCookie>;
const mockCopilotRuntimeEndpoint = copilotRuntimeNextJSAppRouterEndpoint as jest.MockedFunction<
  typeof copilotRuntimeNextJSAppRouterEndpoint
>;

// ─── Session fixture ──────────────────────────────────────────────────────────

const SESSION_FIXTURE = {
  sub: "user-sub-001",
  name: "Jane Doe",
  email: "jane@example.com",
  loginId: "jdoe",
  user_type: "S",
  expires_at: Math.floor(Date.now() / 1000) + 3600,
};

// ─── Helper ───────────────────────────────────────────────────────────────────

function makeReq(headers: Record<string, string> = {}) {
  return new NextRequest("http://localhost:3000/api/copilotkit", {
    method: "POST",
    headers,
    body: "{}",
  });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("POST /api/copilotkit", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default: no session
    mockGetSessionCookie.mockResolvedValue(null as any);
  });

  // 1. copilotRuntimeNextJSAppRouterEndpoint is called with the correct endpoint
  it("calls copilotRuntimeNextJSAppRouterEndpoint with endpoint /api/copilotkit", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    await POST(makeReq());

    expect(mockCopilotRuntimeEndpoint).toHaveBeenCalledWith(
      expect.objectContaining({
        endpoint: "/api/copilotkit",
      })
    );
  });

  // 2. handleRequest is called with the original NextRequest
  it("calls handleRequest with the request object", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    // Retrieve the handleRequest mock from the return value of the endpoint factory
    const req = makeReq();
    await POST(req);

    // The global mock (jest.setup.ts) returns { handleRequest: jest.fn().mockResolvedValue(new Response("ok")) }
    const { handleRequest } = mockCopilotRuntimeEndpoint.mock.results[0].value;
    expect(handleRequest).toHaveBeenCalledWith(req);
  });

  // 3. x-agent-id header is read and passed to A2AAgent
  it("reads x-agent-id header and passes it to A2AAgent", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    await POST(makeReq({ "x-agent-id": "my-agent-42" }));

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({ agentId: "my-agent-42" })
    );
  });

  // 4. x-session-id header is read and passed to A2AAgent
  it("reads x-session-id header and passes it to A2AAgent", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    await POST(makeReq({ "x-session-id": "sess-xyz-789" }));

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: "sess-xyz-789" })
    );
  });

  // 5. userCtx is built from session cookie fields when session exists
  it("builds userCtx from session cookie when session exists", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE as any);

    await POST(
      makeReq({
        "user-agent": "Mozilla/5.0",
        "x-forwarded-for": "10.0.0.1, 10.0.0.2",
      })
    );

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({
        userCtx: expect.objectContaining({
          userId: SESSION_FIXTURE.loginId,
          userName: SESSION_FIXTURE.name,
          userType: SESSION_FIXTURE.user_type,
          loginId: SESSION_FIXTURE.loginId,
          accessToken: SESSION_FIXTURE.access_token,
          userAgent: "Mozilla/5.0",
          userIp: "10.0.0.1",
        }),
      })
    );
  });

  // 6. userCtx is undefined when there is no session
  it("passes undefined userCtx to A2AAgent when there is no session", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    await POST(makeReq());

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({ userCtx: undefined })
    );
  });

  // 7. Response from handleRequest is returned
  it("returns the response from handleRequest (body text is 'ok')", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    const response = await POST(makeReq());
    const text = await response.text();

    expect(text).toBe("ok");
  });

  // 8. agentId and sessionId are both forwarded to A2AAgent constructor
  it("passes agentId and sessionId together to A2AAgent constructor", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    await POST(
      makeReq({
        "x-agent-id": "agent-007",
        "x-session-id": "session-007",
      })
    );

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({
        agentId: "agent-007",
        sessionId: "session-007",
      })
    );
  });

  // Extra: missing headers result in undefined values (not the string "null")
  it("passes undefined for agentId/sessionId when headers are absent", async () => {
    mockGetSessionCookie.mockResolvedValue(null as any);

    await POST(makeReq({}));

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({
        agentId: undefined,
        sessionId: undefined,
      })
    );
  });

  // Extra: userIp falls back to x-real-ip when x-forwarded-for is absent
  it("uses x-real-ip as userIp when x-forwarded-for is not present", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE as any);

    await POST(makeReq({ "x-real-ip": "192.168.1.5" }));

    expect(mockA2AAgent).toHaveBeenCalledWith(
      expect.objectContaining({
        userCtx: expect.objectContaining({ userIp: "192.168.1.5" }),
      })
    );
  });
});
