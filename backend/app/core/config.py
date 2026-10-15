from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://localhost:5432/screening"
    allowed_origins: list[str] = Field(default_factory=list)
    frontend_url: str | None = None
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)
    access_cookie_name: str = "screening_access"
    refresh_cookie_name: str = "screening_refresh"
    admin_email: str = "admin@company.com"
    seed_admin_password: SecretStr | None = None
    seed_hr_password: SecretStr | None = None
    # Resume uploads: PDF only, stored in PostgreSQL (resume_files). Keep these small: files are held in memory.
    resume_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    resume_max_pages: int = Field(default=50, ge=1, le=500)

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        """Managed hosts (Render, Heroku-style) hand out postgres:// or postgresql:// URLs; this app ships psycopg 3."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @model_validator(mode="after")
    def validate_cookie_settings(self):
        if self.app_env == "production" and not self.database_url.startswith("postgresql"):
            raise ValueError("DATABASE_URL must point to PostgreSQL in production")
        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true in production")
        if self.app_env == "production" and not self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS must contain the deployed frontend origin in production")
        if "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS must contain explicit origins, not a wildcard")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true when COOKIE_SAMESITE is none")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
