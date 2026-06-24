"""Application configuration via pydantic-settings.

Fail-fast on missing SECRET_KEY when DEBUG is False to prevent insecure
production deployments. In DEBUG mode a placeholder key is generated so
local development never breaks.
"""
from __future__ import annotations

import secrets

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised, environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core ---
    APP_NAME: str = "fastapi-saas-starter"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # --- Security ---
    SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # --- Database / Cache ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- CORS ---
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Rate limiting ---
    RATE_LIMIT_DEFAULT: str = "60/minute"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Allow comma-separated env value; pydantic handles JSON natively."""
        if isinstance(value, str) and "," in value and not value.startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def model_post_init(self, __context: object) -> None:
        """Reject empty SECRET_KEY in non-DEBUG; auto-fill in DEBUG."""
        if not self.SECRET_KEY:
            if self.DEBUG:
                # Dev convenience: generate an ephemeral key so local boot works.
                object.__setattr__(self, "SECRET_KEY", secrets.token_urlsafe(32))
            else:
                raise RuntimeError(
                    "SECRET_KEY must be set when DEBUG is False. "
                    "Refusing to boot with an empty SECRET_KEY in production."
                )


_settings_cache: Settings | None = None


def get_settings() -> Settings:
    """Return a memoized Settings instance (lru-style for FastAPI Depends)."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
    return _settings_cache


def reset_settings_cache() -> None:
    """Drop the memoized Settings — used by tests after mutating env vars."""
    global _settings_cache
    _settings_cache = None
