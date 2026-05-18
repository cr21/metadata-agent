import json
import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    google_application_credentials: str = ""
    bq_metadata_project: str = ""
    bq_metadata_dataset: str = "metadata_store"
    log_level: str = "INFO"
    log_format: str = "text"  # "text" or "json"
    demo_fixture_repo: str = "https://github.com/cr21/agentic-test-data"
    demo_fixture_branch: str = "main"

    # LLM concurrency
    llm_concurrency: int = 4
    llm_timeout_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    if settings.log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.basicConfig(level=level, handlers=[handler])
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        )
