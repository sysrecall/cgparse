"""Typed settings, one class per service.

Env-var prefixes keep the two services from ever reading each other's secrets:
- api:         API_*
- processing:  PROC_*
- shared:      DATABASE_URL, REDIS_URL, TIGRIS_*
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class SharedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str

    # Tigris object storage via boto3's native AWS_* env-var support:
    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_ENDPOINT_URL_S3 / AWS_REGION
    # are read by botocore automatically — only the bucket name is ours to name.
    tigris_bucket: str


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", env_file=".env", extra="ignore")

    jwt_secret: str = "change-me"
    jwt_expires_minutes: int = 60
    cors_origins: str = "http://localhost:3000"


class ProcessingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROC_", env_file=".env", extra="ignore")

    openparser_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"


@lru_cache
def get_shared_settings() -> SharedSettings:
    return SharedSettings()


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()


@lru_cache
def get_processing_settings() -> ProcessingSettings:
    return ProcessingSettings()
