"""
Centralised application configuration.

Reads from environment variables loaded via glob-based dotenv discovery so both
local .env* files and WCNP Akeyless secret files (mounted as /secrets/.env*)
are picked up automatically — matching the maof loading strategy.

SSL certs come from the Docker ca-roots image (REQUESTS_CA_BUNDLE env var).
No AkeyLess cert secret is required — mirrors the changeiq-agent pattern.
"""

import glob
import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

_cfg_log = logging.getLogger(__name__)

# Load all .env* files from current dir and /secrets (maof-compatible strategy).
# Excludes .env.test and .env.example to avoid polluting runtime with test/placeholder fixtures.
# If running from the src/ folder, also scan the parent directory for .env* files.
_all_env_files = glob.glob(".env*") + glob.glob("/secrets/.env*")
if Path(os.getcwd()).name == "src":
    _all_env_files += glob.glob("../.env*")
_EXCLUDED = {".env.test", ".env.example"}
_env_files = sorted(
    [f for f in _all_env_files if Path(f).name not in _EXCLUDED],
    key=lambda f: (Path(f).name != ".env", Path(f).name),  # .env always loads first
)

for _env_file in _env_files:
    _path = Path(_env_file)
    if _path.is_file():
        try:
            load_dotenv(dotenv_path=_path, override=True)
        except Exception as _exc:
            _cfg_log.exception("Failed to load env file %s: %s", _env_file, _exc)
        _cfg_log.info("[config] Loaded: %s", _env_file)


