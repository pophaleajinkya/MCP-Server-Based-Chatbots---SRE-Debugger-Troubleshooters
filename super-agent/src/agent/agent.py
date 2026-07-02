"""
Google ADK Agent — OpenAI / Element Gateway + full MCP support.

MCP primitives supported:
  ✅ Tools     — loaded via MCPToolset, injected into agent.tools
  ✅ Resources — exposed as a `read_mcp_resource(uri)` FunctionTool
  ✅ Prompts   — exposed as a `get_mcp_prompt(name, arguments)` FunctionTool
                 + base prompt templates injected into agent instruction at startup

Usage:
    agent, exit_stack, mcp_session = await create_agent()
    # ... serve requests ...
    await exit_stack.aclose()   # cleanly disconnects all MCP connections
"""

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

import litellm
# verify=False is intentional: internal Walmart gateway services use self-signed certs
litellm.ssl_verify = False  # noqa: S501
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

from app.request_context import get_llm_headers, push_llm_event
from google.adk.tools.mcp_tool.mcp_toolset import SseConnectionParams, StreamableHTTPConnectionParams
from agent.caching_mcp_toolset import CachingMCPToolset

# Raw MCP client (used for Resources + Prompts alongside MCPToolset for Tools)
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from mcp import types as mcp_types

from app.config import get_settings
from app.tools.auth_tool import pingfed_token

log = logging.getLogger(__name__)


log.info("ADK session manager — using native session handling (ADK >= 1.20)")

# Populated from settings after _s is initialised (see bottom of module-level setup).
# Exposed as a module-level name so _shrink_for_retry (a static method) can read it
# without needing a Settings import inside a hot path.
_SHRINK_TOOL_RESULT_MAX_CHARS: int = 1500  # overwritten below once _s is available


# ── Per-request header injection via LiteLLMClient wrapper ────────────────────
#
# The ADK LiteLlm model is created once at startup and reused for all requests.
# Its extra_headers (stored in _additional_args) are static — set at init time.
#
# To inject per-request wm_llm_gw.* headers (captured by the FastAPI middleware
# and stored in contextvars), we wrap the LiteLLMClient used by the LiteLlm model.
# Our wrapper reads headers from the current async context and merges them into
# the `extra_headers` kwarg BEFORE calling litellm.acompletion(), where they are
# properly merged into the outbound HTTP request.
#
# This is the correct injection point — litellm.acompletion(extra_headers=...)
# flows through to the Anthropic/OpenAI provider's HTTP call. Unlike the
# log_pre_api_call() callback (which is a read-only logging hook), modifications
# to kwargs here actually affect the outbound request.


