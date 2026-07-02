"""
Configuration for the OpenObserve MCP Server.

Loads from environment variables (highest priority) and .env file.
Sensitive credentials (auth tokens) are never hardcoded.

Environment Variables:
    O2_ENDPOINT        OpenObserve API base URL (e.g. https://intl.logs.prod.walmart.com/api)
    O2_AUTH_TOKEN      Base64-encoded "user:password" for Basic auth
    O2_ORG_ID          Organization ID (default: "default")
    O2_TIMEOUT         HTTP timeout in seconds (default: 60)
    O2_SSL_VERIFY      Verify TLS certificates (default: false for internal clusters)
    O2_MAX_LIMIT       Max rows per query result (default: 10000)
    O2_DEFAULT_LIMIT   Default rows per query result (default: 1000)
    O2_DEFAULT_TIME_RANGE  Default time range for queries (default: "1h")
    O2_LOG_LEVEL       Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
    O2_MAX_RETRIES     Max SQL retry attempts in the super-agent loop (default: 5)

Auth:
    On 4XX responses the tool returns {"success": false, "auth_expired": true, ...}
    so the orchestrating agent can call pingfed_playwright_token (super-agent ADK
    tool) for a fresh token and retry the tool call.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="O2_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ── OpenObserve connection ────────────────────────────────────────
    endpoint: str = Field(
        default="",
        description="OpenObserve API base URL, e.g. https://intl.logs.prod.walmart.com/api",
    )
    auth_token: str = Field(
        default="",
        description="Base64-encoded 'user:password' for Basic auth",
    )
    org_id: str = Field(default="default", description="Organization ID")
    timeout: float = Field(default=60.0, description="HTTP timeout in seconds")
    ssl_verify: bool = Field(default=False, description="Verify TLS certificates")

    # ── Query defaults ────────────────────────────────────────────────
    max_limit: int = Field(default=10_000, description="Max rows per query")
    default_limit: int = Field(default=1_000, description="Default rows per query")
    default_time_range: str = Field(default="1h", description="Default query time range")

    # ── Schema pruning ────────────────────────────────────────────────
    schema_field_threshold: int = Field(
        default=30,
        description="Field count above which schema pruning is applied",
    )

    # ── Feature flags ─────────────────────────────────────────────────
    enable_sql_validation: bool = Field(
        default=True, description="Enable live SQL validation against O2 cluster"
    )
    enable_vrl_validation: bool = Field(
        default=True, description="Enable live VRL validation against O2 cluster"
    )
    enable_sql_ast: bool = Field(
        default=True, description="Use sqlglot AST for SQL policy checks"
    )

    # ── Retry loop ───────────────────────────────────────────────────
    max_retries: int = Field(
        default=5,
        description=(
            "Max SQL retry attempts for the super-agent self-correction loop. "
            "Set via O2_MAX_RETRIES env var. Range: 1–10."
        ),
    )

    @field_validator("max_retries", mode="before")
    @classmethod
    def _clamp_max_retries(cls, v: int) -> int:
        """Clamp max_retries to [1, 10] to prevent retry storms or no-retry config."""
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 5  # default on unparseable value
        if v < 1:
            return 1
        if v > 10:
            return 10
        return v

    # ── Server ────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="Logging level")

    # ── Computed ──────────────────────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def auth_header(self) -> str:
        """Return the Authorization header value."""
        if not self.auth_token:
            return ""
        return f"Basic {self.auth_token}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_url(self) -> str:
        """Normalized base URL (trailing slash stripped)."""
        return self.endpoint.rstrip("/") if self.endpoint else ""

    def is_configured(self) -> bool:
        """Return True if endpoint and auth token are both set."""
        return bool(self.endpoint and self.auth_token)

    def get_auth_headers(self) -> dict[str, str]:
        """Return HTTP headers for O2 API requests."""
        return {
            "Authorization": self.auth_header,
            "Content-Type": "application/json",
        }

    def encode_basic_auth(self, username: str, password: str) -> str:
        """Helper: base64-encode user:password for auth_token."""
        raw = f"{username}:{password}"
        return base64.b64encode(raw.encode()).decode()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
