from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    Values are loaded from environment variables / a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Literal["local", "development", "staging", "production", "test"] = "local"

    # Must be an async SQLAlchemy URL (asyncpg driver) — consumed directly by
    # backend/app/db/session.py's create_async_engine() and by alembic/env.py.
    # Port 5434, not 5432 — see .env.example.
    DATABASE_URL: str = "postgresql+asyncpg://agentops:agentops@localhost:5434/agentops_dev"

    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Authentication (Part 2). No default for JWT_SECRET on purpose — an
    # insecure default would let the app boot with a guessable secret.
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # AI provider (Phase 2). Optional at the Settings level, unlike
    # JWT_SECRET: the app must still start (and existing Phase 0/1
    # functionality, including tests, must still run) when no key is
    # configured. Code in app/ai/ is responsible for raising a clear error
    # if it is invoked without GEMINI_API_KEY set.
    #
    # Provider: Google Gemini Developer API (Free Tier — no billing).
    # gemini-2.5-flash-lite returns 404 for newer accounts/projects
    # ("no longer available to new users") — gemini-3.5-flash-lite is
    # Google's own recommended replacement and is Free Tier eligible on
    # https://ai.google.dev/gemini-api/docs/pricing. Get a free key (no
    # credit card) at https://aistudio.google.com/apikey.
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # Phase 8: the second entry in every model group's priority list (see
    # ai/router.py) — used when GEMINI_MODEL fails or is unavailable.
    # "gemini-flash-latest" is Google's own rolling alias for its current
    # recommended flash model, verified live against this project's real
    # API key: gemini-2.5-flash and gemini-2.0-flash both 404 ("no longer
    # available to new users", same issue GEMINI_MODEL's own comment
    # describes), but gemini-flash-latest resolves and responds correctly.
    # Also Free Tier eligible — same provider, same API key, no billing.
    GEMINI_FALLBACK_MODEL: str = "gemini-flash-latest"

    # Phase 6: a separate, smaller/cheaper model for embeddings, per the
    # blueprint ("Embeddings model (small/cheap, separate from the
    # reasoning model)"). Also Free Tier eligible — see
    # https://ai.google.dev/gemini-api/docs/pricing.
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # Phase 8: Redis response cache (app/ai/cache.py) — free, open-source
    # redis:7-alpine in Docker, no billing. Port 6380, not the default
    # 6379: this machine may already have another project's Redis
    # container bound to 6379 on the host (same reasoning as Postgres's
    # port 5434 — see DATABASE_URL above). Inside the Docker network this
    # service is still reachable at "redis:6379" (docker-compose.yml
    # overrides this for the backend service).
    REDIS_URL: str = "redis://localhost:6380/0"

    @field_validator("GEMINI_API_KEY", mode="before")
    @classmethod
    def clean_gemini_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().strip('"').strip("'")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