class _HeaderInjectingClient(LiteLLMClient):
    """LiteLLMClient wrapper that injects per-request WM_LLM_GW.* headers.

    Intercepts acompletion() and completion() calls to merge headers from
    the current async context (set by LLMHeaderMiddleware in factory.py)
    into the extra_headers parameter before delegating to the real LiteLLM call.
    """

    def _merge_llm_headers(self, kwargs: dict) -> dict:
        """Merge per-request LLM Gateway headers into kwargs['extra_headers']."""
        llm_headers = get_llm_headers()
        if llm_headers:
            existing = kwargs.get("extra_headers") or {}
            kwargs["extra_headers"] = {**existing, **llm_headers}
            log.debug("Injected LLM Gateway headers: %s", list(llm_headers.keys()))
        return kwargs

    def _log_caching_status(self, model: str, messages: list, kwargs: dict) -> None:
        """Log whether Anthropic prompt caching is active for this call.

        Caching requires both:
          1. ``anthropic-beta: prompt-caching-2024-07-31`` header in the request
          2. ``cache_control`` blocks inside system/user message content
        """
        if not (isinstance(model, str) and "anthropic" in model.lower()):
            return

        headers = kwargs.get("extra_headers") or {}
        beta_header = headers.get("anthropic-beta", "")
        _CACHE_BETA_HEADERS = ("prompt-caching-2024-07-31", "extended-cache-ttl-2025-04-11")
        beta_active = beta_header in _CACHE_BETA_HEADERS

        cache_control_locs: list[str] = []
        for i, msg in enumerate(messages or []):
            content = msg.get("content", "")
            if isinstance(content, list):
                for j, block in enumerate(content):
                    if isinstance(block, dict) and block.get("cache_control"):
                        cache_control_locs.append(
                            f"messages[{i}].content[{j}] role={msg.get('role','?')}"
                        )

        if beta_active and cache_control_locs:
            log.info(
                "Anthropic prompt caching: ACTIVE — beta_header=%r, cache_control found at: %s",
                beta_header, cache_control_locs,
            )
        elif beta_active:
            log.warning(
                "Anthropic prompt caching: beta header present (%r) but NO cache_control blocks "
                "found in messages — caching will not activate",
                beta_header,
            )
        elif cache_control_locs:
            log.warning(
                "Anthropic prompt caching: cache_control blocks found (%s) but "
                "anthropic-beta header is MISSING — caching will not activate",
                cache_control_locs,
            )
        else:
            log.debug("Anthropic prompt caching: NOT active (no beta header, no cache_control blocks)")

    @staticmethod
    def _inject_cache_control(messages: list) -> list:
        """Mark the system message and the MOST RECENT user message for Anthropic prompt caching.

        Anthropic allows up to 4 cache breakpoints. We mark:
        1. The system message (which contains the massive tool schemas).
        2. The LAST user message (which caches the entire conversation history up to the current turn).

        Converts::

            {"role": "system", "content": "You are ..."}

        into::

            {"role": "system", "content": [
                {"type": "text", "text": "You are ...",
                 "cache_control": {"type": "ephemeral"}}
            ]}
        """
        result = []
        last_user_idx = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_idx = i

        for i, msg in enumerate(messages):
            if msg.get("role") == "system" or i == last_user_idx:
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    msg = {
                        **msg,
                        "content": [
                            {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                        ],
                    }
                elif isinstance(content, list) and content:
                    last = content[-1]
                    if isinstance(last, dict) and not last.get("cache_control"):
                        msg = {
                            **msg,
                            "content": content[:-1] + [{**last, "cache_control": {"type": "ephemeral"}}],
                        }
            result.append(msg)
        return result

    @staticmethod
    def _sanitize_messages(messages: list) -> list:
        """Remove empty text content blocks from messages.

        Anthropic rejects requests where any text content block is empty or
        whitespace-only: "messages: text content blocks must contain
        non-whitespace text".

        This can happen when:
        - A code execution step produced no stdout and an earlier version of
          the code executor didn't guarantee non-empty output.
        - ADK stored the empty result in session history; on the next request
          the history is replayed, hitting the same Anthropic validation.

        This sanitiser is applied on every LLM call so stale session history
        never causes a 400 error.
        """
        cleaned: list = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                # Filter individual blocks — keep non-text blocks and non-empty text blocks
                filtered = [
                    block for block in content
                    if not (
                        isinstance(block, dict)
                        and block.get("type") == "text"
                        and not str(block.get("text", "")).strip()
                    )
                ]
                if not filtered:
                    # Message has no content after filtering — skip it entirely
                    log.debug("_sanitize_messages: dropped empty message role=%s", msg.get("role"))
                    continue
                if len(filtered) != len(content):
                    log.debug(
                        "_sanitize_messages: removed %d empty text block(s) from role=%s",
                        len(content) - len(filtered), msg.get("role"),
                    )
                    msg = {**msg, "content": filtered}
            elif isinstance(content, str) and not content.strip():
                log.debug("_sanitize_messages: dropped empty string message role=%s", msg.get("role"))
                continue
            cleaned.append(msg)
        return cleaned

    @staticmethod
    def _shrink_for_retry(messages: list) -> list:
        """Aggressively shrink messages after a ContextWindowExceededError.

        Strategy:
          1. Keep system prompt(s) as-is.
          2. Keep only the LAST user turn + its following messages — drop all prior turns.
          3. Truncate large tool-result content blocks to _SHRINK_TOOL_RESULT_MAX_CHARS chars.
          4. Prepend a context-loss notice to the current user message.
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system  = [m for m in messages if m.get("role") != "system"]

        user_indices = [i for i, m in enumerate(non_system) if m.get("role") == "user"]

        dropped_turns = 0
        if len(user_indices) > 1:
            keep_from     = user_indices[-1]
            dropped_turns = keep_from
            non_system    = non_system[keep_from:]
            log.warning(
                "_shrink_for_retry: dropped %d older message(s) to fit context window",
                dropped_turns,
            )

        def _truncate_text(text: str) -> str:
            if len(text) <= _SHRINK_TOOL_RESULT_MAX_CHARS:
                return text
            return (
                text[:_SHRINK_TOOL_RESULT_MAX_CHARS]
                + f"\n\n[... {len(text) - _SHRINK_TOOL_RESULT_MAX_CHARS} chars truncated to fit context window ...]"
            )

        def _truncate_content(content):
            if isinstance(content, str):
                return _truncate_text(content)
            if isinstance(content, list):
                result = []
                for block in content:
                    if not isinstance(block, dict):
                        result.append(block)
                        continue
                    block = dict(block)
                    if "text" in block and isinstance(block["text"], str):
                        block["text"] = _truncate_text(block["text"])
                    if "content" in block:
                        block["content"] = _truncate_content(block["content"])
                    result.append(block)
                return result
            return content

        shrunk: list = []
        for i, msg in enumerate(non_system):
            role    = msg.get("role", "")
            content = msg.get("content")

            # Truncate tool/function result messages
            if role in ("tool", "function"):
                msg = {**msg, "content": _truncate_content(content)}

            # Prepend context-loss notice to the current (first kept) user message
            if role == "user" and i == 0 and dropped_turns > 0:
                notice = (
                    "[Note: earlier conversation turns were dropped because the context window "
                    "was exceeded. Only the current query is shown below.]\n\n"
                )
                if isinstance(content, str):
                    msg = {**msg, "content": notice + content}
                elif isinstance(content, list):
                    first_text_idx = next(
                        (j for j, b in enumerate(content) if isinstance(b, dict) and b.get("type") == "text"),
                        None,
                    )
                    if first_text_idx is not None:
                        blocks = list(content)
                        blocks[first_text_idx] = {
                            **blocks[first_text_idx],
                            "text": notice + str(blocks[first_text_idx].get("text", "")),
                        }
                        msg = {**msg, "content": blocks}

            shrunk.append(msg)

        log.warning(
            "_shrink_for_retry: retry context → %d system + %d non-system messages",
            len(system_msgs), len(shrunk),
        )
        return system_msgs + shrunk

    # Heuristic: if the total message payload is above this threshold (chars) and
    # Anthropic returns a generic 400 Bad Request, treat it as a context-overflow.
    # Walmart's LLM Gateway strips Anthropic's original error details, so we can't
    # rely on error-message keyword matching.  A large payload + 400 is almost
    # always "prompt is too long".
    _CONTEXT_OVERFLOW_CHAR_THRESHOLD = 50_000

    def _estimate_payload_chars(self, messages: list) -> int:
        """Cheaply estimate total character count across all message content."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block.get("text", "")))
                        total += len(str(block.get("content", "")))
        return total

    def _is_likely_context_overflow(self, exc: Exception, messages: list) -> bool:
        """Detect whether a BadRequestError is probably a context-window overflow.

        Checks:
          1. Known LiteLLM context-window keywords in the error string.
          2. Heuristic: payload is large + Anthropic returned generic 400.
        """
        err = str(exc).lower()
        _CONTEXT_KEYWORDS = (
            "prompt is too long",
            "prompt: length",
            "context length",
            "maximum context",
            "too many tokens",
            "request too large",
            "payload size exceeds",
            "content length exceeds",
        )
        if any(kw in err for kw in _CONTEXT_KEYWORDS):
            return True
        # Walmart LLM Gateway strips Anthropic's original error → generic "Bad Request".
        # If the payload is large, a 400 is almost certainly context overflow.
        if self._estimate_payload_chars(messages) > self._CONTEXT_OVERFLOW_CHAR_THRESHOLD:
            log.info(
                "BadRequestError with large payload (%d chars) — treating as context overflow",
                self._estimate_payload_chars(messages),
            )
            return True
        return False

    async def _shrink_and_retry(self, model, messages, tools, **kwargs):
        """Shrink context and retry once.  Emits UI progress events via the bridge."""
        push_llm_event({
            "type": "progress",
            "tool": "context_management",
            "call_id": "context_shrink",
            "label": "⚠️ Context window exceeded — optimizing conversation history",
            "category": "system",
            "status": "running",
        })
        shrunk = self._shrink_for_retry(messages)
        if _s.llm_prompt_cache_enabled and _s.claude_is_primary_llm:
            shrunk = self._inject_cache_control(shrunk)
        try:
            result = await super().acompletion(model, shrunk, tools, **kwargs)
            push_llm_event({
                "type": "progress",
                "tool": "context_management",
                "call_id": "context_shrink",
                "label": "✅ Context optimized — continuing",
                "category": "system",
                "status": "done",
            })
            return result
        except (litellm.ContextWindowExceededError, litellm.BadRequestError):
            push_llm_event({
                "type": "progress",
                "tool": "context_management",
                "call_id": "context_shrink",
                "label": "❌ Context still too large after optimization",
                "category": "system",
                "status": "error",
            })
            raise

    async def acompletion(self, model, messages, tools, **kwargs):
        """Async completion with header injection, optional prompt caching,
        extended thinking, and automatic context-shrink + single retry on
        context-overflow errors.

        Handles two flavours of context-window overflow:
          1. ``litellm.ContextWindowExceededError`` — clean identification by LiteLLM.
          2. ``litellm.BadRequestError`` with a large payload — Walmart's LLM Gateway
             strips Anthropic's original error details, returning a generic 400.
             We use a heuristic (payload size) to detect this case.
        """
        kwargs   = self._merge_llm_headers(kwargs)
        messages = self._sanitize_messages(messages)
        if _s.llm_prompt_cache_enabled and _s.claude_is_primary_llm:
            messages = self._inject_cache_control(messages)
        self._log_caching_status(model, messages, kwargs)

        # ── Extended thinking ────────────────────────────────────────────────
        # When enabled, Claude returns thinking blocks (chain-of-thought) that
        # ADK's LiteLLM integration converts to Part(thought=True) objects.
        # These are surfaced to the UI as SSE events by the runner.
        if _s.llm_extended_thinking_enabled and _s.claude_is_primary_llm:
            _budget = _s.llm_thinking_budget_tokens
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": _budget,
            }
            # Ensure max_tokens exceeds the thinking budget (Anthropic requirement).
            # LiteLLM auto-calculates this, but being explicit avoids edge cases.
            if "max_tokens" not in kwargs and "max_completion_tokens" not in kwargs:
                kwargs["max_tokens"] = _budget + 4096
            log.info(
                "Extended thinking ENABLED — budget_tokens=%d  max_tokens=%s  stream=%s",
                _budget,
                kwargs.get("max_tokens", kwargs.get("max_completion_tokens", "auto")),
                kwargs.get("stream", False),
            )

        try:
            return await super().acompletion(model, messages, tools, **kwargs)

        except litellm.ContextWindowExceededError as exc:
            log.warning(
                "ContextWindowExceededError (%d messages) — shrinking and retrying. Error: %s",
                len(messages), exc,
            )
            return await self._shrink_and_retry(model, messages, tools, **kwargs)

        except litellm.BadRequestError as exc:
            if self._is_likely_context_overflow(exc, messages):
                log.warning(
                    "BadRequestError likely context overflow (%d messages) — shrinking and retrying. Error: %s",
                    len(messages), exc,
                )
                return await self._shrink_and_retry(model, messages, tools, **kwargs)
            # Not a context overflow — emit a progress event and re-raise
            push_llm_event({
                "type": "progress",
                "tool": "llm_error",
                "call_id": "bad_request",
                "label": "❌ LLM Bad Request (400)",
                "category": "system",
                "status": "error",
            })
            raise

    def completion(self, model, messages, tools, stream=False, **kwargs):
        """Sync/streaming completion with per-request header injection."""
        kwargs   = self._merge_llm_headers(kwargs)
        messages = self._sanitize_messages(messages)
        return super().completion(model, messages, tools, stream=stream, **kwargs)


