from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://mokalemeban:mokalemeban@postgres:5432/mokalemeban"
    redis_url: str = "redis://redis:6379/0"
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "mokalemeban"
    s3_secret_key: str = "change-me"
    s3_bucket: str = "sales-calls"
    s3_region: str = "us-east-1"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.avalai.ir/v1"
    transcription_model: str = "gpt-4o-transcribe-diarize"
    analysis_model: str = "gpt-4o"
    analysis_prompt_version: str = "sales-v1"

    oidc_issuer: str = "http://keycloak:8080/realms/mokalemeban"
    oidc_jwks_url: str | None = None
    oidc_audience: str = "mokalemeban-api"
    keycloak_admin_url: str = "http://keycloak:8080"
    keycloak_realm: str = "mokalemeban"
    keycloak_admin_user: str = "admin"
    keycloak_admin_password: str = "change-me-now"
    auth_disabled: bool = Field(default=False, description="Only enable for isolated development tests")
    development_tenant_id: str = "00000000-0000-4000-8000-000000000001"
    max_audio_bytes: int = 500 * 1024 * 1024
    api_rate_limit_per_minute: int = 120
    secret_encryption_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
