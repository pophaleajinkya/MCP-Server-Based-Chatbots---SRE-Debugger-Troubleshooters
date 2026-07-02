"""Centralised application configuration for {{cookiecutter.project_name}}."""

import glob
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_all_env_files = glob.glob(".env*") + glob.glob("/secrets/.env*")
if Path(os.getcwd()).name == "src":
    _all_env_files += glob.glob("../.env*")
_EXCLUDED = {".env.test", ".env.example"}
_env_files = sorted(
    [f for f in _all_env_files if Path(f).name not in _EXCLUDED],
    key=lambda f: (Path(f).name != ".env", Path(f).name),
)
for _env_file in _env_files:
    _path = Path(_env_file)
    if _path.is_file():
        load_dotenv(dotenv_path=_path, override=True)


class Settings(BaseSettings):
    # ── Server ────────────────────────────────────────────────────────────────
    agent_host: str = "0.0.0.0"
    agent_port: int = {{cookiecutter.agent_port}}
    agent_env: str = "local"

    # ── LLM — Claude via Walmart Stage Gateway ────────────────────────────────
    claude_gateway_url: str = ""
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    claude_anthropic_version: str = "vertex-2023-10-16"
    claude_is_primary_llm: bool = True

    # ── Redis session storage ─────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_username: str = "default"
    redis_ssl: bool = False
    redis_session_ttl_seconds: int = 604800  # 7 days

    # ── Agent behaviour ───────────────────────────────────────────────────────
    max_tool_rounds: int = 8
    llm_timeout_seconds: int = 60

    # ── MCP (optional) ────────────────────────────────────────────────────────
    mcp_servers_file: str = ""

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
