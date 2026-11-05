# Runtime release verification — 2026-11-05

Configured Gemini 3.8 Flash authentication/model metadata succeeded, but inference failed with HTTP 429: daily free-tier model quota (20 requests) exhausted. Gemini 3.5 Flash Lite returned HTTP 503 overload. A real minimal structured-output request to Gemini 3.6 Flash succeeded (2228.9 ms). The reviewed deployment configuration explicitly selects 3.6; no automatic fallback exists.

Eight real local POST /api/v1/chat requests using 3.6: six completed with correct language/script, validated semantics and evidence; two failed closed with provider 503. The completed numerical requests matched independent read-only DuckDB SQL. The unknown-name request returned AMBIGUOUS without fabricated facts. Source dictionary/SQL searches found no match for the investigated spelling variants. Request/response content is not retained in this report.

Completed inference latency only (n=6): Gemini p50/p95 8273.5/18210.2 ms; full local ASGI API p50/p95 8637.8/18229.7 ms. Two provider failures took 8312.9 and 9907.7 ms, reported separately. These are local measurements, not public hosting benchmarks or availability guarantees.

Executed: `.venv/bin/python -m pytest tests/ -q`: 590 passed in 58.67s. Ruff check and format check passed (78 files). Subsequent resource cleanup change: 50 bootstrap/API/diagnostic tests passed in 6.80s; Ruff rechecked.

Diagnostics permit only stage, exception_class, error_category, elapsed_ms and random request_id. No question, prompt, credential, SQL parameter or row value is logged. Database remains read-only. Default answer caching is disabled. Gemini receives the current question, schema and relevant entity candidates; no zero-retention guarantee is made for Google. Render Free can sleep and provider quota/overload remains an external limitation.
