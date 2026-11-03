"""Application settings, read from environment variables prefixed KHATAIQ_ (or a .env file)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KHATAIQ_", env_file=".env", extra="ignore")

    environment: str = "dev"  # dev | test | prod

    # The app connects as khataiq_app, which is subject to row-level security.
    database_url: str = "postgresql+psycopg://khataiq_app:khataiq_app@localhost:5432/khataiq"
    # Migrations run as the owner role, which creates tables and the app role.
    migration_database_url: str = "postgresql+psycopg://khataiq:khataiq@localhost:5432/khataiq"
    # If set, `alembic upgrade` (re)sets khataiq_app's password to this value.
    app_db_password: SecretStr | None = None

    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "s3"  # s3 | local (a directory; handy for tests and offline dev)
    local_storage_dir: str = ".data/objects"
    s3_endpoint: str | None = "http://localhost:9000"  # None/empty = real AWS S3
    s3_access_key: str = "khataiq"
    s3_secret_key: SecretStr = SecretStr("khataiq-dev-secret")
    s3_bucket: str = "statements"
    s3_region: str = "us-east-1"
    s3_create_bucket: bool = True  # dev convenience; production buckets are provisioned

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_days: int = 7
    cookie_secure: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]

    rate_limit_general_per_minute: int = 60
    rate_limit_uploads_per_minute: int = 10
    rate_limit_copilot_per_hour: int = 20

    max_upload_bytes: int = 10 * 1024 * 1024

    label_model_dir: str | None = None  # default: models/label/v1 in the repository

    llm_model: str = "claude-sonnet-5-5"
    llm_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _no_dev_secrets_in_prod(self) -> Settings:
        if self.environment == "prod" and self.jwt_secret.get_secret_value() == DEV_JWT_SECRET:
            raise ValueError("KHATAIQ_JWT_SECRET must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
