from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="RelayFlow", description="Service display name.")
    debug: bool = Field(default=False, description="Enable SQL echo and debug logging.")

    database_url: str = Field(
        ...,
        description="PostgreSQL DSN. asyncpg form: postgresql+asyncpg://user:pass@host:5432/dbname",
    )
    redis_url: str = Field(
        ...,
        description="Redis 7 connection string, e.g. redis://localhost:6379/0",
    )
    secret_key: SecretStr = Field(
        ...,
        description="Application signing / encryption secret.",
    )

    celery_broker_url: str | None = Field(
        default=None,
        description="Celery broker URL. Defaults to redis_url when omitted.",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="Celery result backend URL. Defaults to redis_url when omitted.",
    )

    @field_validator("database_url")
    @classmethod
    def ensure_asyncpg_dsn(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("postgresql+asyncpg://"):
            return normalized
        if normalized.startswith("postgresql://"):
            return normalized.replace("postgresql://", "postgresql+asyncpg://", 1)
        if normalized.startswith("postgres://"):
            return normalized.replace("postgres://", "postgresql+asyncpg://", 1)
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL DSN "
            "(postgresql+asyncpg://, postgresql://, or postgres://)."
        )

    @field_validator("redis_url")
    @classmethod
    def ensure_redis_dsn(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith(("redis://", "rediss://", "unix://")):
            return normalized
        raise ValueError("REDIS_URL must start with redis://, rediss://, or unix://.")

    @model_validator(mode="after")
    def fill_celery_connection_strings(self) -> "Settings":
        if self.celery_broker_url is None:
            self.celery_broker_url = self.redis_url
        if self.celery_result_backend is None:
            self.celery_result_backend = self.redis_url
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
