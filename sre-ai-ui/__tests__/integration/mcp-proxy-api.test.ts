/**
 * @jest-environment node
 *
 * Integration tests for the MCP proxy API route.
 * Tests POST /api/mcp-proxy handler directly.
 */

import { POST } from "@/app/api/mcp-proxy/route";
import { NextRequest } from "next/server";
import type { AuthSession } from "@/lib/auth-server";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
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

const JSON_RPC_BODY = {
  jsonrpc: "2.0",
  method: "tools/list",
  id: 1,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makePostRequest(body: unknown): NextRequest {
  return new NextRequest("http://localhost:3000/api/mcp-proxy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("POST /api/mcp-proxy", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.clearAllMocks();
    mockGetSessionCookie.mockResolvedValue(null);
    process.env = { ...originalEnv };
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  // ── URL resolution ──────────────────────────────────────────────────────────

  it("uses ADK_AGENT_BASE_URL when set", async () => {
    process.env.ADK_AGENT_BASE_URL = "https://custom-backend:9000";
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ result: [] }), { status: 200 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "https://custom-backend:9000/mcp-proxy",
      expect.any(Object)
    );
  });

  it("falls back to ADK_AGENT_URL with /a2a stripped when ADK_AGENT_BASE_URL is not set", async () => {
    delete process.env.ADK_AGENT_BASE_URL;
    process.env.ADK_AGENT_URL = "http://agent-host:8001/a2a";
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ result: [] }), { status: 200 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://agent-host:8001/mcp-proxy",
      expect.any(Object)
    );
  });

  it("falls back to localhost:8001 when no env vars are set", async () => {
    delete process.env.ADK_AGENT_BASE_URL;
    delete process.env.ADK_AGENT_URL;
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ result: [] }), { status: 200 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    await POST(req);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8001/mcp-proxy",
      expect.any(Object)
    );
  });

  // ── Auth headers ────────────────────────────────────────────────────────────

  it("sends loginId header when session has loginId", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ result: "ok" }), { status: 200 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    await POST(req);

    const [, fetchOptions] = mockFetch.mock.calls[0];
    expect(fetchOptions.headers["loginId"]).toBe("jdoe");
  });

  it("does not send Authorization or loginId headers when no session", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ result: "ok" }), { status: 200 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    await POST(req);

    const [, fetchOptions] = mockFetch.mock.calls[0];
    expect(fetchOptions.headers["loginId"]).toBeUndefined();
    expect(fetchOptions.headers["Content-Type"]).toBe("application/json");
  });

  // ── Successful proxying ─────────────────────────────────────────────────────

  it("proxies the JSON-RPC body and returns backend response", async () => {
    const backendResponse = { jsonrpc: "2.0", result: ["tool1", "tool2"], id: 1 };
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify(backendResponse), { status: 200 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(backendResponse);

    // Verify the body was forwarded
    const [, fetchOptions] = mockFetch.mock.calls[0];
    expect(fetchOptions.method).toBe("POST");
    expect(JSON.parse(fetchOptions.body)).toEqual(JSON_RPC_BODY);
  });

  it("returns the backend status code when backend responds with non-200", async () => {
    mockGetSessionCookie.mockResolvedValue(null);
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ error: "not found" }), { status: 404 })
    );

    const req = makePostRequest(JSON_RPC_BODY);
    const response = await POST(req);

    expect(response.status).toBe(404);
  });

  // ── Error handling ──────────────────────────────────────────────────────────

  it("returns 502 with error message when fetch throws a network error", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

    const req = makePostRequest(JSON_RPC_BODY);
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error).toBe("MCP proxy error: ECONNREFUSED");
  });

  it("returns 502 with stringified error when a non-Error is thrown", async () => {
    mockGetSessionCookie.mockResolvedValue(SESSION_FIXTURE);
    mockFetch.mockRejectedValue("unexpected failure");

    const req = makePostRequest(JSON_RPC_BODY);
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error).toBe("MCP proxy error: unexpected failure");
  });

  it("returns 502 when req.json() fails (invalid JSON body)", async () => {
    const req = new NextRequest("http://localhost:3000/api/mcp-proxy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not-valid-json",
    });

    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error).toContain("MCP proxy error:");
  });
});
