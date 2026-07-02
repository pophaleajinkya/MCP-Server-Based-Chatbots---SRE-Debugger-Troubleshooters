import glob, logging, os
from pathlib import Path
from typing import ClassVar
from dotenv import load_dotenv
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
import logging

logger = logging.getLogger(__name__)
# Get the project root directory
project_root = os.path.dirname(os.path.abspath(__file__))


logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Project root directory: {project_root}")
logger.info(f"Found .env files in current dir: {glob.glob('.env*')}")
logger.info(f"Found .env files in project root: {glob.glob(os.path.join(project_root, '.env*'))}")

# Load all .env* files from current dir, project root, and /secrets
all_env_files = list(set(
    glob.glob(".env*") +
    glob.glob(os.path.join(project_root, ".env*")) +
    glob.glob(os.path.join(os.environ.get("ROOT", ""), ".env*")) +
    glob.glob("/secrets/.env*")
))
env_files = sorted([f for f in all_env_files if f != ".env.test"])

for env_file in env_files:
    path = Path(env_file)
    if path.is_file():
        try:
            load_dotenv(dotenv_path=path, override=True)
        except Exception as e:
            logger.exception(e)
        logger.info(f"[config] Loaded: {env_file}")


class Settings(BaseSettings):
    AZURE_OPENAI_ENDPOINT: str = Field(..., alias="AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_MODEL: str = Field("gpt-4.1", alias="AZURE_OPENAI_MODEL")
    AZURE_EMBEDDING_MODEL: str = Field("text-embedding-ada-002", alias="AZURE_EMBEDDING_MODEL")
    AZURE_OPENAI_API_KEY: str = Field(..., alias="AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_API_VERSION: str = Field("2024-10-21", alias="AZURE_OPENAI_API_VERSION")

    REDIS_HOST: str = Field(..., alias="REDIS_HOST")
    REDIS_PORT: str = Field(..., alias="REDIS_PORT")
    REDIS_PASSWORD: str = Field(..., alias="REDIS_PASSWORD")
    REDIS_URL: str | None = Field(None, alias="REDIS_URL")
    REDIS_USERNAME: str | None = Field(None, alias="REDIS_USERNAME")

    SRE_OPS_URL: str = Field(..., alias="SRE_OPS_URL")
    TOPOLOGY_API_URL: str = Field(..., alias="TOPOLOGY_API_URL")
    TOPOLOGY_WM_CONSUMER_ID: str = Field(..., alias="TOPOLOGY_WM_CONSUMER_ID")
    TOPOLOGY_WM_SVC_NAME: str = Field(..., alias="TOPOLOGY_WM_SVC_NAME")
    TOPOLOGY_WM_SVC_ENV: str = Field(..., alias="TOPOLOGY_WM_SVC_ENV")

    # API Endpoint Paths
    SRE_OPS_DOWNSTREAM_PATH: str = Field("/dependencies/downstream", alias="SRE_OPS_DOWNSTREAM_PATH")
    SRE_OPS_UPSTREAM_PATH: str = Field("/dependencies/upstream", alias="SRE_OPS_UPSTREAM_PATH")
    DX_CONSOLE_APPS_PATH: str = Field("/proxy/wcnp-apps/apps", alias="DX_CONSOLE_APPS_PATH")

    # Conversation and DX Console URLs
    CONVERSATION_API_URL: str = Field(..., alias="CONVERSATION_API_URL")
    DX_CONSOLE_URL: str = Field(..., alias="DX_CONSOLE_URL")


    # AZURE_APP_TENANT_ID: str = Field(..., alias="AZURE_APP_TENANT_ID")
    # AZURE_APP_CLIENT_ID: str = Field(..., alias="AZURE_APP_CLIENT_ID")
    # AZURE_APP_CLIENT_SECRET: str = Field(..., alias="AZURE_APP_CLIENT_SECRET")


    # MILVUS_USER: str = Field(..., alias="MILVUS_USER")
    # MILVUS_PASSWORD: str = Field(..., alias="MILVUS_PASSWORD")
    # MILVUS_HOST: str = Field(..., alias="MILVUS_HOST")
    # MILVUS_PORT: str = Field(..., alias="MILVUS_PORT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
        "extra": "ignore"
    }

@lru_cache()
def get_settings() -> Settings:
    return Settings()

