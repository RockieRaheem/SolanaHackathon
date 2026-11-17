from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HarambeeOne API"
    app_environment: Literal["development", "test", "staging", "production"] = Field(
        default="development", alias="NODE_ENV"
    )
    database_url: str
    migration_database_url: str
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    database_pool_recycle_seconds: int = Field(default=900, ge=60, le=3600)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=120_000)
    database_lock_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    database_idle_transaction_timeout_ms: int = Field(
        default=30_000, ge=1_000, le=300_000
    )
    database_ssl_mode: Literal["require", "verify-ca", "verify-full"] = "require"
    database_ssl_root_cert: Path | None = None
    supabase_url: AnyHttpUrl
    supabase_publishable_key: str = Field(alias="NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemma_model: str = Field(default="gemma-4-26b-a4b-it", alias="GEMMA_MODEL")
    solana_rpc_url: AnyHttpUrl = Field(
        default="https://api.devnet.solana.com", alias="SOLANA_RPC_URL"
    )
    solana_cluster: Literal["devnet"] = Field(default="devnet", alias="SOLANA_CLUSTER")
    solana_ugx_per_sol: Decimal = Field(
        default=Decimal("750000"), gt=0, alias="SOLANA_DEMO_UGX_PER_SOL"
    )
    solana_intent_ttl_minutes: int = Field(
        default=30, ge=5, le=120, alias="SOLANA_INTENT_TTL_MINUTES"
    )

    @model_validator(mode="after")
    def validate_database_transport(self) -> "Settings":
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg driver")
        if not self.migration_database_url.startswith("postgresql+psycopg://"):
            raise ValueError("MIGRATION_DATABASE_URL must use the postgresql+psycopg driver")

        if self.app_environment == "production":
            if self.database_ssl_mode != "verify-full":
                raise ValueError(
                    "Production requires DATABASE_SSL_MODE=verify-full"
                )
            if self.database_ssl_root_cert is None:
                raise ValueError(
                    "Production requires DATABASE_SSL_ROOT_CERT"
                )
            certificate = self.database_ssl_root_cert.expanduser()
            if not certificate.is_file():
                raise ValueError("DATABASE_SSL_ROOT_CERT must reference a readable file")
            self.database_ssl_root_cert = certificate.resolve()

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