class Settings(BaseSettings):
    """All tuneable knobs for the A2A Health Agent.

    Field names map to uppercased env vars automatically (pydantic-settings
    convention): ``agent_host`` → ``AGENT_HOST``, etc.
    """

    # ── Server ────────────────────────────────────────────────────────────────
    agent_host: str = "0.0.0.0"
    agent_port: int = 8001

    # ── OpenAI / Walmart Element Gateway ──────────────────────────────────────
    element_gateway_base_url: str = ""
    element_gateway_api_key: str = ""
    element_gateway_api_version: str = "2024-10-21"
    openai_model: str = "gpt-4.1"

    # ── Claude / Walmart Stage Gateway ────────────────────────────────────────
    claude_gateway_url: str = ""
    claude_api_key: str = ""
    claude_model: str = "claude-opus-4-6"
    claude_anthropic_version: str = "vertex-2023-10-16"
    claude_is_primary_llm: bool = False

    # ── Secrets path ──────────────────────────────────────────────────────────
    secrets_path: str = "/secrets/"
    # ssl_ca_bundle_path removed — cert comes from Docker ca-roots image via
    # REQUESTS_CA_BUNDLE / SSL_CERT_FILE env vars (changeiq-agent pattern).

    # ── Redis session storage ─────────────────────────────────────────────────
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    redis_username: str = "appuser"
    redis_session_ttl_seconds: int = 604800  # 7 days

    # ── CORS / Trusted Hosts ──────────────────────────────────────────────────
    # Set via CORS_ALLOWED_ORIGINS / ALLOWED_HOSTS env vars (JSON arrays) in the
    # genAI redis-config akeyless secret alongside Redis credentials so both are
    # injected together at startup before any Redis connection is attempted.
    #
    # Override in .env.redis-config:
    #   CORS_ALLOWED_ORIGINS=["https://sre-ai.prod.walmart.com","https://sre-ai.stage.walmart.com"]
    #   ALLOWED_HOSTS=["sre-ai.prod.walmart.com","sre-ai.walmart.com","sre-ai.stage.walmart.com","sre-ai.dev.walmart.com"]
    cors_allowed_origins: list[str] = [
        "https://sre.ai.prod.walmart.com",
        "http://sre.ai.prod.walmart.com",
        "https://sre.ai.walmart.com",
        "http://sre.ai.walmart.com",
        "https://sre.ai.stage.walmart.com",
        "http://sre.ai.stage.walmart.com",
        "https://sre.ai.dev.walmart.com",
        "http://sre.ai.dev.walmart.com",
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    allowed_hosts: list[str] = [
        "sre.ai.prod.walmart.com",
        "sre.ai.walmart.com",
        "sre.ai.walmart.com",
        "sre.ai.stage.walmart.com",
        "sre.ai.dev.walmart.com",
        "maof-health-agent.prod.walmart.com",
        "maof-health-agent.stage.walmart.com",
        "maof-health-agent.dev.walmart.com",
        "maof-health-agent.walmart.com",
        "localhost",
        "127.0.0.1",
        # "testserver" is Starlette TestClient's default Host header value.
        # Required so TestClient calls are not rejected by TrustedHostMiddleware.
        "testserver",
    ]

    # ── A2UI (Agent-to-UI) ───────────────────────────────────────────────────
    a2ui_enabled: bool = False

    # ── Skills (ADK SkillToolset) ─────────────────────────────────────────────
    # Directory containing skill folders. Each subfolder must contain a SKILL.md.
    # Relative paths are resolved from the project root.
    # Set to "" to disable SkillToolset integration.
    skills_dir: str = "skills"

    # Comma-separated list of skill folder names to exclude from loading.
    # Example: EXCLUDE_SKILLS=cassandra-triage,cosmos-triage
    exclude_skills: str = ""

    # When true, MCP tools are registered globally so the agent can call any
    # MCP tool directly without loading a skill first.  Skills still work and
    # provide focused routing via adk_additional_tools guidance.
    # When false, MCP tools are ONLY available through skills (the SkillToolset
    # gates access via adk_additional_tools).  Use false when you want strict
    # skill-based routing and don't need direct MCP tool access.
    enable_mcps: bool = True

    # ── Agent behaviour ───────────────────────────────────────────────────────
    max_tool_rounds: int = 8
    llm_timeout_seconds: int = 60
    mcp_timeout_seconds: int = 30
    llm_history_turns: int = 0
    # Maximum characters kept per tool-result content block when the context window
    # is exceeded and _shrink_for_retry() truncates messages before retrying.
    # Lower = more aggressive truncation; higher = more context preserved per tool call.
    shrink_tool_result_max_chars: int = 1500
    # When true (and claude_is_primary_llm=true), marks the system prompt with
    # cache_control and sends the anthropic-beta prompt-caching header so Anthropic
    # caches the system prompt prefix across requests.  Default: false.
    llm_prompt_cache_enabled: bool = False
    # When true, uses the extended cache TTL (~1 hour) instead of the default
    # (~5 minutes).  Only effective when llm_prompt_cache_enabled=true.
    # false → anthropic-beta: prompt-caching-2024-07-31        (~5 min TTL)
    # true  → anthropic-beta: extended-cache-ttl-2025-04-11    (~1 hour TTL)
    llm_prompt_cache_extended: bool = False

    # ── Extended thinking (Claude reasoning) ─────────────────────────────────
    # When true (and claude_is_primary_llm=true), enables Claude's extended
    # thinking feature so the model exposes its chain-of-thought reasoning.
    # Thinking blocks are streamed to the UI as {"type":"thinking"} SSE events,
    # displayed in a collapsible reasoning panel while the request is processing.
    # Increases token usage by up to `llm_thinking_budget_tokens` per turn.
    llm_extended_thinking_enabled: bool = False
    # Maximum tokens allocated for Claude's internal reasoning per LLM call.
    # Higher = deeper reasoning but more latency and cost.
    # Anthropic minimum is 1024; recommended range: 4096–16384.
    llm_thinking_budget_tokens: int = 10000

    # ── Redis extras ──────────────────────────────────────────────────────────
    redis_ssl: bool = True
    redis_socket_timeout: int = 15           # seconds to wait for a Redis response
    redis_socket_connect_timeout: int = 10   # seconds to wait for initial connection
    redis_max_connections: int = 50          # per-pod connection pool limit
    redis_retry_attempts: int = 3            # max retry attempts on transient errors
    redis_retry_backoff_seconds: float = 0.5 # initial backoff (doubles each attempt)

    # ── PingFederate SSO (shared bearer token across all pods) ───────────────
    # Set SSO_USERNAME + SSO_PASSWORD to enable headless PingFed login.
    # The token is acquired once by whichever pod wins the distributed lock
    # and cached in Redis for all other pods to reuse.
    # UPN suffix (@homeoffice.wal-mart.com) is appended automatically if missing.
    sso_username: str = ""          # SSO_USERNAME env var
    sso_password: str = ""          # SSO_PASSWORD env var

    # Target service URL for SSO login (default: OpenObserve / intl.logs.prod.walmart.com).
    # Kept for backward-compatibility — superseded by PINGFED_URLS when set.
    pingfed_base_url: str = "https://intl.logs.prod.walmart.com"  # PINGFED_BASE_URL

    # Comma-separated list of OpenObserve cluster base URLs to pre-warm at startup.
    # When set, supersedes pingfed_base_url — every listed cluster gets its own
    # isolated Redis token key: agent:{auth:<host>}:token
    # Example: PINGFED_URLS=https://intl.logs.prod.walmart.com,https://gtp.logs.prod.walmart.com
    pingfed_urls: str = ""  # PINGFED_URLS

    @property
    def pingfed_url_list(self) -> list[str]:
        """Return the resolved list of O2 cluster URLs to warm up.

        Precedence:
          1. PINGFED_URLS (comma-separated) — supersedes PINGFED_BASE_URL
          2. PINGFED_BASE_URL               — single-URL fallback
        """
        if self.pingfed_urls.strip():
            return [u.strip() for u in self.pingfed_urls.split(",") if u.strip()]
        return [self.pingfed_base_url]

    # Hard Redis TTL — forces a full re-login when the key expires (seconds).
    # O2 web sessions expire in ~1 hour; keep at or below that to avoid serving
    # a token that is valid in Redis but already expired in OpenObserve.
    auth_token_ttl: int = 3300          # AUTH_TOKEN_TTL        (55 min)

    # Soft TTL — background refresh triggers here; pods keep serving the old token.
    auth_token_refresh_at: int = 2700   # AUTH_TOKEN_REFRESH_AT (45 min)

    # Lock TTL — auto-expires if the winning pod crashes mid-login (seconds).
    auth_lock_ttl: int = 60             # AUTH_LOCK_TTL

    # ── Environment / Group ──────────────────────────────────────────────────
    # Used to build the Redis key for MCP server discovery:
    #   super_agent:config:mcp_servers:<agent_env>:<agent_group>:config
    # e.g. super_agent:config:mcp_servers:stage:sre:config
    # Also drives dev-vs-prod branching (YAML file vs Redis).
    agent_env: str = "prod"
    agent_group: str = "sre"

    # ── Local dev overrides ───────────────────────────────────────────────────
    # Set AGENT_ENV=local in .env to skip Redis and load MCP servers from a local file.
    # Set MCP_SERVERS_FILE to the path of a YAML file listing server configs.
    # See mcp_servers.yml.example at the repo root for the expected format.
    mcp_servers_file: str = ""

    # ── A2A remote subagents ──────────────────────────────────────────────────
    # Local dev: point A2A_AGENTS_FILE at a YAML file (like mcp_servers_file).
    # Prod/stage: loaded from Redis key derived from agent_env + agent_group.
    # Missing or empty = no subagents registered (non-fatal, startup continues).
    # See a2a_agents.yml.example at the repo root for the expected format.
    a2a_agents_file: str = ""

    # ── Agent instruction (system prompt) source ──────────────────────────────
    # When true: load AGENT_INSTRUCTION.md content from Redis at startup.
    # When false (default): load from resources/AGENT_INSTRUCTION.md on disk.
    # Redis key used (when true):
    #   super_agent:config:agent_instruction:<agent_env>:<agent_group>:config
    agent_instruction_from_redis: bool = False

    model_config = SettingsConfigDict(extra="ignore")

    # ── Derived properties ────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def openai_url(self) -> str:
        """Construct the full Azure OpenAI chat-completions URL for Element Gateway.

        Combines the base URL, model deployment name, and API version into the
        single endpoint expected by the Azure OpenAI REST API.

        Returns:
            Fully-formed chat completions URL string.
        """
        return (
            f"{self.element_gateway_base_url}/deployments/{self.openai_model}"
            f"/chat/completions?api-version={self.element_gateway_api_version}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def openai_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Api-Key":    self.element_gateway_api_key,
            "api-key":      self.element_gateway_api_key,
        }

    @computed_field  # type: ignore[prop-decorator]
    @property
    def claude_headers(self) -> dict[str, str]:
        return {
            "Content-Type":      "application/json",
            "x-api-key":         self.claude_api_key,
            "anthropic-version": self.claude_anthropic_version,
        }

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_llm(self) -> str:
        """Return a human-readable label for the LLM provider currently in use.

        Returns:
            ``"claude"`` when ``claude_is_primary_llm`` is ``True``,
            ``"openai"`` otherwise.
        """
        return "claude" if self.claude_is_primary_llm else "openai"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mcp_config_key(self) -> str:
        """Build the Redis key for MCP server discovery.

        Format: ``super_agent:config:mcp_servers:<agent_env>:<agent_group>:config``
        e.g. ``super_agent:config:mcp_servers:stage:sre:config``
        """
        return f"super_agent:config:mcp_servers:{self.agent_env}:{self.agent_group}:config"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def a2a_agents_config_key(self) -> str:
        """Build the Redis key for A2A remote subagent discovery.

        Format: ``super_agent:config:a2a_agents:<agent_env>:<agent_group>:config``
        e.g. ``super_agent:config:a2a_agents:stage:sre:config``
        """
        return f"super_agent:config:a2a_agents:{self.agent_env}:{self.agent_group}:config"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def agent_instruction_config_key(self) -> str:
        """Build the Redis key for the agent system-prompt instruction.

        Format: ``super_agent:config:agent_instruction:<agent_env>:<agent_group>:config``
        e.g.    ``super_agent:config:agent_instruction:stage:sre:config``
        """
        return f"super_agent:config:agent_instruction:{self.agent_env}:{self.agent_group}:config"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_llm_endpoint(self) -> str:
        """Return the base URL of whichever LLM gateway is currently active.

        Useful for logging and the ``/health`` response so operators can
        confirm which gateway the agent is hitting at runtime.

        Returns:
            Claude gateway URL or the constructed OpenAI URL, depending on
            ``claude_is_primary_llm``.
        """
        return self.claude_gateway_url if self.claude_is_primary_llm else self.openai_url


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
