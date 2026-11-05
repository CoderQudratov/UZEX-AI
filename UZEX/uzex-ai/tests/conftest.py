import pytest

NAMES = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "LLM_PROVIDER",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "DATABASE_PATH",
    "APP_ENV",
    "MAX_CONCURRENT_QUERIES",
    "GEMINI_TIMEOUT_SECONDS",
    "PORT",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def pytest_addoption(parser):
    from pathlib import Path

    parser.addoption("--source-archive", default=str(Path.home() / "Downloads/uzex_spot_data.zip"))


@pytest.fixture(scope="session")
def source_archive(request):
    from pathlib import Path

    path = Path(request.config.getoption("--source-archive"))
    assert path.is_file(), "Supply the authoritative ZIP with --source-archive"
    return path


@pytest.fixture(scope="session")
def warehouse_path():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data/processed/uzex.duckdb"
    assert path.is_file(), "Run scripts/build_database.py before warehouse acceptance tests"
    return path
