"""Application settings, read from environment variables prefixed KHATAIQ_ (or a .env file)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KHATAIQ_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://khataiq:khataiq@localhost:5432/khataiq"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "khataiq"
    s3_secret_key: SecretStr = SecretStr("khataiq-dev-secret")
    s3_bucket: str = "statements"


@lru_cache
def get_settings() -> Settings:
    return Settings()
