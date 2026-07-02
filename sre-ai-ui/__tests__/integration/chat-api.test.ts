/**
 * @jest-environment node
 *
 * Integration tests for the chat API route.
 * Tests POST /api/chat and GET /api/chat handler functions directly.
 *
 * Uses the `node` environment so that the Web Fetch API globals (Request,
 * Response, Headers, NextRequest) are available — these are provided by the
 * Next.js runtime but are not present in jest-environment-jsdom.
 */

import { POST, GET } from "@/app/api/chat/route";
import { NextRequest } from "next/server";
import type { A2ATask } from "@/types";
import type { AuthSession } from "@/lib/auth-server";

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/a2a-client", () => ({
  sendA2AQuery: jest.fn(),
  extractTaskText: jest.fn(),
}));

jest.mock("@/lib/agents", () => ({
  loadAgents: jest.fn(),
}));

jest.mock("@/lib/auth-server", () => ({
  getSessionCookie: jest.fn(),
  SESSION_COOKIE: "sre_ai_session",
}));

import { sendA2AQuery, extractTaskText } from "@/lib/a2a-client";
import { loadAgents } from "@/lib/agents";
import { getSessionCookie } from "@/lib/auth-server";

const mockSendA2AQuery = sendA2AQuery as jest.MockedFunction<typeof sendA2AQuery>;
const mockExtractTaskText = extractTaskText as jest.MockedFunction<typeof extractTaskText>;
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

const COMPLETED_TASK: A2ATask = {
  id: "task-001",
  status: {
    state: "completed",
    message: {
      role: "agent",
      parts: [{ type: "text", text: "Here is the answer." }],
    },
  },
};

const FAILED_TASK: A2ATask = {
  id: "task-002",
  status: {
    state: "failed",
    message: {
      role: "agent",
      parts: [{ type: "text", text: "Something went wrong." }],
    },
  },
};

const SESSION_FIXTURE: AuthSession = {
  sub: "user-sub-001",
  name: "Jane Doe",
  email: "jane.doe@example.com",
  loginId: "jdoe",
  user_type: "S",
  expires_at: Math.floor(Date.now() / 1000) + 10800,
};

// ─── Helper ───────────────────────────────────────────────────────────────────

