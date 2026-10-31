"""Typed settings, one class per service.

Env-var prefixes keep the two services from ever reading each other's secrets:
- api:         API_*
- processing:  PROC_*
- shared:      DATABASE_URL, REDIS_URL, TIGRIS_*
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
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
    max_upload_mb: int = 200


class ProcessingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROC_", env_file=".env", extra="ignore")

    # Accept both the PROC_-prefixed name and the bare names used in .env
    openparser_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PROC_OPENPARSER_API_KEY", "OPENPARSER_API_KEY"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PROC_LLM_API_KEY", "LLM_API_KEY"),
    )
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_model: str = "openai/gpt-oss-20b"


class EmbeddingSettings(BaseSettings):
    """Embedding provider (OpenAI-compatible; NVIDIA NIM by default).

    Embeds under its own ``EMBED_*`` namespace but falls back to the LLM key and
    base URL, so the single NVIDIA key in the stack powers chat and embeddings.
    Both services read this: the worker embeds passages, the API embeds queries.
    """

    model_config = SettingsConfigDict(env_prefix="EMBED_", env_file=".env", extra="ignore")

    model: str = "nvidia/nemotron-3.5-embed-1b"
    # The model is natively 2048-wide; truncating to 1536 keeps the existing
    # text_chunks.embedding column and its HNSW index. Measured on a probe set:
    # 1536 and 2048 rank identically (top score 0.4629 vs 0.4624).
    dimensions: int = 1536
    batch_size: int = 32
    api_key: str = Field(
        default="",
        validation_alias=AliasChoices("EMBED_API_KEY", "PROC_LLM_API_KEY", "LLM_API_KEY"),
    )
    base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        validation_alias=AliasChoices("EMBED_BASE_URL", "PROC_LLM_BASE_URL", "LLM_BASE_URL"),
    )


@lru_cache
def get_shared_settings() -> SharedSettings:
    return SharedSettings()


@lru_cache
def get_embedding_settings() -> EmbeddingSettings:
    return EmbeddingSettings()


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()


@lru_cache
def get_processing_settings() -> ProcessingSettings:
    return ProcessingSettings()
