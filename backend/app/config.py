from functools import lru_cache
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


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
    openai_base_url: str = "https://api.openai.com/v1"
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
    auth_disabled: bool = Field(
        default=False, description="Only enable for isolated development tests"
    )
    development_tenant_id: str = "00000000-0000-4000-8000-000000000001"
    default_tenant_name: str = "سازمان"
    max_audio_bytes: int = 500 * 1024 * 1024
    api_rate_limit_per_minute: int = 120
    secret_encryption_key: str = ""

    # Issabel/Asterisk recording import. ``local`` also covers mounted SMB/NFS
    # shares; credentials belong to the operating-system mount, not this app.
    issabel_import_mode: str = "disabled"
    issabel_recordings_path: str = "/recordings"
    issabel_sftp_host: str = ""
    issabel_sftp_port: int = 22
    issabel_sftp_username: str = ""
    issabel_sftp_password: str = ""
    issabel_sftp_password_file: str = ""
    issabel_sftp_private_key: str = ""
    issabel_sftp_known_hosts: str = "/run/secrets/issabel_known_hosts"
    issabel_sftp_allow_insecure_host_key: bool = False
    issabel_sftp_remote_path: str = "/var/spool/asterisk/monitor"
    issabel_sftp_staging_path: str = "/tmp/mokalemeban-sftp"
    issabel_sftp_max_files_per_scan: int = Field(default=5000, ge=1, le=100_000)
    issabel_sftp_max_depth: int = Field(default=8, ge=1, le=32)
    issabel_poll_interval: int = 30
    issabel_file_stability_seconds: int = 15
    issabel_allowed_extensions: str = ".wav,.mp3,.gsm"
    issabel_quarantine_path: str = "/recordings/quarantine"
    issabel_filename_pattern: str = ""
    issabel_default_tenant_id: str | None = None
    issabel_temporary_extensions: str = ".tmp,.part,.partial,.download"
    issabel_cdr_database_url: str = ""
    issabel_cdr_host: str = ""
    issabel_cdr_port: int = Field(default=3306, ge=1, le=65535)
    issabel_cdr_username: str = ""
    issabel_cdr_password: str = ""
    issabel_cdr_password_file: str = ""
    issabel_cdr_database: str = "asteriskcdrdb"
    issabel_cdr_table: str = "cdr"
    issabel_cdr_recording_column: str = "recordingfile"
    issabel_cdr_match_window_seconds: int = Field(default=180, ge=30, le=3600)

    @field_validator("issabel_cdr_table", "issabel_cdr_recording_column")
    @classmethod
    def validate_cdr_table(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.replace("_", "").isalnum():
            raise ValueError("ISSABEL_CDR_TABLE must be a simple SQL identifier")
        return normalized

    @staticmethod
    def _secret(value: str, file_path: str) -> str:
        if file_path:
            return Path(file_path).read_text(encoding="utf-8").strip()
        return value

    @property
    def resolved_issabel_sftp_password(self) -> str:
        return self._secret(self.issabel_sftp_password, self.issabel_sftp_password_file)

    @property
    def resolved_issabel_cdr_database_url(self) -> str | URL | None:
        if self.issabel_cdr_database_url:
            return self.issabel_cdr_database_url
        if not self.issabel_cdr_host:
            return None
        return URL.create(
            "mysql+asyncmy",
            username=self.issabel_cdr_username or None,
            password=self._secret(self.issabel_cdr_password, self.issabel_cdr_password_file)
            or None,
            host=self.issabel_cdr_host,
            port=self.issabel_cdr_port,
            database=self.issabel_cdr_database,
        )

    audio_min_duration_seconds: float = 1.0
    audio_target_sample_rate: int = 16000
    audio_ffmpeg_path: str = "ffmpeg"
    audio_ffprobe_path: str = "ffprobe"
    processing_max_retries: int = 5
    processing_retry_schedule_seconds: str = "30,120,600,1800,7200"
    processing_stage_timeout_seconds: int = Field(default=1800, ge=30, le=21_600)
    watcher_stale_after_seconds: int = 120
    worker_stale_after_seconds: int = 300
    cors_origins: str = "http://localhost:3000"
    pdf_font_path: str = ""
    log_level: str = "INFO"

    @field_validator("issabel_import_mode")
    @classmethod
    def validate_import_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"disabled", "local", "shared_folder", "sftp"}:
            raise ValueError("ISSABEL_IMPORT_MODE must be disabled, local, shared_folder or sftp")
        return value

    @property
    def issabel_extensions(self) -> frozenset[str]:
        return frozenset(
            item if item.startswith(".") else f".{item}"
            for item in (
                part.strip().lower() for part in self.issabel_allowed_extensions.split(",")
            )
            if item
        )

    @property
    def retry_schedule(self) -> tuple[int, ...]:
        values = tuple(
            int(item.strip())
            for item in self.processing_retry_schedule_seconds.split(",")
            if item.strip()
        )
        if not values or any(item <= 0 for item in values):
            raise ValueError("PROCESSING_RETRY_SCHEDULE_SECONDS must contain positive integers")
        return values

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @model_validator(mode="after")
    def reject_insecure_production_configuration(self):
        if self.issabel_import_mode != "disabled":
            if not self.issabel_default_tenant_id:
                raise ValueError(
                    "ISSABEL_DEFAULT_TENANT_ID is required when Issabel import is enabled"
                )
            try:
                UUID(self.issabel_default_tenant_id)
            except ValueError as exc:
                raise ValueError("ISSABEL_DEFAULT_TENANT_ID must be a valid UUID") from exc
        if self.issabel_import_mode == "sftp":
            if not self.issabel_sftp_host or not self.issabel_sftp_username:
                raise ValueError(
                    "ISSABEL_SFTP_HOST and ISSABEL_SFTP_USERNAME are required in sftp mode"
                )
            if not self.issabel_sftp_known_hosts and not self.issabel_sftp_allow_insecure_host_key:
                raise ValueError(
                    "ISSABEL_SFTP_KNOWN_HOSTS is required unless insecure host-key checking "
                    "is explicitly enabled"
                )
        if self.environment.casefold() != "production":
            return self
        errors: list[str] = []
        if self.auth_disabled:
            errors.append("AUTH_DISABLED must be false")
        if self.issabel_sftp_allow_insecure_host_key:
            errors.append("ISSABEL_SFTP_ALLOW_INSECURE_HOST_KEY must be false")
        secrets = {
            "S3_SECRET_KEY": self.s3_secret_key,
            "KEYCLOAK_ADMIN_PASSWORD": self.keycloak_admin_password,
            "SECRET_ENCRYPTION_KEY": self.secret_encryption_key,
        }
        for name, value in secrets.items():
            normalized = value.strip().casefold()
            if not normalized or normalized in {"change-me", "change-me-now", "password", "secret"}:
                errors.append(f"{name} must be supplied from a secret store")
        if self.secret_encryption_key:
            try:
                Fernet(self.secret_encryption_key.encode())
            except (TypeError, ValueError):
                errors.append("SECRET_ENCRYPTION_KEY must be a valid Fernet key")
        if (
            "mokalemeban:mokalemeban@" in self.database_url
            or "change-me" in self.database_url.casefold()
        ):
            errors.append("DATABASE_URL contains development credentials")
        if errors:
            raise ValueError("insecure production configuration: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