function makePostRequest(body: object): NextRequest {
  return new NextRequest("http://localhost:3000/api/chat", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

// ─── POST /api/chat ───────────────────────────────────────────────────────────

describe("POST /api/chat", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    // Default: one agent configured, no active session
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);
    mockGetSessionCookie.mockReturnValue(null);
    mockExtractTaskText.mockReturnValue("Here is the answer.");
    mockSendA2AQuery.mockResolvedValue(COMPLETED_TASK);
  });

  // ── Input validation ────────────────────────────────────────────────────────

  it("returns 400 when query field is missing from the request body", async () => {
    const req = makePostRequest({ sessionId: "sess-1" });

    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toMatch(/query is required/i);
  });

  it("returns 400 when query is an empty string", async () => {
    const req = makePostRequest({ query: "" });

    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toMatch(/non-empty string/i);
  });

  it("returns 400 when query is a whitespace-only string", async () => {
    const req = makePostRequest({ query: "   " });

    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toMatch(/non-empty string/i);
  });

  it("returns 400 when query exceeds 4000 characters", async () => {
    const req = makePostRequest({ query: "a".repeat(4001) });

    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toMatch(/exceeds maximum length/i);
  });

  it("accepts a query of exactly 4000 characters", async () => {
    const req = makePostRequest({ query: "a".repeat(4000) });

    const response = await POST(req);

    expect(response.status).toBe(200);
  });

  // ── Agent resolution ────────────────────────────────────────────────────────

  it("returns 503 when no agents are configured", async () => {
    mockLoadAgents.mockReturnValue([]);

    const req = makePostRequest({ query: "Hello" });
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toMatch(/no agents configured/i);
  });

  // ── Successful response ─────────────────────────────────────────────────────

  it("returns 200 with text, agentId, and agentName on a successful query", async () => {
    const req = makePostRequest({ query: "What is 2+2?" });

    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toHaveProperty("text", "Here is the answer.");
    expect(body).toHaveProperty("agentId", AGENT_FIXTURE.id);
    expect(body).toHaveProperty("agentName", AGENT_FIXTURE.name);
  });

  it("includes the agentUrl in the success response", async () => {
    const req = makePostRequest({ query: "ping" });

    const response = await POST(req);
    const body = await response.json();

    expect(body).toHaveProperty("agentUrl", AGENT_FIXTURE.url);
  });

  it("includes the full task object in the success response", async () => {
    const req = makePostRequest({ query: "ping" });

    const response = await POST(req);
    const body = await response.json();

    expect(body).toHaveProperty("task");
    expect(body.task.id).toBe(COMPLETED_TASK.id);
    expect(body.task.status.state).toBe("completed");
  });

  // ── Failed task ─────────────────────────────────────────────────────────────

  it("returns 502 with structured error detail when the agent task state is 'failed'", async () => {
    mockSendA2AQuery.mockResolvedValue(FAILED_TASK);

    const req = makePostRequest({ query: "trigger a failure" });
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error).toMatch(/agent task failed/i);
    expect(body.agentId).toBe(AGENT_FIXTURE.id);
    expect(body.agentName).toBe(AGENT_FIXTURE.name);
    expect(body.taskState).toBe("failed");
  });

  it("includes a 'hint' in the 502 response for a failed task", async () => {
    mockSendA2AQuery.mockResolvedValue(FAILED_TASK);

    const req = makePostRequest({ query: "fail" });
    const response = await POST(req);
    const body = await response.json();

    expect(body).toHaveProperty("hint");
    expect(typeof body.hint).toBe("string");
    expect(body.hint.length).toBeGreaterThan(0);
  });

  // ── Network / throw errors ──────────────────────────────────────────────────

  it("returns 502 with a hint when sendA2AQuery throws a network error (ECONNREFUSED)", async () => {
    mockSendA2AQuery.mockRejectedValue(new Error("connect ECONNREFUSED 127.0.0.1:8080"));

    const req = makePostRequest({ query: "network fail" });
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toHaveProperty("hint");
    expect(body.hint).toMatch(/not reachable/i);
  });

  it("returns 502 with a hint when sendA2AQuery throws a timeout error", async () => {
    mockSendA2AQuery.mockRejectedValue(new Error("Request timed out after 60 seconds"));

    const req = makePostRequest({ query: "slow query" });
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toHaveProperty("hint");
    expect(body.hint).toMatch(/timed out/i);
  });

  it("returns 502 with a hint when sendA2AQuery throws a DNS resolution error", async () => {
    mockSendA2AQuery.mockRejectedValue(new Error("getaddrinfo ENOTFOUND agent.bad-host.invalid"));

    const req = makePostRequest({ query: "dns fail" });
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.hint).toMatch(/dns resolution failed/i);
  });

  it("returns 502 and includes the error message on unexpected throw", async () => {
    mockSendA2AQuery.mockRejectedValue(new Error("Unexpected agent meltdown"));

    const req = makePostRequest({ query: "kaboom" });
    const response = await POST(req);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error).toBe("Unexpected agent meltdown");
  });

  // ── sessionId forwarding ────────────────────────────────────────────────────

  it("passes sessionId to sendA2AQuery when provided in the request body", async () => {
    const req = makePostRequest({ query: "Hello", sessionId: "sess-abc-123" });

    await POST(req);

    expect(mockSendA2AQuery).toHaveBeenCalledWith(
      AGENT_FIXTURE.url,
      "Hello",
      "sess-abc-123",
      undefined // no session cookie → userCtx is undefined
    );
  });

  it("passes undefined sessionId to sendA2AQuery when not provided", async () => {
    const req = makePostRequest({ query: "Hello" });

    await POST(req);

    expect(mockSendA2AQuery).toHaveBeenCalledWith(
      AGENT_FIXTURE.url,
      "Hello",
      undefined,
      undefined
    );
  });

  // ── userCtx from session cookie ──────────────────────────────────────────────

  it("passes a userCtx containing loginId and userType when a session cookie exists", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const req = makePostRequest({ query: "who am I?" });

    await POST(req);

    expect(mockSendA2AQuery).toHaveBeenCalledTimes(1);
    const [, , , userCtx] = mockSendA2AQuery.mock.calls[0];

    expect(userCtx).toBeDefined();
    expect(userCtx!.loginId).toBe(SESSION_FIXTURE.loginId);
    expect(userCtx!.userType).toBe(SESSION_FIXTURE.user_type);
  });

  it("passes userCtx with userId matching the session loginId", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const req = makePostRequest({ query: "user test" });
    await POST(req);

    const [, , , userCtx] = mockSendA2AQuery.mock.calls[0];
    expect(userCtx!.userId).toBe(SESSION_FIXTURE.loginId);
  });

  it("passes userCtx with userName matching the session name", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const req = makePostRequest({ query: "name test" });
    await POST(req);

    const [, , , userCtx] = mockSendA2AQuery.mock.calls[0];
    expect(userCtx!.userName).toBe(SESSION_FIXTURE.name);
  });

  it("passes userCtx with accessToken from the session", async () => {
    mockGetSessionCookie.mockReturnValue(SESSION_FIXTURE);

    const req = makePostRequest({ query: "token test" });
    await POST(req);

    const [, , , userCtx] = mockSendA2AQuery.mock.calls[0];
    expect(userCtx!.accessToken).toBe(SESSION_FIXTURE.access_token);
  });

  it("passes undefined userCtx when no session cookie is present", async () => {
    mockGetSessionCookie.mockReturnValue(null);

    const req = makePostRequest({ query: "anonymous query" });

    await POST(req);

    const [, , , userCtx] = mockSendA2AQuery.mock.calls[0];
    expect(userCtx).toBeUndefined();
  });

  // ── agentId selection ────────────────────────────────────────────────────────

  it("uses the first agent when no agentId is specified in the request body", async () => {
    const secondAgent = { ...AGENT_FIXTURE, id: "second-agent", name: "Second Agent" };
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE, secondAgent]);

    const req = makePostRequest({ query: "pick default" });
    await POST(req);

    const [calledUrl] = mockSendA2AQuery.mock.calls[0];
    expect(calledUrl).toBe(AGENT_FIXTURE.url);
  });

  it("selects the matching agent when agentId is specified", async () => {
    const secondAgent = {
      ...AGENT_FIXTURE,
      id: "second-agent",
      name: "Second Agent",
      url: "http://second-agent.example.com/a2a",
    };
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE, secondAgent]);

    const req = makePostRequest({ query: "specific agent", agentId: "second-agent" });
    await POST(req);

    const [calledUrl] = mockSendA2AQuery.mock.calls[0];
    expect(calledUrl).toBe(secondAgent.url);
  });

  it("falls back to the first agent when the specified agentId is not found", async () => {
    const req = makePostRequest({ query: "unknown agent", agentId: "ghost-agent" });

    await POST(req);

    const [calledUrl] = mockSendA2AQuery.mock.calls[0];
    expect(calledUrl).toBe(AGENT_FIXTURE.url);
  });

  // ── query trimming ───────────────────────────────────────────────────────────

  it("trims whitespace from the query before forwarding to sendA2AQuery", async () => {
    const req = makePostRequest({ query: "  trimmed query  " });

    await POST(req);

    const [, sentText] = mockSendA2AQuery.mock.calls[0];
    expect(sentText).toBe("trimmed query");
  });
});

