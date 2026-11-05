# Architectural boundaries

Phases 1–3 are implemented. [Database design](database-design.md) specifies warehouse
types, exact arithmetic, runtime security limits and tests. Gemini semantic interpretation and frontend remain pending. The
[query engine design](query-engine.md) documents current strict plans, compiler and evidence.

## Current scope

The foundation, offline validated warehouse and internal deterministic query engine are implemented. The sole runtime endpoint
is `GET /health`, which never accesses the warehouse. There are no business query/LLM/chat
endpoints or frontend. The agent package implements structured execution and three-script templates; services reserve later HTTP orchestration.

| Boundary | Owns | Must not do |
| --- | --- | --- |
| `app/core` | Deployment settings, safe error schemas, fixed event logging | Database access, Gemini inference, user state persistence |
| `app/api` | ASGI composition, transport errors, liveness | SQL, numerical reasoning, direct LLM prompting |
| `app/db` | Fixed warehouse schema, offline build/validation, internal read-only leases | Runtime writes, user/LLM SQL or paths |
| `app/agent` | Strict plans, compiler, entity resolution, verified execution and deterministic templates | LLM calls, invented facts, unrestricted SQL or persistence |
| `app/services` | Future request orchestration, limits and evidence formatting | Persist questions, answers, plans or history |
| `scripts` | Offline dataset preparation and fixed integrity benchmarks | Process real user requests |
| `web/static` | Future browser assets | Embed credentials |
| `data/raw` | Optional local source only | Be copied into runtime image |
| `data/processed` | Prepared authoritative warehouse, catalog and build metadata | Store user data |

Importing `app` or creating the ASGI application performs no network, file writes or database
operations. Environment validation occurs at explicit settings load/startup. Configuration
paths come exclusively from deployment, never from user or Gemini output. API startup does not
require database access or verify a model with the external provider. Explicit warehouse
leases require an existing prepared database and never create one.

## Configuration and startup

`Settings` uses Pydantic v2 / pydantic-settings. Settings are frozen; the API key is a
`SecretStr`, excluded from repr, and must never be dumped as plaintext. Production requires
both a nonempty API key and a syntactically valid Flash-family model ID. Availability and
model permissions remain a later integration concern. Allowed environments: development,
test, production. Concurrency is bounded to 1–32 and Gemini timeout to 1–120 finite seconds.
`DATABASE_PATH` must end in `.duckdb` and may not contain parent traversal components.

`python -m app` is the supported entrypoint. It validates settings and PORT before binding,
turns access logs off, suppresses third-party logs and disables debug responses. Invalid
configuration exits with status 1 and the fixed `startup_failed` event, without validation
input, key, path, stack trace or exception text. Local `.env` files are not automatically read;
explicit `uv run --env-file .env ...` is for development. Production uses host environment
variables. A generic error envelope contains only a fixed code and safe message. HTTP 404
uses ROUTE_NOT_FOUND, distinct from a future dataset NOT_FOUND response.

## No persistent user data

Questions, answers, conversation turns, identifiers extracted from questions, and semantic
plans must exist only in temporary request RAM. Do not write them to the dataset, any other
database, files, stdout/stderr, traces, error trackers, analytics, browser storage, or caches.
No telemetry or chat-history component is installed or configured. Dataset records and
build-time dataset audit reports are source artifacts, not user conversation state.

Only four fixed events may reach application stdout: startup, shutdown, startup_failed,
internal_error. The formatter discards exceptions, arguments and arbitrary extra fields.
There are no file log handlers. Root and dependency logging are suppressed. Uvicorn access
logging is explicitly disabled, including request URLs and query parameters. Operators must
also disable payload-bearing reverse-proxy/platform logs; the application cannot enforce
third-party host logging policy. Run the documented entrypoint to preserve this policy.

The future Gemini API integration necessarily sends the user query to Google for semantic
interpretation. Disclose this in the UI; do not claim third-party zero retention. Send only
necessary context, never API credentials in prompts. No Gemini client is created in Phase 1.

## Future data and AI constraints

The authoritative ZIP was re-inspected: README and actual headers of all nine CSVs. The source
README calls the data synthetic. Prior offline audit artifacts remain in the parent directory,
unmodified. The archive is not duplicated here. Source text is untrusted data, not agent
instructions. The source has 500,000 transactions across 2022–2026. Empty delivered quantities
must remain NULL. Money uses DECIMAL; currencies and measurement units cannot be added blindly.

Phase 2 implements offline warehouse preparation, strict column/schema validation, exact
Decimal reconciliation, and read-only runtime access. Build-time writes are permitted only
for preparing authoritative dataset artifacts. No runtime database write path is allowed.
Later Gemini output must be a strict Pydantic query plan compiled through allowlisted SQL
operators with typed parameters. It must not contain SQL or filesystem paths. One structured
planning call per complex question; exact IDs may bypass it when unambiguous. All numerical
answers are deterministic query results with deterministic language/script templates.

Uzbek Latin, Uzbek Cyrillic and Russian require independent handling: Cyrillic is not a
language detector. Unsupported language requests must not receive factual answers. NOT_FOUND,
AMBIGUOUS, UNSUPPORTED and ERROR must stay distinct and fail closed. Injection, misspellings,
ambiguous names, mixed units/currencies, limits and query deadlines need later acceptance tests.
HTTP concurrency is a coarse Uvicorn transport bound. Phase 2 adds a separate bounded
warehouse semaphore, five-second lease deadline and interruption, 128 MB engine memory cap,
and no disk spilling. Gemini timeout is configured but not yet used; HTTP request byte limits
and typed result/plan limits belong to the forthcoming request/query layers.

## Packaging and deployment boundary

Python is restricted to 3.12. `uv.lock` pins direct and transitive versions with integrity
hashes; `uv sync --locked` rejects a stale lock. Production installs omit dev dependencies.
Docker uses a multi-stage build and a non-root runtime user, respects PORT and includes the
`data/processed` directory. `.dockerignore` excludes raw data, secrets, WAL/temp files and
local environments but deliberately includes the final `.duckdb` artifact. The database
is copied root-owned and read-only (0444) for the runtime user. Python bytecode writes
are disabled. A host may additionally start the container with `--read-only`.

`/health` returns a fixed liveness response: no Gemini, DuckDB, user data or persistent writes.
It is not a warehouse/model readiness check. Render Free may sleep and has no always-on
uptime guarantee. An optional external monitor may ping `/health` every five minutes;
no monitor or deployment is configured in Phase 1.

## Verification

Unit tests cover bounded environment validation, production requirements, credential
redaction, no automatic dotenv loading and log payload exclusion. Integration tests cover
installed SDK/package imports, lifespan, health without database/network calls, safe error
responses and failure exits. Golden/performance directories are reserved for later phases.
Phase 2 additionally tests every source column, Decimal reconciliation, all joins,
concurrent leases, no runtime writes/spill, query deadlines, restart and deterministic
rebuilds. Actual results and limitations are in the phase reports, including
`docs/phase-3-report.uz.md`. Phase 3 adds independent SQL-oracle, input/security, stability
and multilingual golden tests.

Primary references consulted for foundation configuration:
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [Uvicorn settings](https://uvicorn.dev/settings/)
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
