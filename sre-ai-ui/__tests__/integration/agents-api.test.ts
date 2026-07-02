/**
 * @jest-environment node
 *
 * Integration tests for the agents API route.
 * Tests GET /api/agents handler function directly.
 *
 * Uses the `node` environment so that the Web Fetch API globals (Request,
 * Response, Headers) are available — these are provided by the Next.js runtime
 * but are not present in jest-environment-jsdom.
 */

// ─── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("@/lib/agents", () => ({
  loadAgents: jest.fn(),
}));

import { GET } from "@/app/api/agents/route";
import { loadAgents } from "@/lib/agents";

const mockLoadAgents = loadAgents as jest.MockedFunction<typeof loadAgents>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const AGENT_FIXTURE = {
  id: "test-agent",
  name: "Test Agent",
  url: "http://agent.example.com/a2a",
  emoji: "🤖",
  description: "A test agent",
};

// ─── GET /api/agents ──────────────────────────────────────────────────────────

describe("GET /api/agents", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  it("returns status 200", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    const response = await GET();

    expect(response.status).toBe(200);
  });

  it("returns JSON with an agents array containing the mocked agents", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    const response = await GET();
    const body = await response.json();

    expect(body).toHaveProperty("agents");
    expect(Array.isArray(body.agents)).toBe(true);
    expect(body.agents).toHaveLength(1);
    expect(body.agents[0]).toEqual(AGENT_FIXTURE);
  });

  it("includes the correct agent fields in the response", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    const response = await GET();
    const body = await response.json();

    expect(body.agents[0].id).toBe(AGENT_FIXTURE.id);
    expect(body.agents[0].name).toBe(AGENT_FIXTURE.name);
    expect(body.agents[0].url).toBe(AGENT_FIXTURE.url);
  });

  it("returns an empty agents array when loadAgents returns []", async () => {
    mockLoadAgents.mockReturnValue([]);

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ agents: [] });
  });

  it("returns all agents when multiple are configured", async () => {
    const agents = [
      AGENT_FIXTURE,
      { ...AGENT_FIXTURE, id: "agent-2", name: "Agent Two", url: "http://agent2.example.com/a2a" },
    ];
    mockLoadAgents.mockReturnValue(agents);

    const response = await GET();
    const body = await response.json();

    expect(body.agents).toHaveLength(2);
    expect(body.agents.map((a: { id: string }) => a.id)).toEqual(["test-agent", "agent-2"]);
  });

  it("calls loadAgents exactly once per request", async () => {
    mockLoadAgents.mockReturnValue([AGENT_FIXTURE]);

    await GET();

    expect(mockLoadAgents).toHaveBeenCalledTimes(1);
  });
});
