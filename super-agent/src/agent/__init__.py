"""ADK agent module.

Exports:
  make_agent(toolsets)  — factory used by factory.py; builds agent from
                          MCPToolset instances loaded from Redis/YAML at startup.
  root_agent            — pre-built agent for `adk web` dev UI only;
                          uses MCP discovery via mcp/client.py (YAML file in dev).
"""

import asyncio
import logging
from pathlib import Path

from google.adk.agents import Agent
from google.adk.code_executors import UnsafeLocalCodeExecutor
from google.adk.code_executors.code_execution_utils import CodeExecutionInput, CodeExecutionResult
from google.adk.agents.invocation_context import InvocationContext
from google.adk.skills._utils import _load_skill_from_dir
from google.adk.tools.mcp_tool.mcp_toolset import (
    SseConnectionParams,
    StreamableHTTPConnectionParams,
)
from agent.caching_mcp_toolset import CachingMCPToolset
from google.adk.tools.skill_toolset import SkillToolset
from agent.agent import create_agent, _llm  # noqa: F401


class _NonEmptyLocalCodeExecutor(UnsafeLocalCodeExecutor):
    """UnsafeLocalCodeExecutor that guarantees non-empty stdout.

    Anthropic rejects messages with empty text content blocks.
    ADK sends the code execution stdout as a text block — if the script
    produces no output the request fails with:
      "messages: text content blocks must contain non-whitespace text"

    This subclass ensures stdout always has at least one printable character.
    """

    def execute_code(
        self,
        invocation_context: InvocationContext,
        code_execution_input: CodeExecutionInput,
    ) -> CodeExecutionResult:
        result = super().execute_code(invocation_context, code_execution_input)
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Anthropic requires at least one non-whitespace character in every
        # text content block.  If the script produced nothing, synthesize a
        # minimal message so the conversation can continue.
        if not stdout.strip() and not stderr.strip():
            stdout = '{"status": "success", "stdout": "", "note": "Script completed silently. Use print() to output data."}'
        elif not stdout.strip() and stderr.strip():
            # stderr only — promote it so it's visible to the LLM
            stdout = "[stderr] " + stderr.strip()
            stderr = ""

        return CodeExecutionResult(stdout=stdout, stderr=stderr, output_files=result.output_files)
from app.config import get_settings
from app.hooks import (
    after_tool_handler,
    commit_pending_observations,
    inject_pending_observations,
    on_tool_error_handler,
    trim_session_history,
)
from app.request_context import get_user_time_context
from app.services.agent_instruction import load_agent_instruction
from app.tools.auth_tool import pingfed_token, pingfed_hub

log = logging.getLogger(__name__)

_AGENT_DESCRIPTION = (
    "WCNP health and dependency intelligence assistant. "
    "Answers questions about Kubernetes namespace health, app health, "
    "dependencies, Cassandra, Cosmos DB, SQL Server, and Prometheus metrics."
)


