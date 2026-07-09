from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Altur Backend"
    app_env: str = "local"
    debug: bool = False
    database_url: str | None = None
    call_storage_bucket: str = "call-audio"
    local_storage_root: str = ".data/storage"
    max_call_upload_bytes: int = 524_288_000
    elevenlabs_api_key: str | None = None
    elevenlabs_stt_model_id: str = "scribe_v1"
    openai_api_key: str | None = None
    openai_analysis_model: str = "gpt-4.1-mini"
    analysis_prompt_version: str = "altur-analysis-v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
