import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app.api.application import create_app
from app.core.config import ConfigurationError, Settings


@pytest.mark.parametrize(
    "module",
    [
        "app",
        "app.core",
        "app.db",
        "app.agent",
        "app.api",
        "app.services",
        "duckdb",
        "fastapi",
        "pydantic",
        "google.genai",
        "uvicorn",
        "httpx",
        "rapidfuzz",
    ],
)
def test_dependency_and_package_imports(module):
    assert importlib.import_module(module) is not None


@pytest.mark.anyio
async def test_health_without_gemini_database_or_writes(tmp_path, monkeypatch):
    import duckdb
    from google import genai

    def forbidden(*_args, **_kwargs):
        pytest.fail("Health/startup attempted network, database or disk write")

    app = create_app(Settings(app_env="test", database_path=tmp_path / "missing.duckdb"))
    monkeypatch.setattr(duckdb, "connect", forbidden)
    monkeypatch.setattr(genai, "Client", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        for _ in range(3):
            response = await client.get("/health?question=private-sentinel")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
        assert (await client.get("/does-not-exist")).json()["error"]["code"] == "ROUTE_NOT_FOUND"
        assert (await client.post("/health")).status_code == 405
        assert (await client.get("/docs")).status_code == 404
    assert list(tmp_path.iterdir()) == []
    assert not hasattr(app.state, "settings")


@pytest.mark.anyio
async def test_startup_invalid_environment_fails(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    app = create_app()
    with pytest.raises(ConfigurationError):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.anyio
async def test_errors_never_echo_input_or_internal_details():
    app = create_app(Settings(app_env="test"))

    @app.get("/test-internal")
    async def broken():
        raise RuntimeError("private-sql-and-key")

    @app.get("/test-http")
    async def http_failure():
        raise HTTPException(400, detail="private-http-details")

    @app.get("/test-validation")
    async def validate(amount: int):
        return {"amount": amount}

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client,
    ):
        internal = await client.get("/test-internal")
        assert internal.status_code == 500
        assert internal.json()["error"]["code"] == "ERROR"
        assert "private" not in internal.text
        http = await client.get("/test-http")
        assert http.status_code == 400
        assert "private" not in http.text
        invalid = await client.get("/test-validation?amount=private-input")
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INVALID_REQUEST"
        assert "private" not in invalid.text


def test_safe_startup_exit_and_logging():
    env = {**os.environ, "PORT": "private-invalid-port", "APP_ENV": "test"}
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "app"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"level": "ERROR", "event": "startup_failed"}
    assert result.stderr == ""
    assert "private" not in result.stdout


def test_real_server_health_and_no_payload_logs():
    import socket
    import time

    import httpx

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "APP_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "app"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            deadline = time.monotonic() + 10
            while True:
                try:
                    response = client.get("/health?question=private-user-sentinel", timeout=0.5)
                    break
                except httpx.TransportError:
                    if time.monotonic() >= deadline:
                        pytest.fail("Server did not start within 10 seconds")
                    time.sleep(0.02)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            assert client.get("/private-path?token=private-user-sentinel").status_code == 404
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            raise
    import signal

    # Uvicorn restores and re-raises SIGTERM after its lifespan shutdown completes.
    assert process.returncode in (0, -signal.SIGTERM)
    events = [json.loads(line)["event"] for line in stdout.splitlines()]
    assert events == ["startup", "shutdown"]
    assert "private" not in stdout + stderr
    assert stderr == ""
