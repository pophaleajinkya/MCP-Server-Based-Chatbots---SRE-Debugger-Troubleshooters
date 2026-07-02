"""Unit tests for src/mcp_server/resources_and_prompts.py

Tests verify:
  - agent_guide resource returns a non-empty string with required sections
  - trace_wcnp_app prompt interpolates app_name and namespace correctly
  - trace_oneops_app prompt interpolates org, platform, assembly correctly
  - prompts include multi-step instructions (numbered steps)
  - prompts reference the correct tool names
"""
import pytest

from src.mcp_server.resources_and_prompts import (
    agent_guide,
    trace_wcnp_app,
    trace_oneops_app,
)


# ─── agent_guide resource ─────────────────────────────────────────────────────

class TestAgentGuideResource:
    """Tests for the dependency://agent-guide resource."""

    def test_returns_non_empty_string(self):
        """Resource must return a non-empty string."""
        result = agent_guide()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_wcnp_section(self):
        """Guide must cover WCNP platform routing."""
        result = agent_guide()
        assert "WCNP" in result or "Kubernetes" in result

    def test_contains_oneops_section(self):
        """Guide must cover OneOps platform routing."""
        result = agent_guide()
        assert "OneOps" in result

    def test_contains_managed_services_section(self):
        """Guide must cover all 4 managed service types."""
        result = agent_guide()
        assert "Cassandra" in result
        assert "MeghaCache" in result
        assert "Cosmos" in result
        assert "SQL Server" in result or "sqlserver" in result.lower()

    def test_contains_upstream_and_downstream_directions(self):
        """Guide must explain both upstream and downstream directions."""
        result = agent_guide()
        assert "upstream" in result.lower()
        assert "downstream" in result.lower()

    def test_contains_tool_names_for_wcnp(self):
        """Guide must name the exact WCNP tool names the LLM should call."""
        result = agent_guide()
        assert "fetch_wcnp_upstream_dependencies" in result
        assert "fetch_wcnp_downstream_dependencies" in result
        assert "list_apps_in_namespace" in result

    def test_contains_tool_names_for_oneops(self):
        """Guide must name the exact OneOps tool names the LLM should call."""
        result = agent_guide()
        assert "fetch_oneops_upstream_dependencies" in result
        assert "fetch_oneops_downstream_dependencies" in result

    def test_contains_tool_names_for_managed_services(self):
        """Guide must name the exact managed service tool names."""
        result = agent_guide()
        assert "fetch_cassandra_upstream_dependencies" in result
        assert "fetch_meghacache_upstream_dependencies" in result
        assert "fetch_cosmos_upstream_dependencies" in result
        assert "fetch_sqlserver_upstream_dependencies" in result

    def test_contains_decision_tree(self):
        """Guide must contain a decision tree section."""
        result = agent_guide()
        assert "Decision tree" in result or "decision tree" in result.lower()

    def test_guide_is_idempotent(self):
        """Calling agent_guide() multiple times must return identical content."""
        assert agent_guide() == agent_guide()

    def test_guide_explains_namespace_only_flow(self):
        """Guide must mention the namespace-only → list_apps step."""
        result = agent_guide()
        assert "list_apps_in_namespace" in result
        # Should explain what to do when only namespace is known
        assert "namespace" in result.lower()


# ─── trace_wcnp_app prompt ───────────────────────────────────────────────────

class TestTraceWcnpAppPrompt:
    """Tests for the trace_wcnp_app prompt."""

    def test_returns_non_empty_string(self):
        result = trace_wcnp_app("iro-prod", "item-assembler-async")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_interpolates_app_name(self):
        """app_name must appear in the prompt text."""
        result = trace_wcnp_app("payment-service", "payments-prod")
        assert "payment-service" in result

    def test_interpolates_namespace(self):
        """namespace must appear in the prompt text."""
        result = trace_wcnp_app("payment-service", "payments-prod")
        assert "payments-prod" in result

    def test_references_upstream_tool(self):
        """Prompt must instruct the LLM to call the upstream tool."""
        result = trace_wcnp_app("my-app", "my-ns")
        assert "fetch_wcnp_upstream_dependencies" in result

    def test_references_downstream_tool(self):
        """Prompt must instruct the LLM to call the downstream tool."""
        result = trace_wcnp_app("my-app", "my-ns")
        assert "fetch_wcnp_downstream_dependencies" in result

    def test_contains_numbered_steps(self):
        """Prompt must have at least 2 numbered steps (multi-tool workflow)."""
        result = trace_wcnp_app("my-app", "my-ns")
        assert "1." in result
        assert "2." in result

    def test_mentions_summary_step(self):
        """Prompt must include a final summarisation step."""
        result = trace_wcnp_app("my-app", "my-ns")
        assert "Summarise" in result or "summarise" in result or "summary" in result.lower()

    def test_different_apps_produce_different_prompts(self):
        """Two different app names must produce different prompt texts."""
        p1 = trace_wcnp_app("app-a", "ns-1")
        p2 = trace_wcnp_app("app-b", "ns-2")
        assert p1 != p2

    def test_t0_tier_is_highlighted(self):
        """Prompt must instruct LLM to highlight T0-tier (critical) dependencies."""
        result = trace_wcnp_app("my-app", "my-ns")
        assert "T0" in result or "critical" in result.lower()


# ─── trace_oneops_app prompt ─────────────────────────────────────────────────

class TestTraceOneopsAppPrompt:
    """Tests for the trace_oneops_app prompt."""

    def test_returns_non_empty_string(self):
        result = trace_oneops_app("mexicoecomm", "rmsag2", "mx-rms")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_interpolates_org(self):
        result = trace_oneops_app("mexicoecomm", "rmsag2", "mx-rms")
        assert "mexicoecomm" in result

    def test_interpolates_platform(self):
        result = trace_oneops_app("mexicoecomm", "rmsag2", "mx-rms")
        assert "rmsag2" in result

    def test_interpolates_assembly(self):
        result = trace_oneops_app("mexicoecomm", "rmsag2", "mx-rms")
        assert "mx-rms" in result

    def test_references_upstream_tool(self):
        """Prompt must instruct the LLM to call the upstream tool."""
        result = trace_oneops_app("o", "p", "a")
        assert "fetch_oneops_upstream_dependencies" in result

    def test_references_downstream_tool(self):
        """Prompt must instruct the LLM to call the downstream tool."""
        result = trace_oneops_app("o", "p", "a")
        assert "fetch_oneops_downstream_dependencies" in result

    def test_contains_numbered_steps(self):
        """Prompt must have at least 2 numbered steps (multi-tool workflow)."""
        result = trace_oneops_app("o", "p", "a")
        assert "1." in result
        assert "2." in result

    def test_mentions_summary_step(self):
        result = trace_oneops_app("o", "p", "a")
        assert "Summarise" in result or "summarise" in result or "summary" in result.lower()

    def test_t0_tier_is_highlighted(self):
        result = trace_oneops_app("o", "p", "a")
        assert "T0" in result or "critical" in result.lower()

    def test_different_assemblies_produce_different_prompts(self):
        p1 = trace_oneops_app("org", "plat", "assembly-1")
        p2 = trace_oneops_app("org", "plat", "assembly-2")
        assert p1 != p2