// ─── GET /api/chat ────────────────────────────────────────────────────────────

describe("GET /api/chat", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  it("returns status 200", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    const response = await GET();

    expect(response.status).toBe(200);
  });

  it("returns { status: 'ok', agents: [...] } with the configured agents", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    const response = await GET();
    const body = await response.json();

    expect(body.status).toBe("ok");
    expect(Array.isArray(body.agents)).toBe(true);
    expect(body.agents).toHaveLength(1);
    expect(body.agents[0].id).toBe(AGENT_FIXTURE.id);
    expect(body.agents[0].name).toBe(AGENT_FIXTURE.name);
    expect(body.agents[0].url).toBe(AGENT_FIXTURE.url);
  });

  it("includes the protocol field in the response", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    const response = await GET();
    const body = await response.json();

    expect(body).toHaveProperty("protocol");
    expect(typeof body.protocol).toBe("string");
  });

  it("returns an empty agents array when no agents are configured", async () => {
    mockLoadAgents.mockReturnValue([]);

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.status).toBe("ok");
    expect(body.agents).toEqual([]);
  });

  it("returns all agents when multiple are configured", async () => {
    const agents = [
      AGENT_FIXTURE,
      { ...AGENT_FIXTURE, id: "agent-2", name: "Agent Two", url: "http://agent2.example.com/a2a" },
      { ...AGENT_FIXTURE, id: "agent-3", name: "Agent Three", url: "http://agent3.example.com/a2a" },
    ];
    mockLoadAgents.mockReturnValue(agents);

    const response = await GET();
    const body = await response.json();

    expect(body.agents).toHaveLength(3);
    expect(body.agents.map((a: { id: string }) => a.id)).toEqual(["test-agent", "agent-2", "agent-3"]);
  });
});