log.info("_HeaderInjectingClient ready — WM_LLM_GW headers will be injected per-request")


# ── Model configuration ──────────────────────────────────────────────────────
#
# When CLAUDE_IS_PRIMARY_LLM=true, uses Walmart Stage Gateway (Anthropic):
#   POST CLAUDE_GATEWAY_URL  (full /messages endpoint)
#   Required: CLAUDE_API_KEY, CLAUDE_MODEL, CLAUDE_ANTHROPIC_VERSION
#
# Otherwise, uses Walmart Element Gateway (Azure OpenAI-compatible):
#   POST {ELEMENT_GATEWAY_BASE_URL}/deployments/{model}/chat/completions?api-version={version}
#   Required: ELEMENT_GATEWAY_BASE_URL, ELEMENT_GATEWAY_API_KEY, OPENAI_MODEL

_s = get_settings()

# Override module-level constant from settings so it can be tuned via .env
# without a code change.  SHRINK_TOOL_RESULT_MAX_CHARS=2000 in .env doubles
# the per-tool-result budget; set to 500 for very aggressive truncation.
_SHRINK_TOOL_RESULT_MAX_CHARS = _s.shrink_tool_result_max_chars
log.info("_SHRINK_TOOL_RESULT_MAX_CHARS=%d (from SHRINK_TOOL_RESULT_MAX_CHARS env)", _SHRINK_TOOL_RESULT_MAX_CHARS)

