"""A2A remote subagent registry package.

Provides:
  A2AAgentConfig  — dataclass describing a single remote A2A subagent
  load_a2a_agents — loads subagent list from Redis key or local YAML file
  fetch_agent_card — fetches /.well-known/agent.json from a remote A2A agent
"""

from app.a2a.client import A2AAgentConfig, load_a2a_agents, fetch_agent_card

__all__ = ["A2AAgentConfig", "load_a2a_agents", "fetch_agent_card"]
