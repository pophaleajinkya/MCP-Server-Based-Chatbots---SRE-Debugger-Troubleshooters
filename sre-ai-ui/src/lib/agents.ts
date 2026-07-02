import type { AgentConfig } from "@/types";
import { createLogger } from "@/lib/logger";
const log = createLogger('agents.ts');

/**
 * Loads ADK agent configs from environment variables.
 * Primary source: ADK_AGENTS (JSON array)
 * Fallback: ADK_AGENT_URL (single legacy agent)
 */
export function loadAgents(): AgentConfig[] {
  const raw = process.env.ADK_AGENTS;

  if (raw) {
    try {
      const parsed = JSON.parse(raw) as AgentConfig[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.map((a) => ({
          id: a.id,
          name: a.name,
          url: a.url,
          emoji: a.emoji ?? "🤖",
          description: a.description ?? "",
        }));
      }
    } catch {
      log.error("[agents] Failed to parse ADK_AGENTS:", raw);
    }
  }

  const fallbackUrl = process.env.ADK_AGENT_URL ?? "https://maof-health-agent.dev.walmart.com/a2a";

  return [
    {
      id: "default",
      name: "ADK Agent",
      url: fallbackUrl,
      emoji: "🤖",
      description: "Default ADK agent",
    },
  ];
}
