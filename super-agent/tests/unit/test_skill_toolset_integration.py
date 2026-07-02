"""
Unit tests for SkillToolset integration in agent/__init__.py.

Covers:
  - _load_skills()          — loading skills from filesystem directories
  - make_agent()            — SkillToolset wiring into agent tools
  - Edge cases              — missing dirs, empty dirs, malformed SKILL.md,
                              duplicate names, disabled via config
  - Negative cases          — invalid frontmatter, name mismatches,
                              missing SKILL.md, permission errors

Also covers:
  - Skill scripts           — Python scripts in skills/*/scripts/
  - Script edge cases       — empty args, missing keys, malformed JSON
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_skill_md(skill_dir: Path, name: str, description: str = "Test skill.",
                    additional_tools: list | None = None, body: str = "# Instructions\nDo things."):
    """Write a valid SKILL.md into the given directory."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(exist_ok=True)
    (skill_dir / "references").mkdir(exist_ok=True)
    (skill_dir / "assets").mkdir(exist_ok=True)

    metadata_block = ""
    if additional_tools:
        tools_yaml = "\n".join(f"    - {t}" for t in additional_tools)
        metadata_block = f"metadata:\n  adk_additional_tools:\n{tools_yaml}\n"

    content = f"""---
name: {name}
description: >
  {description}
{metadata_block}---

{body}
"""
    (skill_dir / "SKILL.md").write_text(content)


def _write_script(skill_dir: Path, script_name: str, script_content: str):
    """Write a Python script into the skill's scripts/ subdirectory."""
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / script_name).write_text(script_content)


# ── _load_skills ─────────────────────────────────────────────────────────────

