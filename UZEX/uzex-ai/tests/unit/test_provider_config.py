import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_groq_production_requires_only_selected_credentials():
    settings = Settings(
        app_env="production",
        llm_provider="groq",
        groq_api_key="fixture-groq-private-key",
        groq_model="openai/gpt-oss-120b",
    )
    assert settings.gemini_api_key is None
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert "fixture-groq-private-key" not in repr(settings)
    assert "fixture-groq-private-key" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"llm_provider": "other"},
        {"groq_model": "arbitrary-model"},
        {"app_env": "production", "llm_provider": "groq", "groq_model": "openai/gpt-oss-20b"},
        {"app_env": "production", "llm_provider": "gemini", "groq_api_key": "fixture-key"},
    ],
)
def test_unknown_provider_models_and_missing_credentials_fail_closed(kwargs):
    with pytest.raises(ValidationError):
        Settings(**kwargs)
