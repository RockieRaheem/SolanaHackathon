from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HarambeeOne API"
    app_environment: str = Field(default="development", alias="NODE_ENV")
    database_url: str
    migration_database_url: str
    supabase_url: AnyHttpUrl
    supabase_publishable_key: str = Field(alias="NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemma_model: str = Field(default="gemma-4-26b-a4b-it", alias="GEMMA_MODEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