if _s.claude_is_primary_llm:
    # LiteLlm appends /v1/messages to api_base — strip both variants so the
    # path resolves correctly: .../v1/messages → .../wmtllmgateway (no /v1).
    _claude_base = _s.claude_gateway_url.removesuffix("/v1/messages").removesuffix("/messages")
    _claude_extra_headers: dict = {"anthropic-version": _s.claude_anthropic_version}

    # ── anthropic-beta header ────────────────────────────────────────────
    # Combine all required beta features into a single comma-separated header.
    _beta_features: list[str] = []
    if _s.llm_prompt_cache_enabled:
        if _s.llm_prompt_cache_extended:
            _beta_features.append("extended-cache-ttl-2025-04-11")
            log.info("Anthropic prompt caching ENABLED — extended TTL (~1 hour)")
        else:
            _beta_features.append("prompt-caching-2024-07-31")
            log.info("Anthropic prompt caching ENABLED — default TTL (~5 minutes)")
    if _s.llm_extended_thinking_enabled:
        _beta_features.append("interleaved-thinking-2025-05-14")
        log.info("Anthropic extended thinking beta header ENABLED")
    if _beta_features:
        _claude_extra_headers["anthropic-beta"] = ",".join(_beta_features)
    _llm = LiteLlm(
        model=f"anthropic/{_s.claude_model}",
        api_key=_s.claude_api_key,
        api_base=_claude_base,
        extra_headers=_claude_extra_headers,
    )
    log.info("LLM: anthropic/%s via Stage Gateway (%s)", _s.claude_model, _claude_base)
