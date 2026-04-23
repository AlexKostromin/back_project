from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LexInsight Backend"
    app_version: str = "0.1.0"
    app_debug: bool = False

    # Dev-only defaults so smoke tests that don't touch the DB can still
    # instantiate Settings without a populated .env. Real credentials come
    # from .env / compose env and override these at runtime.
    postgres_user: str = "lexinsight"
    postgres_password: str = "change-me"
    postgres_db: str = "lexinsight"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    es_url: str = "http://localhost:9200"
    es_request_timeout_s: int = 10
    es_court_decisions_index: str = "court_decisions"

    scraper_user_agent: str = "LexInsight-Bot/1.0 (+https://lexinsight.ru/bot; bot@lexinsight.ru)"
    scraper_connect_timeout: float = 5.0
    scraper_read_timeout: float = 30.0

    @field_validator("scraper_user_agent")
    @classmethod
    def _no_crlf(cls, v: str) -> str:
        if "\r" in v or "\n" in v:
            raise ValueError("scraper_user_agent must not contain CR or LF")
        return v

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