def _inject_time_context(callback_context, llm_request) -> None:
    """ADK before_model_callback — prepend user timezone + epoch ms to system instruction.

    Reads the IANA timezone and browser epoch ms captured from the HTTP request
    headers (x-user-timezone / x-current-epoch-ms) by _LLMHeaderContextBuilder
    and stored in contextvars by _before_agent in factory.py.

    Fires before every LLM API call so the model can correctly convert
    natural-language times like "2AM to 10AM" to UTC epoch ms.

    Returns None to continue normal ADK execution.
    """
    timezone, epoch_ms = get_user_time_context()
    if not timezone and not epoch_ms:
        return None

    utc_str = ""
    if epoch_ms:
        try:
            from datetime import datetime, timezone as _tz
            utc_str = datetime.fromtimestamp(
                int(epoch_ms) / 1000, tz=_tz.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    time_block = (
        f"[System Time Context: User timezone={timezone or 'unknown'}, "
        f"UTC={utc_str or 'unknown'}, Epoch ms={epoch_ms or 'unknown'}]\n"
        "When the user refers to times like '2AM to 10AM' or 'today', "
        "interpret them in the above timezone and convert to UTC epoch ms before "
        "calling any tool that accepts time range parameters.\n\n"
    )

    if hasattr(llm_request, "messages") and llm_request.messages:
        last_msg = llm_request.messages[-1]
        is_user = False
        if isinstance(last_msg, dict) and last_msg.get("role") == "user":
            is_user = True
            content = last_msg.get("content", "")
            if isinstance(content, str):
                last_msg["content"] = time_block + content
            elif isinstance(content, list):
                last_msg["content"].insert(0, {"type": "text", "text": time_block})
        elif hasattr(last_msg, "role") and last_msg.role == "user":
            is_user = True
            if isinstance(last_msg.content, str):
                last_msg.content = time_block + last_msg.content
            elif isinstance(last_msg.content, list):
                last_msg.content.insert(0, {"type": "text", "text": time_block})
        
        if not is_user:
            llm_request.append_instructions([time_block])
    else:
        llm_request.append_instructions([time_block])
    log.debug(
        "_inject_time_context: timezone=%r utc=%r epoch_ms=%r",
        timezone, utc_str, epoch_ms,
    )
    return None


def _load_skills(skills_dir: str) -> list:
    """Load all skills from the given directory.

    Each subdirectory must contain a SKILL.md file with valid frontmatter.
    Skips invalid/missing skill dirs with a warning instead of aborting startup.
    Skill folders listed in ``EXCLUDE_SKILLS`` (comma-separated) are skipped.

    Args:
        skills_dir: Path to the directory containing skill subdirectories.
                    Relative paths are resolved from the project root.

    Returns:
        List of loaded Skill model instances.
    """
    from app.config import get_settings
    _s = get_settings()

    # Parse excluded skill folder names from config
    excluded: set[str] = {
        name.strip() for name in _s.exclude_skills.split(",") if name.strip()
    }
    if excluded:
        log.info("Excluding skills: %s", ", ".join(sorted(excluded)))

    project_root = Path(__file__).parents[2]
    skills_path = Path(skills_dir)
    if not skills_path.is_absolute():
        skills_path = project_root / skills_path

    if not skills_path.is_dir():
        log.warning("Skills directory not found: %s — SkillToolset disabled", skills_path)
        return []

    skills = []
    seen_names: dict[str, str] = {}  # skill.name → directory name (for duplicate detection)
    try:
        children = sorted(skills_path.iterdir())
    except OSError as exc:
        log.warning("Cannot read skills directory %s: %s — SkillToolset disabled", skills_path, exc)
        return []

    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in excluded:
            log.info("Skipping excluded skill: %s", child.name)
            continue
        try:
            skill = _load_skill_from_dir(child)
            skill_name = getattr(skill, "name", None) or child.name

            # ── Duplicate detection ──────────────────────────────────────────
            if skill_name in seen_names:
                log.warning(
                    "Duplicate skill name %r found in %s (first seen in %s) — skipping duplicate",
                    skill_name, child.name, seen_names[skill_name],
                )
                continue

            # metadata is a dict — use .get() not attribute access
            additional_count = len(skill.frontmatter.metadata.get("adk_additional_tools") or [])
            seen_names[skill_name] = child.name
            skills.append(skill)
            log.info("Loaded skill: %s (%d additional_tools)", skill.name, additional_count)
        except Exception as exc:
            log.warning("Skipping skill dir %s: %s", child.name, exc)

    return skills


async def make_agent(
    toolsets: list,
    guide: str = "",
    mcp_pool=None,
    remote_agent_tools: list | None = None,
) -> Agent:
    """Create the ADK agent with the given MCPToolset instances and optional A2A subagents.

    Called by factory.py after MCP server configs and A2A subagents are loaded from Redis.

    Args:
        toolsets:            List of MCPToolset (or any ADK-compatible tool) objects.
        guide:               AGENT.md content loaded from the MCP at startup — injected
                             into the system instruction so the agent knows the routing table.
        mcp_pool:            MCPPool instance used to call MCP prompts on-demand.
        remote_agent_tools:  List of async FunctionTool callables wrapping remote A2A
                             subagents (built by make_remote_agent_tool in factory.py).
                             Each tool delegates a query to its subagent via A2A 0.3
                             message/send JSON-RPC and returns the text response.
                             Pass None or [] when no subagents are registered.
    """
    instruction = await load_agent_instruction()
    if guide:
        instruction = f"{instruction}\n\n---\n\n{guide}"

    # Append A2UI structured-UI instructions when enabled
    s = get_settings()
    if s.a2ui_enabled:
        from agent.a2ui import generate_a2ui_instruction
        a2ui_instruction = generate_a2ui_instruction()
        instruction = f"{instruction}\n\n---\n\n{a2ui_instruction}"
        log.info("A2UI enabled — structured UI instruction appended to agent prompt")

    # Build the get_mcp_prompt tool so the agent can load use-case workflows on demand
    extra_tools = []
    if mcp_pool is not None:
        async def get_mcp_prompt(name: str, arguments: str = "{}") -> str:
            """Load a named MCP workflow prompt to get structured guidance for a specific use case.

            Call this when you need detailed step-by-step instructions for a domain task
            (e.g. diagnosing CPU issues, triaging an incident, visualizing metrics).
            The prompt name comes from the routing table in the agent guide above.

            Args:
                name:      Prompt name from the routing table (e.g. 'wcnp-full-triage').
                arguments: JSON string of key/value arguments the prompt requires
                           (e.g. '{"namespace": "iro-prod", "app": "item-assembler-async"}').
            Returns:
                Rendered workflow instructions for the use case.
            """
            import json as _json
            try:
                args = _json.loads(arguments) if arguments.strip() else {}
            except Exception:
                args = {}
            return await mcp_pool.call_prompt(name, args)

        extra_tools.append(get_mcp_prompt)
        log.info("Wired get_mcp_prompt tool — agent can load use-case workflows on demand")

    # ── SkillToolset — file-based skill system (ADK 1.28 experimental) ────────
    # Skills live in the skills/ directory at project root.  Each skill provides
    # SKILL.md instructions that guide the LLM on which tools to use.
    skill_toolset = None
    if s.skills_dir:
        skills = _load_skills(s.skills_dir)
        if skills:
            try:
                if s.enable_mcps:
                    # ENABLE_MCPS=true (default):
                    # MCP tools are registered globally (below) so the agent can
                    # call any MCP tool directly — even without loading a skill.
                    # SkillToolset only provides skill management tools.
                    # We do NOT pass toolsets as additional_tools to avoid
                    # duplicate declarations (Anthropic rejects duplicates).
                    # The adk_additional_tools in SKILL.md still guides the LLM
                    # on which MCP tools to use for that workflow.
                    skill_toolset = SkillToolset(
                        skills=skills,
                        code_executor=_NonEmptyLocalCodeExecutor(timeout_seconds=120),
                    )
                    log.info(
                        "SkillToolset enabled — %d skills loaded, "
                        "ENABLE_MCPS=true → MCP tools available globally",
                        len(skills),
                    )
                else:
                    # ENABLE_MCPS=false:
                    # MCP tools are ONLY available through skills.  The
                    # SkillToolset gates access via adk_additional_tools — the
                    # agent must load_skill() first to unlock MCP tools.
                    skill_toolset = SkillToolset(
                        skills=skills,
                        code_executor=_NonEmptyLocalCodeExecutor(timeout_seconds=120),
                        additional_tools=toolsets,
                    )
                    log.info(
                        "SkillToolset enabled — %d skills loaded (with %d MCP toolsets), "
                        "ENABLE_MCPS=false → MCP tools gated behind skills",
                        len(skills), len(toolsets),
                    )
            except Exception as exc:
                log.error(
                    "SkillToolset construction failed — skills disabled: %s", exc,
                    exc_info=True,
                )
                skill_toolset = None

            # ── Register skill aliases from SKILL.md metadata ────────────
            # If a skill's frontmatter has  metadata.aliases: [a, b, c]
            # we register each alias so load_skill("a") resolves to the
            # canonical skill.  Aliases never overwrite existing names.
            if skill_toolset is not None:
                for skill in skills:
                    aliases = (
                        skill.frontmatter.metadata.get("aliases", [])
                        if skill.frontmatter and skill.frontmatter.metadata
                        else []
                    )
                    for alias in aliases:
                        if alias in skill_toolset._skills:
                            log.debug(
                                "Alias %r for skill %r skipped — name already taken",
                                alias, skill.name,
                            )
                        else:
                            skill_toolset._skills[alias] = skill_toolset._skills[skill.name]
                            log.info(
                                "Registered alias %r → skill %r",
                                alias, skill.name,
                            )

    # ── Assemble final tools list ────────────────────────────────────────────
    all_tools: list = [*extra_tools, *(remote_agent_tools or []), pingfed_token, pingfed_hub]

    if s.enable_mcps:
        # ENABLE_MCPS=true: MCP tools available globally (backward-compatible).
        # Skills enhance routing with focused instructions but don't gate access.
        all_tools.extend(toolsets)
    else:
        # ENABLE_MCPS=false: MCP tools live inside SkillToolset only.
        # If SkillToolset failed to construct, fall back to global registration
        # so the agent isn't left without any MCP tools.
        if skill_toolset is None:
            log.warning(
                "ENABLE_MCPS=false but SkillToolset is unavailable — "
                "falling back to global MCP tool registration"
            )
            all_tools.extend(toolsets)

    if skill_toolset is not None:
        all_tools.append(skill_toolset)

    # ── Dynamic skill auto-loader (before_tool_callback) ─────────────────────
    # The skill-builder meta-skill writes new skill directories to
    # /tmp/dynamic-skills/<name>/.  This callback scans that directory before
    # every tool call and hot-registers any new skills into SkillToolset._skills
    # so `load_skill("dynamic-xyz")` resolves immediately.
    _dynamic_skills_dir = Path("/tmp/dynamic-skills")

    def _auto_load_dynamic_skills(tool, args, tool_context):
        """before_tool_callback: hot-load skills from /tmp/dynamic-skills/."""
        if skill_toolset is None or not _dynamic_skills_dir.is_dir():
            return None  # continue normally — nothing to load

        try:
            for child in _dynamic_skills_dir.iterdir():
                if (
                    child.is_dir()
                    and child.name.startswith("dynamic-")
                    and child.name not in skill_toolset._skills
                    and (child / "SKILL.md").is_file()
                ):
                    try:
                        skill = _load_skill_from_dir(child)
                        skill_toolset._skills[skill.name] = skill
                        log.info("Auto-loaded dynamic skill: %s", skill.name)
                    except Exception as exc:
                        log.warning(
                            "Failed to auto-load dynamic skill %s: %s",
                            child.name, exc,
                        )
        except OSError as exc:
            log.debug("Dynamic skills dir scan failed: %s", exc)

        return None  # always continue — never short-circuit the tool call

    log.info(
        "Agent tools assembled — %d global entries (%d MCP toolsets, "
        "skill_toolset=%s, enable_mcps=%s)",
        len(all_tools), len(toolsets), skill_toolset is not None, s.enable_mcps,
    )

    return Agent(
        model=_llm,
        name="query_agent",
        description=_AGENT_DESCRIPTION,
        instruction=instruction,
        tools=all_tools,
        # Order matters: trim first so we don't waste time priming pending
        # observations into events that are about to be dropped; then inject
        # so the LLM sees the freshest out-of-band context for this turn.
        before_agent_callback=[trim_session_history, inject_pending_observations],
        # after_agent fires only when the turn completes normally.  We use it
        # to promote the "pending" lifecycle HWM staged by
        # inject_pending_observations — if the LLM call failed, this callback
        # is skipped and the next turn re-drains the same observations.
        after_agent_callback=commit_pending_observations,
        before_model_callback=_inject_time_context,
        before_tool_callback=_auto_load_dynamic_skills,
        after_tool_callback=after_tool_handler,
        on_tool_error_callback=on_tool_error_handler,
        # Enable Python code execution — LLM writes ```python blocks,
        # ADK executes them in a spawned subprocess and feeds stdout back.
        # 120s allows HTTP calls to external REST APIs for data fetching.
        # _NonEmptyLocalCodeExecutor ensures stdout is never empty so Anthropic
        # never rejects the response with "text content blocks must contain
        # non-whitespace text".
        code_executor=_NonEmptyLocalCodeExecutor(timeout_seconds=120),
    )


# ── Dev-only: root_agent for `adk web` ───────────────────────────────────────
# Loaded from MCP discovery (YAML file in dev mode) so `adk web` works
# without Redis.  NOT used by the FastAPI server — factory.py calls make_agent()
# with Redis-loaded toolsets instead.

def _conn_params_from_discovery():
    """Build MCPToolset list from mcp/client.py file-based discovery for `adk web` dev usage."""
    s = get_settings()
    toolsets = []

    # Only works in local mode with a local YAML file
    if s.agent_env.lower() != "local" or not s.mcp_servers_file:
        log.info("[adk web] Not in local mode or MCP_SERVERS_FILE not set — root_agent has no MCP tools")
        return toolsets

    try:
        from app.mcp.client import _load_from_file, _validate_and_parse

        entries = _load_from_file(s.mcp_servers_file)
        configs = _validate_and_parse(entries, source=s.mcp_servers_file)

        for cfg in configs:
            params = (
                StreamableHTTPConnectionParams(url=cfg.url, headers=cfg.headers)
                if cfg.transport == "streamable_http"
                else SseConnectionParams(url=cfg.url, headers=cfg.headers)
            )
            toolsets.append(CachingMCPToolset(connection_params=params))
            log.info("[adk web] MCP server: name=%r url=%r transport=%r", cfg.name, cfg.url, cfg.transport)

    except Exception as exc:
        # Banner already logged by load_mcp_servers / _load_from_file
        log.error("[adk web] MCP discovery failed — root_agent has no MCP tools")

    return toolsets


try:
    root_agent = asyncio.run(make_agent(_conn_params_from_discovery()))
except RuntimeError:
    # asyncio.run() cannot be called from a running event loop (e.g. uvicorn startup).
    # In that case root_agent is not needed — factory.py calls make_agent() directly.
    root_agent = None

__all__ = ["make_agent", "root_agent"]
