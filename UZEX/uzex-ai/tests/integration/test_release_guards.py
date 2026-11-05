import httpx
import pytest

from app.api.application import create_app
from app.core.config import Settings
from app.services.chat_service import ChatService


@pytest.mark.anyio
async def test_chunked_body_budget_without_content_length():
    app = create_app(Settings(app_env="test"))

    async def chunks():
        for _ in range(70):
            yield b"x" * 1024

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat", content=chunks())
    assert response.status_code == 413


@pytest.mark.anyio
async def test_default_chat_cache_keeps_no_content():
    class Router:
        pass

    service = ChatService(Router())
    assert service.cache._maxsize == 0
    assert await service.cache.get("private-example") is None
    assert not service.cache._cache
