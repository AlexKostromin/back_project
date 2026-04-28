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

    kad_session_ttl_seconds: int = 23 * 3600
    kad_session_headless: bool = True

    # GigaChat (Сбер). Свободный тариф GIGACHAT_API_PERS — лимит токенов в
    # месяц, модель ``GigaChat`` (Lite, ~8K контекст). Auth — OAuth2 client
    # credentials по адресу ngw.devices.sberbank.ru, чат — через
    # gigachat.devices.sberbank.ru. TLS требует Russian Trusted Root CA;
    # путь до bundle хранится тут, чтобы httpx-клиент мог его подсунуть
    # как ``verify=...``.
    gigachat_client_id: str = ""
    gigachat_client_secret: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_ca_bundle_path: str = "app/llm/certs/russian_trusted_root_ca.pem"
    gigachat_request_timeout_s: float = 30.0
    # Жёсткий cap на длину текста, отдаваемого в LLM (символы), чтобы не
    # упереться в context window модели Lite. ~24K символов ≈ ~8K токенов
    # для русского, плюс место под промпт и ответ.
    gigachat_max_input_chars: int = 24000

    # Rate-limit на LLM-эндпоинты (per IP, per minute). На demo-тарифе
    # GIGACHAT_API_PERS месячный лимит токенов конечен — открытый
    # анонимный эндпоинт без лимита одна curl-петля сжигает за минуты.
    # 10/min достаточно для живой демонстрации (демонстратор в худшем
    # случае жмёт «обновить» 3-4 раза подряд) и плотно блокирует
    # ботов-сканеров. Меняется без ребилда через .env.
    llm_rate_limit_per_minute: int = 10

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
