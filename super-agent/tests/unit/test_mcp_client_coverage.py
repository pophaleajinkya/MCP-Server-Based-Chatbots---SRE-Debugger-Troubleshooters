"""Additional unit tests for app.mcp.client — covers YAML error handling and generate_faqs."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestLoadFromFileErrors:
    def test_missing_file_raises(self, tmp_path):
        from app.mcp.client import _load_from_file
        with pytest.raises(FileNotFoundError, match="MCP_SERVERS_FILE not found"):
            _load_from_file(str(tmp_path / "nonexistent.yml"))

    def test_invalid_yaml_raises(self, tmp_path):
        from app.mcp.client import _load_from_file
        bad_yaml = tmp_path / "bad.yml"
        bad_yaml.write_text("{{{{invalid yaml: [")
        with pytest.raises(ValueError, match="YAML syntax error"):
            _load_from_file(str(bad_yaml))

    def test_empty_yaml_raises(self, tmp_path):
        from app.mcp.client import _load_from_file
        empty = tmp_path / "empty.yml"
        empty.write_text("")
        with pytest.raises(ValueError, match="empty"):
            _load_from_file(str(empty))


class TestMCPPoolGenerateFaqs:
    def test_generate_faqs_from_prompts_and_tools(self):
        from app.mcp.client import MCPPool
        pool = MCPPool.__new__(MCPPool)
        pool._sessions = []
        pool.prompts = [
            {"name": "health-check_status", "description": "Check health status of a service"},
            {"name": "health-get_metrics", "description": "Get metrics for a service"},
            {"name": "deploy-trigger_deploy", "description": "Trigger a deployment"},
        ]
        pool.claude_tools = [
            {"name": "check_app_health", "description": "Check application health\nMore details here"},
            {"name": "get_incidents", "description": "Get active incidents"},
        ]

        faqs = pool.generate_faqs()
        assert len(faqs) >= 2  # at least prompts group(s) and tools group

        # Find the tools group
        tools_group = next((g for g in faqs if g["title"] == "Agent Tools"), None)
        assert tools_group is not None
        assert len(tools_group["faqs"]) == 2

        # Find the health prompts group
        health_group = next((g for g in faqs if "Health" in g["title"]), None)
        assert health_group is not None
        assert len(health_group["faqs"]) == 2

    def test_generate_faqs_empty(self):
        from app.mcp.client import MCPPool
        pool = MCPPool.__new__(MCPPool)
        pool._sessions = []
        pool.prompts = []
        pool.claude_tools = []
        faqs = pool.generate_faqs()
        assert faqs == []

    def test_generate_faqs_single_group_prompt(self):
        from app.mcp.client import MCPPool
        pool = MCPPool.__new__(MCPPool)
        pool._sessions = []
        pool.prompts = [
            {"name": "standalone_prompt", "description": "A standalone prompt"},
        ]
        pool.claude_tools = []
        faqs = pool.generate_faqs()
        assert len(faqs) == 1
        assert faqs[0]["title"] == "Agent Capabilities"
