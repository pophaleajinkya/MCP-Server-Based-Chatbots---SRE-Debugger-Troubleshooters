"""Configuration for {{cookiecutter.project_name}}."""

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
    server_host: str = "0.0.0.0"
    server_port: int = {{cookiecutter.server_port}}

    # ── TODO: Add your domain-specific settings ───────────────────────────────
    # prometheus_url: str = "http://prometheus.internal:9090"
    # db_host: str = "localhost"
    # api_key: str = ""

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
