from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    secret_key: str
    encryption_key: str

    platform_database_url: str = "sqlite:///./data/platform.db"
    tenant_db_mode: Literal["sqlite", "postgres"] = "sqlite"
    tenant_sqlite_dir: str = "./data/tenants"
    postgres_admin_url: str = ""
    tenant_db_host: str = "db"
    tenant_db_port: int = 5432

    access_token_minutes: int = 30
    refresh_token_days: int = 7
    cors_origins: str = "http://localhost:5173"
    app_base_url: str = "http://localhost:5173"  # origin used in e-mailed links
    password_reset_minutes: int = 60
    email_verify_hours: int = 24

    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    upload_dir: str = "./data/uploads"
    backup_dir: str = "./data/backups"
    max_upload_bytes: int = 10 * 1024 * 1024
    webhook_allow_private_urls: bool = False
    webhook_worker_interval_seconds: int = 5
    webhook_max_attempts: int = 5

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"

    # Optional shared Redis (rate limits, live-event fan-out, job lock). Empty = single instance, everything in memory.
    # Use redis://:PASSWORD@host:6379/0 or rediss:// and keep it on a private network: every tenant's live events pass through it.
    redis_url: str = ""
    redis_channel: str = "worksphere:events"

    stun_urls: str = "stun:stun.l.google.com:19302"
    turn_url: str = ""
    turn_username: str = ""
    turn_credential: str = ""
    turn_secret: str = ""  # coturn use-auth-secret: issue short-lived credentials instead of static ones

    @field_validator("secret_key")
    @classmethod
    def _secret_len(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
