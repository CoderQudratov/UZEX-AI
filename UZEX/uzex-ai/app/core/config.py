"""Typed deployment settings; no database, network or import-time environment reads."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Safe public startup failure; never wrap or expose the original validation text."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_model: str | None = None
    database_path: Path = Path("data/processed/uzex.duckdb")
    app_env: Literal["development", "test", "production"] = "development"
    max_concurrent_queries: int = Field(default=4, ge=1, le=32)
    gemini_timeout_seconds: float = Field(default=20, ge=1, le=120, allow_inf_nan=False)

    @field_validator("gemini_api_key", "gemini_model", mode="before")
    @classmethod
    def empty_to_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_path")
    @classmethod
    def database_file(cls, value: Path) -> Path:
        if value.suffix != ".duckdb" or ".." in value.parts:
            raise ValueError("Database must be a .duckdb deployment path without traversal")
        # No file operations: the warehouse does not exist in Phase 1.
        return value

    @field_validator("gemini_model")
    @classmethod
    def flash_model(cls, value: str | None) -> str | None:
        if value is not None:
            import re

            if not re.fullmatch(r"gemini-[a-z0-9.-]*flash[a-z0-9.-]*", value):
                raise ValueError("A Gemini Flash-family model identifier is required")
        return value

    @model_validator(mode="after")
    def production_requirements(self) -> Self:
        if self.app_env == "production" and (not self.gemini_api_key or not self.gemini_model):
            raise ValueError("Production requires Gemini credentials and a Flash model")
        return self


def load_settings() -> Settings:
    try:
        # Local .env is read only when explicitly selected by a developer; production
        # must use environment variables and never reads a local credentials file.
        return Settings()
    except ValueError:
        raise ConfigurationError("Application configuration is invalid") from None