else:
    # LiteLLM azure model auto-appends /openai/deployments/{model}/... to api_base.
    # Strip the trailing /openai from the gateway URL to avoid a duplicate path.
    _litellm_base = _s.element_gateway_base_url.removesuffix("/openai")

    _llm = LiteLlm(
        model=f"azure/{_s.openai_model}",
        api_key=_s.element_gateway_api_key,
        api_base=_litellm_base,
        api_version=_s.element_gateway_api_version,
        extra_headers={"api-key": _s.element_gateway_api_key} if _s.element_gateway_api_key else {},
    )
    log.info("LLM: azure/%s via Element Gateway (%s)", _s.openai_model, _litellm_base)

# Replace the default LiteLLMClient with our header-injecting wrapper so that
# every acompletion()/completion() call merges per-request wm_llm_gw.* headers.
_llm.llm_client = _HeaderInjectingClient()
log.info("LiteLLM client patched — per-request header injection active")


# ── MCP helpers ──────────────────────────────────────────────────────────────

def _mcp_env() -> dict | None:
    """Read MCP config from mcp/client.py discovery (YAML or Redis).

    Returns a single-server dict for backward-compat with create_agent().
    Prefer using load_mcp_servers() from app.mcp.client directly.
    Returns None if no MCP servers are configured.
    """
    try:
        from app.mcp.client import _load_from_file, _validate_and_parse
        s = get_settings()
        if s.agent_env.lower() == "local" and s.mcp_servers_file:
            entries = _load_from_file(s.mcp_servers_file)
            configs = _validate_and_parse(entries, source=s.mcp_servers_file)
            if configs:
                cfg = configs[0]
                return {"url": cfg.url, "headers": cfg.headers, "transport": cfg.transport}
        return None
    except Exception as exc:
        log.warning("MCP config discovery failed: %s — starting without MCP", exc)
        return None


