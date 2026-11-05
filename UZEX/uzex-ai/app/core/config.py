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
    llm_provider: Literal["gemini", "groq"] = "gemini"
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_model: str | None = None
    database_path: Path = Path("data/processed/uzex.duckdb")
    app_env: Literal["development", "test", "production"] = "development"
    max_concurrent_queries: int = Field(default=4, ge=1, le=32)
    gemini_timeout_seconds: float = Field(default=20, ge=1, le=120, allow_inf_nan=False)

    @field_validator("gemini_api_key", "gemini_model", "groq_api_key", "groq_model", mode="before")
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

    @field_validator("groq_model")
    @classmethod
    def reviewed_groq_model(cls, value: str | None) -> str | None:
        if value is not None and value not in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
            raise ValueError("An explicitly reviewed Groq model identifier is required")
        return value

    @property
    def llm_model(self) -> str | None:
        return self.groq_model if self.llm_provider == "groq" else self.gemini_model

    @model_validator(mode="after")
    def production_requirements(self) -> Self:
        key = self.groq_api_key if self.llm_provider == "groq" else self.gemini_api_key
        if self.app_env == "production" and (not key or not self.llm_model):
            raise ValueError("Production requires the selected provider credentials and model")
        return self


def load_settings() -> Settings:
    try:
        # Local .env is read only when explicitly selected by a developer; production
        # must use environment variables and never reads a local credentials file.
        return Settings()
    except ValueError:
        raise ConfigurationError("Application configuration is invalid") from None
