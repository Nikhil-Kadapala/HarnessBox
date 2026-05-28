"""Cloud API configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_jwt_secret: str

    stripe_secret_key: str
    stripe_webhook_secret: str = ""

    harnessbox_storage: str = "sqlite"
    harnessbox_db_path: str = "harnessbox_cloud.db"

    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