async def _open_raw_session(cfg: dict, exit_stack: AsyncExitStack) -> ClientSession | None:
    """
    Open a raw MCP ClientSession (used for Resources + Prompts).
    Managed by exit_stack — no manual cleanup needed.
    Returns None if the connection fails.
    """
    try:
        read, write = await exit_stack.enter_async_context(
            sse_client(url=cfg["url"], headers=cfg["headers"])
        )
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        log.info("✅ Raw MCP session established (resources + prompts)")
        return session
    except Exception as exc:
        log.warning("⚠️  Raw MCP session failed (%s) — resources/prompts unavailable", exc)
        return None


# ── FunctionTool factories (closures over live MCP session) ──────────────────

def _make_resource_tool(session: ClientSession):
    """Returns an async function the ADK agent can call to read MCP resources."""

    async def read_mcp_resource(uri: str) -> str:
        """
        Read the content of a resource from the connected MCP server.

        Use this tool whenever the user asks about data, documents, or content
        that may be stored on the MCP server. Pass the full resource URI.

        Args:
            uri: The resource URI to read (e.g. 'file:///data/report.md').

        Returns:
            The text content of the resource.
        """
        try:
            result: mcp_types.ReadResourceResult = await session.read_resource(uri)
            parts = []
            for content in result.contents:
                if hasattr(content, "text"):
                    parts.append(content.text)
                elif hasattr(content, "blob"):
                    parts.append(f"[binary resource — base64 omitted, mimeType={content.mimeType}]")
            return "\n".join(parts) if parts else "[empty resource]"
        except Exception as exc:
            return f"Error reading resource '{uri}': {exc}"

    return read_mcp_resource


