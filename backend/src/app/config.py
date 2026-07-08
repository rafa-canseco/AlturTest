from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Altur Backend"
    app_env: str = "local"
    debug: bool = False
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "call-audio"
    max_call_upload_bytes: int = 524_288_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