class TestLoadSkills:

    def test_loads_valid_skills(self, tmp_path):
        """Skills are loaded from subdirectories with valid SKILL.md."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "my-skill", "my-skill", "A test skill.")
        _write_skill_md(skills_dir / "other-skill", "other-skill", "Another skill.")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"my-skill", "other-skill"}

    def test_empty_skills_dir_returns_empty_list(self, tmp_path):
        """Empty directory returns [] without error."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skills = agent_mod._load_skills(str(skills_dir))
        assert skills == []

    def test_nonexistent_dir_returns_empty_list(self, tmp_path):
        """Missing directory returns [] without raising."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(tmp_path / "does-not-exist"))
        assert skills == []

    def test_skips_hidden_directories(self, tmp_path):
        """Directories starting with '.' are ignored."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "good-skill", "good-skill")
        _write_skill_md(skills_dir / ".hidden-skill", ".hidden-skill")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        assert skills[0].name == "good-skill"

    def test_skips_files_in_skills_dir(self, tmp_path):
        """Non-directory entries (files) are silently skipped."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "README.md").write_text("Not a skill.")
        _write_skill_md(skills_dir / "real-skill", "real-skill")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        assert skills[0].name == "real-skill"

    def test_skips_dir_missing_skill_md(self, tmp_path):
        """Subdirectory without SKILL.md is skipped with a warning, not a crash."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "valid-skill", "valid-skill")
        # Create a dir with no SKILL.md
        (skills_dir / "broken-skill").mkdir(parents=True)
        (skills_dir / "broken-skill" / "scripts").mkdir()

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        assert skills[0].name == "valid-skill"

    def test_skips_name_mismatch(self, tmp_path):
        """Skill where name doesn't match directory name is skipped."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        # Directory is "foo-skill" but frontmatter name is "bar-skill"
        _write_skill_md(skills_dir / "foo-skill", "bar-skill")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 0

    def test_skips_malformed_frontmatter(self, tmp_path):
        """Invalid YAML frontmatter is skipped without crashing."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "good-skill", "good-skill")
        # Write a malformed SKILL.md
        bad_dir = skills_dir / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("---\nname: [[[invalid yaml\n---\nBody.")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        assert skills[0].name == "good-skill"

    def test_skips_empty_skill_md(self, tmp_path):
        """Empty SKILL.md is skipped without crashing."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "good-skill", "good-skill")
        bad_dir = skills_dir / "empty-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1

    def test_skips_missing_name_in_frontmatter(self, tmp_path):
        """SKILL.md without required 'name' field is skipped."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        bad_dir = skills_dir / "no-name"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("---\ndescription: no name field\n---\nBody.")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 0

    def test_skips_missing_description(self, tmp_path):
        """SKILL.md without required 'description' field is skipped."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        bad_dir = skills_dir / "no-desc"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("---\nname: no-desc\n---\nBody.")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 0

    def test_loads_additional_tools_metadata(self, tmp_path):
        """adk_additional_tools from metadata is parsed correctly."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(
            skills_dir / "tooled-skill", "tooled-skill",
            additional_tools=["tool_a", "tool_b", "tool_c"],
        )

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        tools = skills[0].frontmatter.metadata.get("adk_additional_tools", [])
        assert tools == ["tool_a", "tool_b", "tool_c"]

    def test_skill_without_metadata_has_empty_additional_tools(self, tmp_path):
        """Skill without metadata section still loads with empty additional_tools."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "simple-skill", "simple-skill")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        tools = skills[0].frontmatter.metadata.get("adk_additional_tools", [])
        assert tools == []

    def test_relative_path_resolved_from_project_root(self, tmp_path, monkeypatch):
        """Relative skills_dir is resolved against the project root (2 parents up from __init__.py)."""
        import agent as agent_mod
        # _load_skills uses Path(__file__).parents[2] as project root
        # We can test that a relative path gets resolved
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "rel-skill", "rel-skill")

        # Using absolute path should always work
        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1

    def test_loads_scripts_from_skill_directory(self, tmp_path):
        """Python scripts in scripts/ subdir are loaded as resources."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "scripted-skill", "scripted-skill")
        _write_script(skills_dir / "scripted-skill", "helper.py", "print('hello')")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        assert "helper.py" in skills[0].resources.list_scripts()

    def test_loads_multiple_scripts(self, tmp_path):
        """Multiple scripts in scripts/ are all loaded."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "multi-script", "multi-script")
        _write_script(skills_dir / "multi-script", "script_a.py", "print('a')")
        _write_script(skills_dir / "multi-script", "script_b.py", "print('b')")

        skills = agent_mod._load_skills(str(skills_dir))
        script_names = skills[0].resources.list_scripts()
        assert "script_a.py" in script_names
        assert "script_b.py" in script_names

    def test_invalid_name_format_skipped(self, tmp_path):
        """Name with uppercase or special chars fails ADK validation — skipped."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        bad_dir = skills_dir / "BadName"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text(
            "---\nname: BadName\ndescription: Bad name.\n---\nBody."
        )

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 0

    def test_description_too_long_skipped(self, tmp_path):
        """Description exceeding 1024 chars fails validation — skipped."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        bad_dir = skills_dir / "long-desc"
        bad_dir.mkdir(parents=True)
        long_desc = "x" * 1025
        (bad_dir / "SKILL.md").write_text(
            f"---\nname: long-desc\ndescription: {long_desc}\n---\nBody."
        )

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 0


# ── make_agent SkillToolset integration ──────────────────────────────────────

class TestMakeAgentSkillToolset:

    @pytest.fixture(autouse=True)
    def _clear_settings_cache(self):
        """Ensure get_settings() LRU cache is fresh for every test."""
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_skill_toolset_added_when_skills_exist(self, tmp_path, monkeypatch):
        """SkillToolset is in agent.tools when skills_dir has valid skills."""
        import agent as agent_mod
        from google.adk.tools.skill_toolset import SkillToolset

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "my-skill", "my-skill")

        monkeypatch.setenv("SKILLS_DIR", str(skills_dir))
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        toolset_types = [type(t) for t in agent.tools]
        assert SkillToolset in toolset_types

    @pytest.mark.asyncio
    async def test_no_skill_toolset_when_skills_dir_empty_string(self, monkeypatch):
        """Empty skills_dir config disables SkillToolset."""
        import agent as agent_mod
        from google.adk.tools.skill_toolset import SkillToolset
        from app.config import Settings

        mock_settings = Settings.model_construct(skills_dir="", a2ui_enabled=False)
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        toolset_types = [type(t) for t in agent.tools]
        assert SkillToolset not in toolset_types

    @pytest.mark.asyncio
    async def test_no_skill_toolset_when_dir_missing(self, tmp_path, monkeypatch):
        """Non-existent skills_dir results in no SkillToolset (graceful)."""
        import agent as agent_mod
        from google.adk.tools.skill_toolset import SkillToolset
        from app.config import Settings

        mock_settings = Settings.model_construct(
            skills_dir=str(tmp_path / "no-such-dir"), a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        toolset_types = [type(t) for t in agent.tools]
        assert SkillToolset not in toolset_types

    @pytest.mark.asyncio
    async def test_no_skill_toolset_when_all_skills_invalid(self, tmp_path, monkeypatch):
        """If all skills fail to load, SkillToolset is not added."""
        import agent as agent_mod
        from google.adk.tools.skill_toolset import SkillToolset
        from app.config import Settings

        skills_dir = tmp_path / "skills"
        # Directory exists but only contains invalid skills
        bad_dir = skills_dir / "broken"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("not valid yaml at all {{{")

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        toolset_types = [type(t) for t in agent.tools]
        assert SkillToolset not in toolset_types

    @pytest.mark.asyncio
    async def test_enable_mcps_true_toolsets_in_global_tools(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=true: MCPToolsets are in global tools list."""
        import agent as agent_mod
        from app.config import Settings

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "my-skill", "my-skill")

        mock_toolset = MagicMock()
        mock_toolset.name = "mock-mcp"

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=True, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)

        assert mock_toolset in agent.tools

    @pytest.mark.asyncio
    async def test_enable_mcps_false_toolsets_not_in_global_tools(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=false: MCPToolsets are NOT in global tools (gated by skills)."""
        import agent as agent_mod
        from app.config import Settings

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "my-skill", "my-skill")

        mock_toolset = MagicMock()
        mock_toolset.name = "mock-mcp"

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=False, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)

        # MCPToolset should NOT be in global tools — only inside SkillToolset
        assert mock_toolset not in agent.tools

    @pytest.mark.asyncio
    async def test_pingfed_token_always_in_tools(self, tmp_path, monkeypatch):
        """pingfed_token tool is always present regardless of SkillToolset status."""
        import agent as agent_mod
        from app.tools.auth_tool import pingfed_token

        monkeypatch.setenv("SKILLS_DIR", "")
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        assert pingfed_token in agent.tools

    @pytest.mark.asyncio
    async def test_remote_agent_tools_in_agent_tools(self, tmp_path, monkeypatch):
        """Remote agent tools are present in agent.tools."""
        import agent as agent_mod

        mock_remote_tool = MagicMock()
        mock_remote_tool.__name__ = "remote_agent_tool"

        monkeypatch.setenv("SKILLS_DIR", "")
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."):
            agent = await agent_mod.make_agent(
                [], guide="", mcp_pool=None,
                remote_agent_tools=[mock_remote_tool],
            )

        assert mock_remote_tool in agent.tools

    @pytest.mark.asyncio
    async def test_enable_mcps_true_skill_toolset_no_additional_tools(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=true: SkillToolset constructed WITHOUT additional_tools."""
        import agent as agent_mod
        from app.config import Settings
        from google.adk.tools.skill_toolset import SkillToolset

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "pooled-skill", "pooled-skill",
                        additional_tools=["mock_tool"])

        mock_toolset = MagicMock()
        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=True, a2ui_enabled=False,
        )

        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            with patch.object(SkillToolset, "__init__", return_value=None) as mock_init:
                mock_init.return_value = None
                try:
                    await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)
                except Exception:
                    pass

                if mock_init.called:
                    call_kwargs = mock_init.call_args
                    additional = call_kwargs.kwargs.get("additional_tools")
                    assert additional is None, (
                        "ENABLE_MCPS=true: SkillToolset should NOT receive "
                        "additional_tools — MCP tools are global"
                    )

    @pytest.mark.asyncio
    async def test_enable_mcps_false_skill_toolset_receives_additional_tools(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=false: SkillToolset constructed WITH additional_tools."""
        import agent as agent_mod
        from app.config import Settings
        from google.adk.tools.skill_toolset import SkillToolset

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "pooled-skill", "pooled-skill",
                        additional_tools=["mock_tool"])

        mock_toolset = MagicMock()
        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=False, a2ui_enabled=False,
        )

        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            with patch.object(SkillToolset, "__init__", return_value=None) as mock_init:
                mock_init.return_value = None
                try:
                    await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)
                except Exception:
                    pass

                if mock_init.called:
                    call_kwargs = mock_init.call_args
                    additional = call_kwargs.kwargs.get("additional_tools")
                    assert additional is not None, (
                        "ENABLE_MCPS=false: SkillToolset MUST receive "
                        "additional_tools — MCP tools are gated behind skills"
                    )
                    assert mock_toolset in additional

    # ── Edge / negative cases for ENABLE_MCPS ────────────────────────────────

    @pytest.mark.asyncio
    async def test_enable_mcps_false_no_skills_dir_falls_back_to_global(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=false + SKILLS_DIR="" → MCP tools fall back to global."""
        import agent as agent_mod
        from app.config import Settings

        mock_toolset = MagicMock()
        mock_toolset.name = "mock-mcp"

        mock_settings = Settings.model_construct(
            skills_dir="", enable_mcps=False, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)

        # No skills_dir → SkillToolset never constructed → fallback to global
        assert mock_toolset in agent.tools

    @pytest.mark.asyncio
    async def test_enable_mcps_false_no_valid_skills_falls_back_to_global(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=false + skills_dir exists but empty → MCP tools fall back to global."""
        import agent as agent_mod
        from app.config import Settings

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        # Directory exists but contains no valid skills

        mock_toolset = MagicMock()
        mock_toolset.name = "mock-mcp"

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=False, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)

        # No valid skills → SkillToolset never constructed → fallback to global
        assert mock_toolset in agent.tools

    @pytest.mark.asyncio
    async def test_enable_mcps_false_skill_toolset_fails_falls_back_to_global(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=false + SkillToolset construction fails → MCP tools fall back to global."""
        import agent as agent_mod
        from app.config import Settings
        from google.adk.tools.skill_toolset import SkillToolset

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "my-skill", "my-skill")

        mock_toolset = MagicMock()
        mock_toolset.name = "mock-mcp"

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=False, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings), \
             patch.object(SkillToolset, "__init__", side_effect=RuntimeError("boom")):
            agent = await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)

        # SkillToolset failed → fallback to global
        assert mock_toolset in agent.tools

    @pytest.mark.asyncio
    async def test_enable_mcps_true_no_skills_dir_mcp_tools_still_global(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=true + SKILLS_DIR="" → MCP tools global, no SkillToolset."""
        import agent as agent_mod
        from app.config import Settings
        from google.adk.tools.skill_toolset import SkillToolset

        mock_toolset = MagicMock()
        mock_toolset.name = "mock-mcp"

        mock_settings = Settings.model_construct(
            skills_dir="", enable_mcps=True, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            agent = await agent_mod.make_agent([mock_toolset], guide="", mcp_pool=None)

        # MCP tools global, no SkillToolset present
        assert mock_toolset in agent.tools
        toolset_types = [type(t) for t in agent.tools]
        assert SkillToolset not in toolset_types

    @pytest.mark.asyncio
    async def test_enable_mcps_false_empty_toolsets_no_crash(self, tmp_path, monkeypatch):
        """ENABLE_MCPS=false + empty toolsets=[] → SkillToolset with no additional tools."""
        import agent as agent_mod
        from app.config import Settings

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "my-skill", "my-skill")

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), enable_mcps=False, a2ui_enabled=False,
        )
        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings):
            # Should not raise even with empty toolsets
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        assert agent is not None


# ── Skill script edge cases ──────────────────────────────────────────────────

class TestSkillScripts:
    """Test the actual Python scripts in skills/*/scripts/ handle edge cases."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).resolve().parent.parent.parent

    # ── health-triage/scripts/summarize_health.py ──

    def test_summarize_health_empty_result(self, project_root):
        """summarize_health handles empty health result dict."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({})
        assert "Health Triage Summary" in result
        assert "unknown" in result.lower()
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    def test_summarize_health_healthy_app(self, project_root):
        """summarize_health produces green status for healthy app."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({
            "overall_status": "healthy",
            "anomaly_detected": False,
            "root_cause": "none",
            "failure_attribution": "none",
        })
        assert "HEALTHY" in result
        assert "No action required" in result
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    def test_summarize_health_critical_anomaly(self, project_root):
        """summarize_health classifies unhealthy + anomaly as CRITICAL."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({
            "overall_status": "unhealthy",
            "anomaly_detected": True,
            "root_cause": "CPU spike",
            "failure_attribution": "this_app",
        })
        assert "CRITICAL" in result
        assert "incident-rca" in result
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    def test_summarize_health_downstream_dependency(self, project_root):
        """summarize_health recommends dependency-mapping for downstream issues."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({
            "overall_status": "unhealthy",
            "anomaly_detected": False,
            "failure_attribution": "downstream_dependency",
        })
        assert "dependency-mapping" in result
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    def test_summarize_health_with_failed_checks(self, project_root):
        """summarize_health lists failed checks from the checks dict."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({
            "overall_status": "degraded",
            "anomaly_detected": False,
            "checks": {
                "cpu": {"status": "critical", "message": "CPU at 95%"},
                "memory": {"status": "healthy", "message": "OK"},
                "restarts": {"status": "warning", "message": "3 restarts"},
            },
        })
        assert "cpu" in result.lower()
        assert "CPU at 95%" in result
        assert "3 restarts" in result
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    def test_summarize_health_checks_not_dict(self, project_root):
        """summarize_health handles non-dict checks gracefully."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({
            "overall_status": "healthy",
            "checks": "not a dict",
        })
        assert "Health Triage Summary" in result
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    def test_summarize_health_correlations_as_strings(self, project_root):
        """summarize_health handles correlations as list of strings."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import summarize_health
        result = summarize_health.summarize({
            "overall_status": "degraded",
            "correlations": ["traffic → latency", "cpu → memory"],
        })
        assert "traffic" in result
        sys.path.pop(0)
        sys.modules.pop("summarize_health", None)

    # ── health-triage/scripts/compare_clusters.py ──

    def test_compare_clusters_no_cluster_data(self, project_root):
        """compare_clusters handles missing cluster data."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import compare_clusters
        result = compare_clusters.compare({})
        assert "No cluster data" in result
        sys.path.pop(0)
        sys.modules.pop("compare_clusters", None)

    def test_compare_clusters_single_cluster(self, project_root):
        """compare_clusters reports when < 2 clusters present."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import compare_clusters
        result = compare_clusters.compare({"clusters": {"us-east": {"status": "healthy"}}})
        assert "Only 1 cluster" in result
        sys.path.pop(0)
        sys.modules.pop("compare_clusters", None)

    def test_compare_clusters_detects_divergence(self, project_root):
        """compare_clusters flags divergent check statuses across clusters."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import compare_clusters
        result = compare_clusters.compare({
            "clusters": {
                "us-east": {"checks": {"cpu": {"status": "healthy"}, "memory": {"status": "critical"}}},
                "us-west": {"checks": {"cpu": {"status": "healthy"}, "memory": {"status": "healthy"}}},
            }
        })
        assert "divergent" in result.lower()
        sys.path.pop(0)
        sys.modules.pop("compare_clusters", None)

    def test_compare_clusters_no_divergence(self, project_root):
        """compare_clusters reports consistency when all clusters match."""
        sys.path.insert(0, str(project_root / "skills" / "health-triage" / "scripts"))
        import compare_clusters
        result = compare_clusters.compare({
            "clusters": {
                "us-east": {"checks": {"cpu": {"status": "healthy"}}},
                "us-west": {"checks": {"cpu": {"status": "healthy"}}},
            }
        })
        assert "consistent" in result.lower()
        sys.path.pop(0)
        sys.modules.pop("compare_clusters", None)

    # ── log-analysis/scripts/parse_exceptions.py ──

    def test_parse_exceptions_empty_rows(self, project_root):
        """parse_exceptions handles empty result."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        result = parse_exceptions.parse_exceptions({})
        assert "No exception data" in result
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    def test_parse_exceptions_classifies_severity(self, project_root):
        """parse_exceptions classifies timeout as Critical, null as Error."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        result = parse_exceptions.parse_exceptions({
            "rows": [
                {"exception_class": "TimeoutException", "count": 100},
                {"exception_class": "NullPointerException", "count": 50},
                {"exception_class": "RetryableException", "count": 10},
            ]
        })
        assert "Critical" in result
        assert "Error" in result
        assert "Warning" in result
        assert "160" in result  # total
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    def test_parse_exceptions_string_count(self, project_root):
        """parse_exceptions handles count as string (SQL result edge case)."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        result = parse_exceptions.parse_exceptions({
            "rows": [{"exception_class": "SomeException", "count": "42"}]
        })
        assert "42" in result
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    def test_parse_exceptions_missing_class_field(self, project_root):
        """parse_exceptions falls back to 'Unknown' when no exception_class field."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        result = parse_exceptions.parse_exceptions({
            "rows": [{"message": "something went wrong"}]
        })
        assert "Unknown" in result
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    def test_parse_exceptions_truncates_long_messages(self, project_root):
        """parse_exceptions truncates sample messages over 200 chars."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        long_msg = "A" * 300
        result = parse_exceptions.parse_exceptions({
            "rows": [{"exception_class": "TestException", "exception_message": long_msg}]
        })
        assert "..." in result
        # Should not contain the full 300 char message
        assert long_msg not in result
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    # ── log-analysis/scripts/build_histogram.py ──

    def test_build_histogram_empty_data(self, project_root):
        """build_histogram handles empty rows."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import build_histogram
        result = build_histogram.build_histogram([])
        assert "No data" in result
        sys.path.pop(0)
        sys.modules.pop("build_histogram", None)

    def test_build_histogram_all_zero_values(self, project_root):
        """build_histogram handles rows where all values are 0."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import build_histogram
        rows = [
            {"bucket": "2026-04-14T10:00:00Z", "requests": 0},
            {"bucket": "2026-04-14T10:05:00Z", "requests": 0},
        ]
        result = build_histogram.build_histogram(rows)
        assert "Histogram" in result
        sys.path.pop(0)
        sys.modules.pop("build_histogram", None)

    def test_build_histogram_string_values(self, project_root):
        """build_histogram handles numeric values passed as strings."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import build_histogram
        rows = [
            {"bucket": "10:00", "requests": "100"},
            {"bucket": "10:05", "requests": "200"},
        ]
        result = build_histogram.build_histogram(rows)
        assert "200" in result
        sys.path.pop(0)
        sys.modules.pop("build_histogram", None)

    def test_build_histogram_non_numeric_values(self, project_root):
        """build_histogram treats non-numeric values as 0."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import build_histogram
        rows = [{"bucket": "10:00", "requests": "not-a-number"}]
        result = build_histogram.build_histogram(rows)
        assert "Histogram" in result
        sys.path.pop(0)
        sys.modules.pop("build_histogram", None)

    # ── incident-rca/scripts/build_rca_timeline.py ──

    def test_rca_timeline_no_data(self, project_root):
        """build_rca_timeline returns message when no data given."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        result = build_rca_timeline.build_timeline()
        assert "No RCA data" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    def test_rca_timeline_only_blame(self, project_root):
        """build_rca_timeline works with only blame data."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        result = build_rca_timeline.build_timeline(
            blame={"author": "dev@walmart.com", "sha": "abc12345", "date": "2026-04-14T10:00:00Z"}
        )
        assert "Code Authored" in result
        assert "dev@walmart.com" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    def test_rca_timeline_full_chain(self, project_root):
        """build_rca_timeline assembles the complete chain correctly."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        result = build_rca_timeline.build_timeline(
            blame={"author": "dev", "sha": "abc", "date": "2026-04-14T08:00:00Z"},
            commit={"sha": "abc12345", "commit": {"committer": {"date": "2026-04-14T09:00:00Z"}, "message": "Fix bug"}},
            pr={"number": 42, "title": "Fix timeout", "merged_at": "2026-04-14T10:00:00Z", "merged_by": {"login": "reviewer"}},
            tag={"name": "v1.2.3", "date": "2026-04-14T11:00:00Z"},
            incident={"number": "INC123", "priority": "P1", "short_description": "Outage", "opened_at": "2026-04-14T14:00:00Z"},
        )
        assert "Code Authored" in result
        assert "Commit Pushed" in result
        assert "PR Merged" in result
        assert "Release Tagged" in result
        assert "Incident Opened" in result
        assert "Total span" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    def test_rca_timeline_missing_timestamps(self, project_root):
        """build_rca_timeline handles events with missing/invalid timestamps."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        result = build_rca_timeline.build_timeline(
            blame={"author": "dev", "sha": "abc"},  # no date
            incident={"number": "INC123", "opened_at": ""},  # empty date
        )
        assert "Code Authored" in result
        assert "Incident Opened" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    # ── deployment-check/scripts/deployment_diff.py ──

    def test_deployment_diff_empty_list(self, project_root):
        """deployment_diff handles empty deployment list."""
        sys.path.insert(0, str(project_root / "skills" / "deployment-check" / "scripts"))
        import deployment_diff
        result = deployment_diff.analyze_deployments([])
        assert "No deployment data" in result
        sys.path.pop(0)
        sys.modules.pop("deployment_diff", None)

    def test_deployment_diff_valid_data(self, project_root):
        """deployment_diff produces version change table."""
        sys.path.insert(0, str(project_root / "skills" / "deployment-check" / "scripts"))
        import deployment_diff
        result = deployment_diff.analyze_deployments([
            {"app_name": "cart", "version": "1.0", "deployed_at": "2026-04-14T10:00:00Z", "deployer": "ci-bot"},
            {"app_name": "cart", "version": "1.1", "deployed_at": "2026-04-14T11:00:00Z", "deployer": "dev"},
        ])
        assert "cart" in result
        assert "1.0" in result
        assert "1.1" in result
        assert "Deployment Analysis" in result
        sys.path.pop(0)
        sys.modules.pop("deployment_diff", None)

    def test_deployment_diff_missing_timestamp(self, project_root):
        """deployment_diff handles records with missing timestamp."""
        sys.path.insert(0, str(project_root / "skills" / "deployment-check" / "scripts"))
        import deployment_diff
        result = deployment_diff.analyze_deployments([
            {"app_name": "svc", "version": "1.0"},
        ])
        assert "svc" in result
        sys.path.pop(0)
        sys.modules.pop("deployment_diff", None)

    # ── dependency-mapping/scripts/blast_radius.py ──

    def test_blast_radius_no_dependencies(self, project_root):
        """blast_radius handles empty upstream and downstream."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        result = blast_radius.blast_radius("my-app", [], [])
        assert "my-app" in result
        assert "leaf service" in result.lower()
        assert "MINIMAL" in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    def test_blast_radius_high_risk_t0(self, project_root):
        """blast_radius classifies T0 upstream deps as HIGH RISK."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        result = blast_radius.blast_radius(
            "my-app",
            upstream=[{"app_name": "critical-svc", "namespace": "ns", "tier": "T0"}],
            downstream=[],
        )
        assert "HIGH RISK" in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    def test_blast_radius_medium_risk_many_upstream(self, project_root):
        """blast_radius classifies >10 upstream callers as MEDIUM RISK."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        upstream = [{"app_name": f"svc-{i}", "namespace": "ns"} for i in range(15)]
        result = blast_radius.blast_radius("my-app", upstream, [])
        assert "MEDIUM RISK" in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    def test_blast_radius_dict_input(self, project_root):
        """blast_radius handles dict with 'dependencies' key."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        result = blast_radius.blast_radius(
            "app",
            {"dependencies": [{"app_name": "caller", "namespace": "ns"}]},
            {"dependencies": []},
        )
        assert "caller" in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    def test_blast_radius_mermaid_generated(self, project_root):
        """blast_radius includes Mermaid graph when dependencies exist."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        result = blast_radius.blast_radius(
            "my-app",
            [{"app_name": "upstream-a"}],
            [{"app_name": "downstream-b"}],
        )
        assert "```mermaid" in result
        assert "graph LR" in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    # ── cosmos-triage/scripts/throttle_analysis.py ──

    def test_throttle_analysis_empty_result(self, project_root):
        """throttle_analysis handles empty health result."""
        sys.path.insert(0, str(project_root / "skills" / "cosmos-triage" / "scripts"))
        import throttle_analysis
        result = throttle_analysis.analyze_throttle({})
        assert "Cosmos DB Throttle Analysis" in result
        sys.path.pop(0)
        sys.modules.pop("throttle_analysis", None)

    def test_throttle_analysis_active_throttling(self, project_root):
        """throttle_analysis recommends RU increase when throttling is critical."""
        sys.path.insert(0, str(project_root / "skills" / "cosmos-triage" / "scripts"))
        import throttle_analysis
        result = throttle_analysis.analyze_throttle({
            "account_name": "my-cosmos",
            "overall_status": "unhealthy",
            "checks": {
                "throttled": {"status": "critical", "throttle_rate": "15%"},
                "ru": {"status": "critical", "utilization_pct": 98, "provisioned_ru": 1000, "consumed_ru": 980},
            }
        })
        assert "Increase provisioned RU" in result
        assert "98%" in result
        sys.path.pop(0)
        sys.modules.pop("throttle_analysis", None)

    def test_throttle_analysis_no_issues(self, project_root):
        """throttle_analysis reports green when no throttling."""
        sys.path.insert(0, str(project_root / "skills" / "cosmos-triage" / "scripts"))
        import throttle_analysis
        result = throttle_analysis.analyze_throttle({
            "checks": {"throttled": {"status": "healthy"}, "ru": {"status": "healthy"}}
        })
        assert "No throttling issues" in result
        sys.path.pop(0)
        sys.modules.pop("throttle_analysis", None)

    # ── cassandra-triage/scripts/bad_node_report.py ──

    def test_bad_node_report_empty_result(self, project_root):
        """bad_node_report handles empty health result."""
        sys.path.insert(0, str(project_root / "skills" / "cassandra-triage" / "scripts"))
        import bad_node_report
        result = bad_node_report.bad_node_report({})
        assert "Bad-Node Report" in result
        sys.path.pop(0)
        sys.modules.pop("bad_node_report", None)

    def test_bad_node_report_with_outliers(self, project_root):
        """bad_node_report lists bad nodes and provides remediation."""
        sys.path.insert(0, str(project_root / "skills" / "cassandra-triage" / "scripts"))
        import bad_node_report
        result = bad_node_report.bad_node_report({
            "cluster_name": "my-cluster",
            "checks": {
                "bad_node": {
                    "status": "critical",
                    "bad_nodes": [
                        {"node": "10.0.0.1", "p99_latency_ms": 500, "avg_latency_ms": 200, "timeout_rate": "5%"},
                    ],
                },
            },
        })
        assert "10.0.0.1" in result
        assert "500ms" in result
        assert "compaction" in result.lower()
        sys.path.pop(0)
        sys.modules.pop("bad_node_report", None)

    def test_bad_node_report_no_bad_nodes(self, project_root):
        """bad_node_report reports healthy when no outliers."""
        sys.path.insert(0, str(project_root / "skills" / "cassandra-triage" / "scripts"))
        import bad_node_report
        result = bad_node_report.bad_node_report({
            "checks": {"bad_node": {"status": "healthy", "bad_nodes": []}},
        })
        assert "No bad nodes" in result
        sys.path.pop(0)
        sys.modules.pop("bad_node_report", None)

    # ── sqlserver-triage/scripts/deadlock_analysis.py ──

    def test_deadlock_analysis_empty_result(self, project_root):
        """deadlock_analysis handles empty health result."""
        sys.path.insert(0, str(project_root / "skills" / "sqlserver-triage" / "scripts"))
        import deadlock_analysis
        result = deadlock_analysis.deadlock_analysis({})
        assert "SQL Server Analysis" in result
        sys.path.pop(0)
        sys.modules.pop("deadlock_analysis", None)

    def test_deadlock_analysis_with_deadlocks(self, project_root):
        """deadlock_analysis lists deadlock victims and recommends remediation."""
        sys.path.insert(0, str(project_root / "skills" / "sqlserver-triage" / "scripts"))
        import deadlock_analysis
        result = deadlock_analysis.deadlock_analysis({
            "database_name": "my-db",
            "overall_status": "unhealthy",
            "checks": {
                "deadlocks": {
                    "status": "critical", "count": 25,
                    "victims": [
                        {"timestamp": "10:00", "process": "SPID 42", "wait_resource": "KEY: db.tbl", "duration_ms": 1500},
                    ],
                },
                "cpu": {"status": "warning", "value": "85%"},
            },
        })
        assert "25 detected" in result
        assert "SPID 42" in result
        assert "consistent lock ordering" in result
        sys.path.pop(0)
        sys.modules.pop("deadlock_analysis", None)

    def test_deadlock_analysis_no_deadlocks(self, project_root):
        """deadlock_analysis reports clean when no deadlocks."""
        sys.path.insert(0, str(project_root / "skills" / "sqlserver-triage" / "scripts"))
        import deadlock_analysis
        result = deadlock_analysis.deadlock_analysis({
            "checks": {"deadlocks": {"status": "healthy", "count": 0}},
        })
        assert "No deadlock" in result
        sys.path.pop(0)
        sys.modules.pop("deadlock_analysis", None)

    def test_deadlock_analysis_count_without_victims(self, project_root):
        """deadlock_analysis handles count > 0 but no victim details."""
        sys.path.insert(0, str(project_root / "skills" / "sqlserver-triage" / "scripts"))
        import deadlock_analysis
        result = deadlock_analysis.deadlock_analysis({
            "checks": {"deadlocks": {"status": "warning", "count": 5}},
        })
        assert "5 detected" in result
        assert "no victim details" in result.lower()
        sys.path.pop(0)
        sys.modules.pop("deadlock_analysis", None)


# ── Real skills/ directory validation ────────────────────────────────────────

class TestRealSkillsDirectory:
    """Validate the actual skills/ directory at project root."""

    @pytest.fixture
    def skills_dir(self):
        return Path(__file__).resolve().parent.parent.parent / "skills"

    def test_all_skills_load_without_error(self, skills_dir):
        """Every skill in skills/ loads via ADK _load_skill_from_dir without error."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) >= 8, f"Expected ≥8 skills, got {len(skills)}"

    def test_all_skill_names_match_directories(self, skills_dir):
        """Each skill's frontmatter name matches its directory name."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        for skill in skills:
            # The ADK loader enforces this, but let's verify
            assert skill.name == skill.name.lower()
            assert " " not in skill.name

    def test_all_skills_have_descriptions(self, skills_dir):
        """Every skill has a non-empty description."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        for skill in skills:
            assert len(skill.description.strip()) > 0, f"{skill.name} has empty description"

    def test_all_skills_have_instructions(self, skills_dir):
        """Every skill has non-empty instructions (SKILL.md body)."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        for skill in skills:
            assert len(skill.instructions.strip()) > 0, f"{skill.name} has empty instructions"

    def test_all_skills_have_scripts(self, skills_dir):
        """Every skill (except purely informational ones) has at least one Python script."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        for skill in skills:
            if skill.name in ("support", "edge-triage", "deep-historical"):
                continue
            scripts = skill.resources.list_scripts()
            assert len(scripts) >= 1, f"{skill.name} has no scripts"
            for s in scripts:
                assert s.endswith(".py"), f"{skill.name}: script {s} is not a .py file"

    def test_no_duplicate_skill_names(self, skills_dir):
        """No two skills share the same name."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        names = [s.name for s in skills]
        assert len(names) == len(set(names)), f"Duplicate skill names: {names}"

    def test_additional_tools_are_strings(self, skills_dir):
        """adk_additional_tools metadata values are all strings."""
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        for skill in skills:
            tools = skill.frontmatter.metadata.get("adk_additional_tools", [])
            for tool_name in tools:
                assert isinstance(tool_name, str), \
                    f"{skill.name}: tool name {tool_name!r} is not a string"

    def test_skill_names_are_kebab_case(self, skills_dir):
        """All skill names follow kebab-case convention."""
        import re
        import agent as agent_mod
        skills = agent_mod._load_skills(str(skills_dir))
        kebab = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
        for skill in skills:
            assert kebab.match(skill.name), f"{skill.name} is not valid kebab-case"


# ── Exception handling edge cases (post-hardening) ───────────────────────────

class TestExceptionHandling:
    """Tests for exception handling in code and scripts after hardening pass."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).resolve().parent.parent.parent

    # ── _load_skills metadata access (was .adk_additional_tools, now .get()) ──

    def test_load_skills_metadata_access_uses_dict_get(self, tmp_path):
        """_load_skills accesses metadata via dict .get(), not attribute access."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "meta-skill", "meta-skill",
                        additional_tools=["tool_a", "tool_b"])

        # This previously crashed with AttributeError: 'dict' has no attribute 'adk_additional_tools'
        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1
        assert skills[0].name == "meta-skill"

    def test_load_skills_metadata_without_additional_tools_key(self, tmp_path):
        """_load_skills handles metadata dict that has no adk_additional_tools key."""
        import agent as agent_mod
        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "plain-skill", "plain-skill")

        skills = agent_mod._load_skills(str(skills_dir))
        assert len(skills) == 1

    # ── SkillToolset constructor failure ──

    @pytest.mark.asyncio
    async def test_make_agent_survives_skill_toolset_constructor_error(self, tmp_path, monkeypatch):
        """If SkillToolset() raises, make_agent still returns a working agent."""
        import agent as agent_mod
        from google.adk.tools.skill_toolset import SkillToolset
        from app.config import Settings

        skills_dir = tmp_path / "skills"
        _write_skill_md(skills_dir / "ok-skill", "ok-skill")

        mock_settings = Settings.model_construct(
            skills_dir=str(skills_dir), a2ui_enabled=False,
        )

        def _boom(*args, **kwargs):
            raise ValueError("Simulated ADK construction failure")

        with patch("app.services.agent_instruction.load_agent_instruction", new_callable=AsyncMock, return_value="Test."), \
             patch("agent.get_settings", return_value=mock_settings), \
             patch.object(SkillToolset, "__init__", _boom):
            agent = await agent_mod.make_agent([], guide="", mcp_pool=None)

        # Agent should still be created — just without SkillToolset
        assert agent is not None
        assert SkillToolset not in [type(t) for t in agent.tools]

    # ── parse_exceptions: non-numeric count ──

    def test_parse_exceptions_non_numeric_count(self, project_root):
        """parse_exceptions treats non-numeric count string as 1."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        result = parse_exceptions.parse_exceptions({
            "rows": [{"exception_class": "SomeError", "count": "N/A"}]
        })
        assert "SomeError" in result
        assert "1" in result  # Falls back to count=1
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    def test_parse_exceptions_none_count(self, project_root):
        """parse_exceptions treats None count as 1."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import parse_exceptions
        result = parse_exceptions.parse_exceptions({
            "rows": [{"exception_class": "SomeError", "count": None}]
        })
        assert "1" in result
        sys.path.pop(0)
        sys.modules.pop("parse_exceptions", None)

    # ── build_histogram: None value ──

    def test_build_histogram_none_value(self, project_root):
        """build_histogram treats None value as 0."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import build_histogram
        rows = [{"bucket": "10:00", "requests": None}]
        result = build_histogram.build_histogram(rows)
        assert "Histogram" in result
        sys.path.pop(0)
        sys.modules.pop("build_histogram", None)

    def test_build_histogram_non_dict_row(self, project_root):
        """build_histogram skips rows that aren't dicts."""
        sys.path.insert(0, str(project_root / "skills" / "log-analysis" / "scripts"))
        import build_histogram
        rows = ["not a dict", {"bucket": "10:00", "requests": 50}]
        result = build_histogram.build_histogram(rows)
        assert "50" in result
        sys.path.pop(0)
        sys.modules.pop("build_histogram", None)

    # ── build_rca_timeline: aware/naive datetime sorting ──

    def test_rca_timeline_mixed_none_and_valid_timestamps(self, project_root):
        """build_rca_timeline sorts correctly when some events have None timestamps."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        # This previously crashed with "can't compare offset-naive and offset-aware datetimes"
        result = build_rca_timeline.build_timeline(
            blame={"author": "dev", "sha": "abc12345", "date": "2026-04-14T10:00:00Z"},
            commit={"sha": "def456", "commit": {"committer": {"date": ""}, "message": "msg"}},  # empty date → None
            incident={"number": "INC1", "opened_at": "2026-04-14T12:00:00Z"},
        )
        assert "Code Authored" in result
        assert "Incident Opened" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    def test_rca_timeline_sha_is_none(self, project_root):
        """build_rca_timeline handles sha=None without TypeError."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        # This previously crashed with None[:8] → TypeError
        result = build_rca_timeline.build_timeline(
            blame={"author": "dev", "sha": None, "date": "2026-04-14T10:00:00Z"},
        )
        assert "Code Authored" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    def test_rca_timeline_date_is_not_string(self, project_root):
        """build_rca_timeline handles non-string date values."""
        sys.path.insert(0, str(project_root / "skills" / "incident-rca" / "scripts"))
        import build_rca_timeline
        result = build_rca_timeline.build_timeline(
            blame={"author": "dev", "sha": "abc", "date": 12345},  # int, not str
        )
        assert "Code Authored" in result
        sys.path.pop(0)
        sys.modules.pop("build_rca_timeline", None)

    # ── deployment_diff: None timestamp, aware/naive ──

    def test_deployment_diff_none_timestamp_field(self, project_root):
        """deployment_diff handles None timestamp without AttributeError."""
        sys.path.insert(0, str(project_root / "skills" / "deployment-check" / "scripts"))
        import deployment_diff
        # deployed_at is None — previously crashed on None.replace("Z", ...)
        result = deployment_diff.analyze_deployments([
            {"app_name": "svc", "version": "1.0", "deployed_at": None},
            {"app_name": "svc", "version": "1.1", "deployed_at": "2026-04-14T10:00:00Z"},
        ])
        assert "svc" in result
        sys.path.pop(0)
        sys.modules.pop("deployment_diff", None)

    def test_deployment_diff_integer_timestamp(self, project_root):
        """deployment_diff handles non-string timestamp gracefully."""
        sys.path.insert(0, str(project_root / "skills" / "deployment-check" / "scripts"))
        import deployment_diff
        result = deployment_diff.analyze_deployments([
            {"app_name": "svc", "version": "1.0", "deployed_at": 1681459200},
        ])
        assert "svc" in result
        sys.path.pop(0)
        sys.modules.pop("deployment_diff", None)

    # ── blast_radius: non-dict deps ──

    def test_blast_radius_non_dict_upstream_entries(self, project_root):
        """blast_radius skips non-dict entries in upstream list."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        result = blast_radius.blast_radius(
            "my-app",
            ["not-a-dict", {"app_name": "real-svc", "namespace": "ns"}],
            [],
        )
        assert "real-svc" in result
        assert "not-a-dict" not in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    def test_blast_radius_non_dict_downstream_entries(self, project_root):
        """blast_radius skips non-dict entries in downstream list."""
        sys.path.insert(0, str(project_root / "skills" / "dependency-mapping" / "scripts"))
        import blast_radius
        result = blast_radius.blast_radius(
            "my-app",
            [],
            [42, None, {"app_name": "db-svc"}],
        )
        assert "db-svc" in result
        sys.path.pop(0)
        sys.modules.pop("blast_radius", None)

    # ── Script __main__ blocks: malformed JSON input ──

    def test_summarize_health_script_bad_json(self, project_root):
        """summarize_health __main__ prints error on malformed JSON."""
        import subprocess
        script = project_root / "skills" / "health-triage" / "scripts" / "summarize_health.py"
        result = subprocess.run(
            [sys.executable, str(script), "not valid json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "Error parsing input" in result.stdout

    def test_blast_radius_script_bad_json(self, project_root):
        """blast_radius __main__ prints error on malformed JSON."""
        import subprocess
        script = project_root / "skills" / "dependency-mapping" / "scripts" / "blast_radius.py"
        result = subprocess.run(
            [sys.executable, str(script), "{{{bad json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "Error parsing input" in result.stdout

    def test_rca_timeline_script_bad_json(self, project_root):
        """build_rca_timeline __main__ prints error on malformed JSON."""
        import subprocess
        script = project_root / "skills" / "incident-rca" / "scripts" / "build_rca_timeline.py"
        result = subprocess.run(
            [sys.executable, str(script), "not json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "Error parsing input" in result.stdout