def _make_prompt_tool(session: ClientSession):
    """Returns an async function the ADK agent can call to render MCP prompt templates."""

    async def get_mcp_prompt(name: str, arguments: str = "{}") -> str:
        """
        Retrieve and render a prompt template from the connected MCP server.

        Use this when you need a structured prompt for a specific task and the
        MCP server provides a matching prompt template.

        Args:
            name:      The prompt template name (e.g. 'summarize', 'translate').
            arguments: JSON string of key/value arguments for the template
                       (e.g. '{"language": "Spanish", "text": "Hello"}').

        Returns:
            The rendered prompt messages as a formatted string.
        """
        try:
            args: dict[str, str] = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return f"Error: 'arguments' must be a valid JSON object string, got: {arguments!r}"

        try:
            result: mcp_types.GetPromptResult = await session.get_prompt(name, args)
            lines = [f"[Prompt: {result.description or name}]"] if (result.description or name) else []
            for msg in result.messages:
                role = msg.role
                text = msg.content.text if hasattr(msg.content, "text") else str(msg.content)
                lines.append(f"{role.upper()}: {text}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Error getting prompt '{name}': {exc}"

    return get_mcp_prompt


async def _load_prompt_summary(session: ClientSession) -> str:
    """
    List all available MCP prompts and return a brief summary string
    that gets appended to the agent's system instruction.
    """
    try:
        result: mcp_types.ListPromptsResult = await session.list_prompts()
        if not result.prompts:
            return ""
        lines = ["Available MCP prompt templates (use get_mcp_prompt tool):"]
        for p in result.prompts:
            desc = f" — {p.description}" if p.description else ""
            lines.append(f"  • {p.name}{desc}")
        return "\n" + "\n".join(lines)
    except Exception as exc:
        log.warning("Could not list MCP prompts: %s", exc)
        return ""


# ── Agent factory ────────────────────────────────────────────────────────────

async def create_agent() -> tuple[Agent, AsyncExitStack, ClientSession | None]:
    """
    Async factory — wires up the ADK agent with full MCP support.

    Opens two MCP connections (when MCP_SERVER_URL is set):
      1. MCPToolset connection  → loads Tools into agent.tools
      2. Raw ClientSession      → used for Resources + Prompts (FunctionTools + REST)

    Returns:
        (agent, exit_stack, mcp_session)
        Call `await exit_stack.aclose()` on shutdown.
        mcp_session is None when MCP is not configured or unreachable.
    """
    exit_stack = AsyncExitStack()
    tools: list[Any] = []
    mcp_session: ClientSession | None = None

    cfg = _mcp_env()

    if cfg:
        # ── 1. Tools via MCPToolset ──────────────────────────────────────────
        try:
            if cfg["transport"] == "streamable_http":
                conn_params = StreamableHTTPConnectionParams(
                    url=cfg["url"], headers=cfg["headers"], timeout=30,
                )
            else:
                conn_params = SseConnectionParams(
                    url=cfg["url"], headers=cfg["headers"],
                )
            mcp_toolset = CachingMCPToolset(connection_params=conn_params)
            mcp_tools = await exit_stack.enter_async_context(mcp_toolset)
            tools.extend(mcp_tools)
            log.info("✅ MCP Tools loaded (%d): %s", len(mcp_tools), [t.name for t in mcp_tools])
        except Exception as exc:
            log.warning("⚠️  MCPToolset failed (%s) — no MCP tools", exc)

        # ── 2. Resources + Prompts via raw ClientSession ─────────────────────
        mcp_session = await _open_raw_session(cfg, exit_stack)

        if mcp_session:
            # FunctionTools so the agent can call them autonomously
            tools.append(_make_resource_tool(mcp_session))
            tools.append(_make_prompt_tool(mcp_session))
            log.info("✅ MCP Resources + Prompts tools wired into agent")
    else:
        log.info("MCP_SERVER_URL not set — starting without MCP support")

    # ── Auth tool — always available regardless of MCP config ────────────────
    # pingfed_token is a native ADK FunctionTool. The LLM can call
    # it directly when a downstream service needs a bearer token, or when a
    # tool call returns 4XX indicating an expired token.
    # Future: move to a dedicated auth MCP server.
    tools.append(pingfed_token)
    log.info("✅ pingfed_token auth tool registered")

    # Build system instruction (+ prompt catalogue if available)
    base_instruction = (
        "You are a helpful, concise, and accurate assistant. "
        "Answer the user's question directly and clearly. "
        "Use the available tools whenever they can help. "
        "If you don't know something, say so honestly."
        "\n\n"
        "## Prompt Usage Rules\n"
        "Before rendering any chart — call get_mcp_prompt('wcnp-visualization-guide').\n"
        "Before writing any raw query for any provider — call get_mcp_prompt with the relevant prompt "
        "from the list below to get exact metric names, query patterns, and filters for that provider. "
        "PromQL requires EXACT metric names — a single character difference returns empty results. "
        "NEVER invent, guess, or modify metric names.\n"
    )
    if mcp_session:
        prompt_summary = await _load_prompt_summary(mcp_session)
        base_instruction += prompt_summary

    agent = Agent(
        model=_llm,
        name="query_agent",
        description=(
            "A general-purpose assistant using OpenAI/Element Gateway "
            "with full MCP support: Tools, Resources, and Prompts."
        ),
        instruction=base_instruction,
        tools=tools,
    )

    return agent, exit_stack, mcp_session
