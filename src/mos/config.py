"""Application settings loaded from environment variables.

Kept deliberately small in Phase 1. Add a field here only when a module
actually reads it — speculative config is the opposite of what we're doing.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # allow .env to carry vars we haven't declared yet
    )

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://mos:mos_dev@localhost:5432/mos",
        alias="DATABASE_URL",
    )

    # --- Redis (Celery broker + result backend) ---
    redis_url: str = Field(
        default="redis://localhost:6379/0", alias="REDIS_URL"
    )

    # --- Object storage ---
    storage_endpoint: str = Field(
        default="http://localhost:9000", alias="STORAGE_ENDPOINT"
    )
    storage_access_key: str = Field(default="mos", alias="STORAGE_ACCESS_KEY")
    storage_secret_key: str = Field(
        default="mos_dev_secret", alias="STORAGE_SECRET_KEY"
    )
    storage_bucket: str = Field(
        default="mos-artifacts", alias="STORAGE_BUCKET"
    )
    storage_region: str = Field(default="us-east-1", alias="STORAGE_REGION")

    # --- Environment label ---
    env: str = Field(default="dev", alias="MOS_ENV")

    # --- Intent LLM (Groq) ---
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(
        default="llama-3.1-70b-versatile", alias="GROQ_MODEL"
    )


def get_settings() -> Settings:
    """Factory. Tests may override by constructing Settings() directly with
    keyword args, bypassing .env."""
    return Settings()
