import pytest
from pydantic import ValidationError

from app.core.config import ConfigurationError, Settings, load_settings


def test_development_needs_no_external_service():
    config = Settings()
    assert config.app_env == "development"
    assert config.gemini_api_key is None
    assert config.database_path.as_posix() == "data/processed/uzex.duckdb"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_ENV", "debug"),
        ("MAX_CONCURRENT_QUERIES", "0"),
        ("MAX_CONCURRENT_QUERIES", "33"),
        ("GEMINI_TIMEOUT_SECONDS", "0"),
        ("GEMINI_TIMEOUT_SECONDS", "nan"),
        ("GEMINI_TIMEOUT_SECONDS", "inf"),
        ("DATABASE_PATH", "../secret.duckdb"),
        ("DATABASE_PATH", "data/private.txt"),
        ("GEMINI_MODEL", "gemini-pro"),
    ],
)
def test_invalid_environment_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError, match="^Application configuration is invalid$"):
        load_settings()


def test_production_missing_credentials_fails(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigurationError):
        load_settings()


def test_environment_and_secret_redaction(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-private-credential")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-flash")
    monkeypatch.setenv("MAX_CONCURRENT_QUERIES", "2")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "7.5")
    config = load_settings()
    assert config.max_concurrent_queries == 2
    assert config.gemini_timeout_seconds == 7.5
    assert "fixture-private-credential" not in repr(config)
    assert "fixture-private-credential" not in config.model_dump_json()


def test_dotenv_is_never_implicitly_read(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("APP_ENV=production\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_settings().app_env == "development"


def test_settings_frozen():
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.app_env = "production"
