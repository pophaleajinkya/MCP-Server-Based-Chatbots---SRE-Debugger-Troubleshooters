"""
Configuration for the Signal MCP Server.

Loads from environment variables (highest priority) and .env file.

Environment Variables:
    SIGNAL_BASE_URL         Signal API base URL (default: https://signal-api.walmart.com)
    SIGNAL_TIMEOUT          HTTP timeout in seconds (default: 60)
    SIGNAL_VERIFY_SSL       Verify TLS certificates (default: true)
    SIGNAL_LOG_LEVEL        Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)

Authentication:
    Signal API uses accept: application/json header.
    No API key or token is required for the current endpoints.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()
load_dotenv(Path("/secrets/.env.signal_mcp"))


def _parse_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    return bool(v)


class Settings(BaseSettings):
    """Signal MCP Server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    signal_base_url: str = Field(
        default="https://signal-api.walmart.com",
        alias="SIGNAL_BASE_URL",
        description="Signal API base URL.",
    )
    signal_timeout: float = Field(
        default=60.0,
        alias="SIGNAL_TIMEOUT",
        description="HTTP timeout in seconds for Signal API calls.",
    )
    signal_verify_ssl: bool = Field(
        default=True,
        alias="SIGNAL_VERIFY_SSL",
        description="Verify TLS certificates to Signal API.",
    )

    log_level: str = Field(
        default="INFO",
        alias="SIGNAL_LOG_LEVEL",
        description="Logging level.",
    )

    @field_validator("signal_verify_ssl", mode="before")
    @classmethod
    def parse_verify_ssl(cls, v: object) -> bool:
        return _parse_bool(v)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
