"""
Configuration for the Valid8 MCP Server.

Loads from environment variables (highest priority) and .env file.

Environment Variables:
    VALID8_BASE_URL         Valid8 base URL (default: https://intl-valid8-qa.walmart.com)
    VALID8_API_KEY          API key for X-API-Key header (required)
    VALID8_TIMEOUT          HTTP timeout in seconds (default: 60)
    VALID8_VERIFY_SSL       TLS verification for Valid8 (default: true).
                            Accepts:
                              - "true" / "false" / "1" / "0" — toggle verification
                              - a path to a PEM CA bundle → httpx verifies against it.
                                Prod/Stage: /secrets/walmart-ca.pem (injected by
                                Akeyless, see kitt.yml).
                                Local dev: ./certs/walmart-ca.pem (git-ignored).
    VALID8_LOG_LEVEL        Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)

Authentication:
    Valid8 uses X-API-Key and X-Tenant headers for authentication.
    X-API-Key is configured via VALID8_API_KEY env var.
    X-Tenant is determined per-request based on the market (ca / mx).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local dev: .env — KITT/Akeyless: mounted at /secrets/.env.valid8_mcp (see kitt.yml)
load_dotenv()
load_dotenv(Path("/secrets/.env.valid8_mcp"))


def _parse_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    return bool(v)


_BOOL_TOKENS = {"true", "false", "1", "0", "yes", "no", ""}


def _parse_verify_ssl(v: object) -> bool | str:
    """Return a bool for toggles; return a str path when v points to a PEM bundle.

    httpx's ``verify`` parameter natively accepts both ``bool`` and ``str``
    (treated as a CA bundle path), so we forward whichever the caller gave us.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in _BOOL_TOKENS:
            return _parse_bool(s)
        if Path(s).is_file():
            return s
        return _parse_bool(s)
    return bool(v)


class Settings(BaseSettings):
    """Valid8 MCP Server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Valid8 connection ─────────────────────────────────────────────
    valid8_base_url: str = Field(
        default="https://intl-valid8-qa.walmart.com",
        alias="VALID8_BASE_URL",
        description="Valid8 base URL.",
    )
    valid8_api_key: str = Field(
        default="",
        alias="VALID8_API_KEY",
        description="API key sent as X-API-Key header.",
    )
    valid8_timeout: float = Field(
        default=60.0,
        alias="VALID8_TIMEOUT",
        description="HTTP timeout in seconds for Valid8 API calls.",
    )
    valid8_verify_ssl: bool | str = Field(
        default=True,
        alias="VALID8_VERIFY_SSL",
        description=(
            "TLS verification for Valid8. True/False to toggle, or a path "
            "to a PEM CA bundle (e.g. /secrets/cert.pem)."
        ),
    )

    # ── Server ────────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        alias="VALID8_LOG_LEVEL",
        description="Logging level.",
    )

    @field_validator("valid8_verify_ssl", mode="before")
    @classmethod
    def parse_verify_ssl(cls, v: object) -> bool | str:
        return _parse_verify_ssl(v)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
