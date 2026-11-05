import sys
from types import SimpleNamespace

import httpx
import pytest

from app.api.application import create_app
from app.core.config import Settings


@pytest.mark.anyio
async def test_explicit_groq_provider_is_selected_without_gemini(monkeypatch, warehouse_path):
    created = []

    class Planner:
        def __init__(self, settings):
            created.append(settings.llm_provider)

    def forbidden(*args, **kwargs):
        pytest.fail("Unselected Gemini provider must not initialize")

    monkeypatch.setitem(sys.modules, "app.agent.groq_client", SimpleNamespace(GroqPlanner=Planner))
    monkeypatch.setattr("app.api.application.GeminiPlanner", forbidden)
    settings = Settings(
        app_env="production",
        database_path=warehouse_path,
        llm_provider="groq",
        groq_api_key="fixture-private-key",
        groq_model="openai/gpt-oss-120b",
    )
    app = create_app(settings)
    assert created == ["groq"]
    assert isinstance(app.state.chat_service.router.planner, Planner)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json()["llm_provider"] == "groq"
    assert response.json()["llm_model"] == "openai/gpt-oss-120b"
    assert "fixture-private-key" not in response.text
