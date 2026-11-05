"""Integration and contract tests for Phase 6 Web Frontend."""

import httpx
import pytest

from app.agent.query_executor import QueryExecutor
from app.agent.semantic_router import SemanticRouter
from app.api.application import create_app
from app.core.config import Settings


@pytest.fixture(scope="module")
def web_app(warehouse_path):
    settings = Settings(database_path=warehouse_path, app_env="test")
    engine = QueryExecutor(settings)
    router = SemanticRouter(engine, planner=None, max_concurrency=4)
    return create_app(settings, router=router)


@pytest.mark.anyio
async def test_frontend_root_and_static_assets(web_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app), base_url="http://test"
    ) as client:
        # 1. Root serves index.html
        res_root = await client.get("/")
        assert res_root.status_code == 200
        assert "text/html" in res_root.headers["content-type"]
        assert "UZEX AI" in res_root.text
        assert "Spot Analitika" in res_root.text
        assert "chat-input" in res_root.text

        # 2. CSS bundle serves cleanly
        res_css = await client.get("/static/style.css")
        assert res_css.status_code == 200
        assert "text/css" in res_css.headers["content-type"]
        assert "--primary" in res_css.text
        assert "@media (max-width: 640px)" in res_css.text

        # 3. JavaScript bundle serves cleanly
        res_js = await client.get("/static/app.js")
        assert res_js.status_code == 200
        assert "javascript" in res_js.headers["content-type"]
        assert "UI_TEXT" in res_js.text


def test_zero_persistent_storage_in_frontend():
    from pathlib import Path

    js_file = Path("web/static/app.js")
    assert js_file.is_file()
    js_code = js_file.read_text()

    # Verify no persistent browser storage mechanisms are used
    assert "localStorage" not in js_code
    assert "sessionStorage" not in js_code
    assert "indexedDB" not in js_code
    assert "document.cookie" not in js_code


@pytest.mark.anyio
async def test_frontend_chat_integration_uz_latn(web_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/chat", json={"message": "bitim 100001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["language"] == "uz"
        assert data["script"] == "latin"
        assert "100001" in data["answer"]
        assert data["evidence"]["source_count"] == 1


@pytest.mark.anyio
async def test_frontend_chat_integration_uz_cyrl(web_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/chat", json={"message": "битим 100001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["language"] == "uz"
        assert data["script"] == "cyrillic"
        assert "100001" in data["answer"]


@pytest.mark.anyio
async def test_frontend_chat_integration_ru(web_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/chat", json={"message": "сделка 100001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["language"] == "ru"
        assert data["script"] == "cyrillic"
        assert "100001" in data["answer"]


@pytest.mark.anyio
async def test_frontend_chat_integration_unsupported(web_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/chat", json={"message": "What is the weather?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "UNSUPPORTED"
        assert data["language"] == "unsupported"
        assert data["evidence"] is None
