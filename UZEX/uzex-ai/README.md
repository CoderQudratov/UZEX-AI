# UZEX AI — Project Foundation

Phases 1–3: Python 3.12 foundation, validated warehouse and deterministic query engine.
Health endpoint, privacy-preserving logs, locked dependencies and Docker configuration
are included. Gemini semantic interpretation and frontend remain pending.

The authoritative archive remains at `/home/doston/Downloads/uzex_spot_data.zip`.
Earlier dataset audit files remain in the parent directory. No persistent raw data is duplicated.
The source README labels the data synthetic.

## Install and verify

Use Python 3.12 and uv 0.13.7. Build the warehouse below before running the full
test suite. From this project directory:

```bash
uv sync --locked
uv run --locked python -m pytest -q -c pyproject.toml tests
uv run --locked ruff check .
uv run --locked python -c "import app; import duckdb; from google import genai"
```

`uv.lock` pins transitive dependencies. Do not regenerate it at container startup.
For a production-only local installation use `uv sync --locked --no-dev`.
Runtime dependency advisory check (sends package names/versions to the advisory service,
never application requests or credentials):

```bash
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file /tmp/uzex-foundation-runtime.txt
uv run --locked pip-audit --disable-pip --no-deps -r /tmp/uzex-foundation-runtime.txt
```

## Build the warehouse before warehouse tests

```bash
uv run --locked python scripts/build_database.py --archive /home/doston/Downloads/uzex_spot_data.zip
uv run --locked python -m pytest -q -c pyproject.toml tests --source-archive=/home/doston/Downloads/uzex_spot_data.zip
uv run --locked python scripts/benchmark_warehouse.py
```

Outputs: `data/processed/uzex.duckdb`, `schema_catalog.json`, `build_report.json`.
The build fails closed on a different source checksum or any invalid count/type/join.
Warehouse tests require the prepared file and original source ZIP (no critical skips).
For foundation-only tests before building, run `pytest tests/unit/test_config.py tests/unit/test_logging.py tests/integration/test_bootstrap.py`.
See [database design](docs/database-design.md) for all source mappings and exact arithmetic.

## Structured query engine (Phase 3)

Use `QueryExecutor(Settings()).execute(QueryPlan(...))` in Python. There is no raw SQL or
business query HTTP endpoint. See [query engine](docs/query-engine.md), including the closed
plan schema, currency/unit ambiguity rules, source evidence and privacy restrictions.

```bash
uv run --locked python scripts/benchmark_query_engine.py
```

Measured timings are in `docs/query_engine_performance.json`. Never log or save user plans,
parameters, filters, results or internal audit SQL. No Gemini call is made in Phase 3.

## Run locally

```bash
uv run --locked python -m app
```

Default: development, port 8000. `GET /health` returns `{"status":"ok"}` without Gemini
or a warehouse. Application import does not read configuration or connect to services.

For explicit local environment loading:

```bash
cp .env.example .env
# Edit .env locally; never commit it.
uv run --locked --env-file .env python -m app
```

| Variable | Default | Validation |
| --- | --- | --- |
| GEMINI_API_KEY | unset | Required in production; secret redacted |
| GEMINI_MODEL | unset | Required in production; Gemini Flash-family ID |
| DATABASE_PATH | data/processed/uzex.duckdb | Deployment path ending .duckdb, no parent traversal |
| APP_ENV | development | development, test, production |
| MAX_CONCURRENT_QUERIES | 4 | Integer 1–32 |
| GEMINI_TIMEOUT_SECONDS | 20 | Finite number 1–120 seconds |
| PORT | 8000 | Integer 1–65535 |

Environment names are case insensitive in settings; PORT is read by the entrypoint.
Production does not automatically load `.env`. Configure real secrets and an available
Flash model through the hosting environment. No Gemini API calls are made in this phase.
Settings validate DATABASE_PATH syntactically. The read-only connection layer additionally
requires an existing prepared file; `/health` does not access or verify it.

## Docker and Render preparation

```bash
docker build -t uzex-ai .
docker run --rm -p 8000:8000 -e APP_ENV=development uzex-ai
```

The image defaults to production and will fail startup without Gemini configuration.
Use the environment override above for a foundation smoke test. For Render, use Docker
and set production credentials/model in the dashboard; PORT is supplied by the host.
Deployment is outside Phase 1. The prepared database is copied from
`data/processed/`; both ignore files explicitly allow the three final artifacts for
Git-backed builds. Temporary/WAL files and raw archives stay excluded.
Render Free has no guaranteed always-on uptime. Health is liveness only.

## Privacy

No user questions, answers, identifiers, plans or conversation history are persisted.
No file logging, analytics or telemetry is configured. Only fixed lifecycle/error events
reach stdout; Uvicorn access logs and third-party logs are disabled by `python -m app`.
Use this entrypoint instead of a default logging-enabled Uvicorn command.

Future Gemini inference sends the query to Google. This is an external data transfer;
third-party zero retention is not guaranteed. Credentials never belong in frontend code.
See [architecture](docs/architecture.md) for boundaries and later-phase acceptance requirements.
