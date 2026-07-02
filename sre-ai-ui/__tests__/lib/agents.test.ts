import { loadAgents } from "@/lib/agents";

// ---------------------------------------------------------------------------
// Isolate process.env for each test
// ---------------------------------------------------------------------------

const originalEnv = process.env;

beforeEach(() => {
  process.env = { ...originalEnv };
});

afterEach(() => {
  process.env = originalEnv;
});

// ---------------------------------------------------------------------------
// loadAgents()
// ---------------------------------------------------------------------------

describe("loadAgents", () => {
  describe("ADK_AGENTS environment variable (valid JSON array)", () => {
    it("returns agents parsed from a valid ADK_AGENTS JSON array", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        { id: "agent-1", name: "First Agent", url: "https://first.example.com/a2a" },
      ]);

      const agents = loadAgents();

      expect(agents).toHaveLength(1);
      expect(agents[0].id).toBe("agent-1");
      expect(agents[0].name).toBe("First Agent");
      expect(agents[0].url).toBe("https://first.example.com/a2a");
    });

    it("returns all agents when multiple entries are provided", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        { id: "a1", name: "Agent One", url: "https://one.example.com/a2a" },
        { id: "a2", name: "Agent Two", url: "https://two.example.com/a2a" },
        { id: "a3", name: "Agent Three", url: "https://three.example.com/a2a" },
      ]);

      const agents = loadAgents();

      expect(agents).toHaveLength(3);
    });

    it("preserves the id, name, and url fields exactly as parsed", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        {
          id: "my-agent",
          name: "My Agent",
          url: "https://custom.example.com/a2a",
          emoji: "🦾",
          description: "A custom agent",
        },
      ]);

      const agents = loadAgents();

      expect(agents[0].id).toBe("my-agent");
      expect(agents[0].name).toBe("My Agent");
      expect(agents[0].url).toBe("https://custom.example.com/a2a");
    });
  });

  describe("default emoji when not provided", () => {
    it("assigns the default emoji '🤖' to each agent that has no emoji", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        { id: "a1", name: "Agent One", url: "https://one.example.com/a2a" },
        { id: "a2", name: "Agent Two", url: "https://two.example.com/a2a" },
      ]);

      const agents = loadAgents();

      expect(agents[0].emoji).toBe("🤖");
      expect(agents[1].emoji).toBe("🤖");
    });

    it("keeps the emoji provided in ADK_AGENTS when present", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        { id: "a1", name: "Agent One", url: "https://one.example.com/a2a", emoji: "🚀" },
      ]);

      const agents = loadAgents();

      expect(agents[0].emoji).toBe("🚀");
    });
  });

  describe("default description when not provided", () => {
    it("assigns an empty string description to each agent that omits it", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        { id: "a1", name: "Agent One", url: "https://one.example.com/a2a" },
      ]);

      const agents = loadAgents();

      expect(agents[0].description).toBe("");
    });

    it("keeps the description provided in ADK_AGENTS when present", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        {
          id: "a1",
          name: "Agent One",
          url: "https://one.example.com/a2a",
          description: "Handles health queries",
        },
      ]);

      const agents = loadAgents();

      expect(agents[0].description).toBe("Handles health queries");
    });
  });

  describe("fallback to ADK_AGENT_URL when ADK_AGENTS is unset", () => {
    it("returns a single default agent using ADK_AGENT_URL when ADK_AGENTS is absent", () => {
      delete process.env.ADK_AGENTS;
      process.env.ADK_AGENT_URL = "https://custom-fallback.example.com/a2a";

      const agents = loadAgents();

      expect(agents).toHaveLength(1);
      expect(agents[0].url).toBe("https://custom-fallback.example.com/a2a");
    });

    it("returns the default agent with id 'default' and name 'ADK Agent'", () => {
      delete process.env.ADK_AGENTS;
      process.env.ADK_AGENT_URL = "https://custom-fallback.example.com/a2a";

      const agents = loadAgents();

      expect(agents[0].id).toBe("default");
      expect(agents[0].name).toBe("ADK Agent");
    });
  });

  describe("fallback to hardcoded default URL when both env vars are unset", () => {
    it("uses the hardcoded URL when neither ADK_AGENTS nor ADK_AGENT_URL is set", () => {
      delete process.env.ADK_AGENTS;
      delete process.env.ADK_AGENT_URL;

      const agents = loadAgents();

      expect(agents).toHaveLength(1);
      expect(agents[0].url).toBe(
        "https://maof-health-agent.dev.walmart.com/a2a"
      );
    });

    it("returns a single agent with the default id and name", () => {
      delete process.env.ADK_AGENTS;
      delete process.env.ADK_AGENT_URL;

      const agents = loadAgents();

      expect(agents[0].id).toBe("default");
      expect(agents[0].name).toBe("ADK Agent");
      expect(agents[0].emoji).toBe("🤖");
      expect(agents[0].description).toBe("Default ADK agent");
    });
  });

  describe("invalid JSON in ADK_AGENTS", () => {
    it("falls back to a single default agent when ADK_AGENTS is not valid JSON", () => {
      process.env.ADK_AGENTS = "not-valid-json{{";
      delete process.env.ADK_AGENT_URL;

      const agents = loadAgents();

      expect(agents).toHaveLength(1);
      expect(agents[0].id).toBe("default");
    });

    it("uses the hardcoded default URL after a JSON parse failure", () => {
      process.env.ADK_AGENTS = "{broken";
      delete process.env.ADK_AGENT_URL;

      const agents = loadAgents();

      expect(agents[0].url).toBe(
        "https://maof-health-agent.dev.walmart.com/a2a"
      );
    });

    it("uses ADK_AGENT_URL as the fallback URL after a JSON parse failure", () => {
      process.env.ADK_AGENTS = "not-json";
      process.env.ADK_AGENT_URL = "https://fallback.example.com/a2a";

      const agents = loadAgents();

      expect(agents[0].url).toBe("https://fallback.example.com/a2a");
    });

    it("falls back when ADK_AGENTS is a valid JSON scalar (not an array)", () => {
      process.env.ADK_AGENTS = JSON.stringify({ id: "a", name: "A", url: "https://a.com" });
      delete process.env.ADK_AGENT_URL;

      const agents = loadAgents();

      // An object is not an array, so the fallback path is taken
      expect(agents).toHaveLength(1);
      expect(agents[0].id).toBe("default");
    });

    it("falls back when ADK_AGENTS is a valid JSON empty array", () => {
      process.env.ADK_AGENTS = "[]";
      delete process.env.ADK_AGENT_URL;

      const agents = loadAgents();

      // Empty array has length 0 so the guard `parsed.length > 0` is false
      expect(agents).toHaveLength(1);
      expect(agents[0].id).toBe("default");
    });
  });

  describe("first agent correctness in a parsed array", () => {
    it("returns the first agent with the correct id, name, and url", () => {
      process.env.ADK_AGENTS = JSON.stringify([
        {
          id: "health-agent",
          name: "Health Agent",
          url: "https://health.example.com/a2a",
        },
        {
          id: "finance-agent",
          name: "Finance Agent",
          url: "https://finance.example.com/a2a",
        },
      ]);

      const agents = loadAgents();

      expect(agents[0].id).toBe("health-agent");
      expect(agents[0].name).toBe("Health Agent");
      expect(agents[0].url).toBe("https://health.example.com/a2a");
    });
  });
});
