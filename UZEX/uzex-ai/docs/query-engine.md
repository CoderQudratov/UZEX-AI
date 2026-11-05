# Phase 3 deterministic query engine

## Boundary and use

This phase implements a Python service accepting a validated `QueryPlan` and returning a
`VerifiedResult`. It adds no HTTP query endpoint, Gemini integration, natural-language
interpreter, frontend, chat history, analytics or request cache. `/health` is unchanged.

Initialize `QueryExecutor(Settings(...))` once before serving requests. Initialization hashes
the prepared database and matches it to its build report, approved dataset version and
catalog logical fingerprint; only actual source dictionaries/metadata remain in RAM.
Each execution checks the immutable artifact's inode/size/mtime signature. An artifact
changed under a running engine produces ERROR, never stale verified evidence. Deploy builds
while the service is stopped. Initialization fails closed with a safe deployment error.

```python
from app.agent.query_executor import QueryExecutor
from app.agent.query_models import Filter, Lookup, Order, QueryPlan
from app.core.config import Settings

engine = QueryExecutor(Settings())
lookup = engine.execute(
    QueryPlan(kind="lookup", lookup=Lookup(entity="transaction", identifier=100001))
)
ranking = engine.execute(
    QueryPlan(
        kind="aggregate",
        metrics=("sum_amount", "count"),
        money_mode="uzs",
        group_by=("seller_inn",),
        order_by=(Order(field="sum_amount"),),
        limit=10,
    )
)
# Consume in request RAM; never print/log/save plans, results, parameters or questions.
```

Python construction is strict: native tuple collections, date objects and Decimal objects
are accepted, while coercions from arbitrary Python lists/floats are not. For future JSON
integration use `QueryPlan.model_validate_json`: JSON arrays are accepted, and ISO date
filter strings are parsed in a field-aware validator. Dates must use full YYYY-MM-DD;
business date parsing and relative dates belong to Phase 4. `docs/query_plan.schema.json`
is generated from the model, not an independently maintained schema.

## Modules

- `query_models.py`: closed plan/result/evidence models, forbidden extra fields and strict
  primitive types. All supported language codes explicitly distinguish Uzbek scripts.
- `query_validator.py`: field-aware filter typing, arity/ranges, identifier/number bounds,
  shape restrictions, meaning of money/price/units and sort selections. Even unchecked
  `model_construct` / `model_copy` objects are revalidated. Pydantic serialization warnings
  are converted to safe rejection so malformed inputs cannot leak through stderr warnings.
- `query_compiler.py`: fixed field/operator/dimension/metric/lookup maps. Every value is
  bound separately; caller SQL, expressions, column aliases, paths and join conditions are
  absent from the input language. The compiler chooses only pre-approved, Phase-2-validated
  many-to-one joins. Lean operations avoid unnecessary participant/broker joins.
- `query_executor.py`: resolution, semantic probes, grouping bounds, exact arithmetic,
  deterministic sorting with complete tie-breakers, output guards and safe error statuses.
- `entity_resolver.py`: source-only RAM dictionary; normalization/transliteration, fixed
  verified region/status aliases, conservative product-family translations and RapidFuzz
  suggestions. No user-resolution history is cached.
- `evidence.py`: artifact-bound dataset version, snapshot, source tables and query evidence.
- `answer_formatter.py`: fixed Uzbek Latin, Uzbek Cyrillic and Russian plain-text templates.
  Entity/product names keep their recorded spelling. Units/status labels are translated
  deterministically. Output values come only from the result. The formatter does not emit
  SQL, exception strings or input text on unsupported-language requests.

## Capability map and limits

| Requested capability | Explicit representation |
| --- | --- |
| Transaction, contract, company STIR, broker lookup | `kind=lookup`; separate entity/key domains |
| Detailed transactions | `kind=records`, allowlisted projection and filters; default complete source deal fields plus currency and party names |
| Count, delivered count | `count`, `delivered_count`; delivered means recorded delivered_lots > 0 |
| Sum, arithmetic transaction mean, min/max amounts | `sum_amount`, `avg_amount`, `min_amount`, `max_amount` with explicit money_mode |
| Top sellers/buyers, product ranking, broker stats | explicit role/name/code/product group dimensions, metric sorting and bounded limit |
| Dates and monthly grouping | strict date filters; `<`, `<=`, `>`, `>=`, inclusive between; `month` dimension |
| Transaction statuses | exact observed `status` filters; all eight source states preserved |
| Contract form/type filters | `contract_form` and `contract_type`, never substituted for status |
| Contract status | **UNSUPPORTED: no such source column or dictionary exists**; reason CONTRACT_STATUS_ABSENT |
| Product code | exact VARCHAR `tn_ved_code` filter/resolution, leading zeros preserved |
| Currency | explicit original vs transaction-date UZS conversion |
| Comparison | two explicit disjoint inclusive date periods, side-by-side groups and values |
| Partial delivery | explicit status filter, known delivered count/volume and NULL evidence |
| Multiple filters | up to 16 AND filters with typed in/between/null operators |
| Unit prices | volume-weighted price; min/max per-deal rounded quote; ambiguous price_average rejected |

No unrecorded contract lifecycle status, invented product identity, automatic kg-to-ton
conversion, unsupported mathematical expression or implicit cancellation filter exists.
Comparisons do not invent zero amounts for absent periods or absent groups, and do not
invent growth percentages; explicit period dates accompany each observed row. A comparison
that would truncate a period is rejected rather than presented incompletely. Grouping by
a name means that recorded string, not an inferred corporate identity; use company INN
and broker codes (optionally with names) for entity rankings. Products group by recorded
product strings/classification; synonyms are not silently merged into a canonical product.

Hard limits: plan serialization 16 KiB; output 100 rows / 128 KiB JSON; 20,000 grouping
buckets; 3 dimensions; 8 metrics; 16 filters (up to 50 values each, strings <=256 characters);
4 entity references; 2 sort keys; 2 comparison periods. Output truncation is explicit in
evidence. Group cardinality is probed before result extraction. Memory exhaustion may
precede cardinality determination for a huge hash group: this is safe ERROR with no rows.

Phase 2's read-only leases, 128 MB DuckDB budget, no disk spilling, one worker thread,
MAX_CONCURRENT_QUERIES semaphore, one-second capacity wait and five-second execution
window remain active. All probes/execution within an operation share its lease/deadline.
The engine does not expose a raw SQL method. Compiler SQL is internal developer machinery,
not permission to pass user text to `ReadOnlyWarehouse`.

## Financial and statistical meaning

`money_mode` is mandatory for monetary metrics. `original` keeps the contract currency;
multiple currencies require a currency dimension or a filter leaving a single currency.
`uzs` converts each USD transaction using its own deal-date rate and keeps UZS unchanged.
Amount sums/min/max remain Decimal. Arithmetic `avg_amount` is sum of transaction amounts
/ transaction count, not an average unit price. `weighted_unit_price` is total amount /
total physical volume. Ratios use Python Decimal precision 60, ROUND_HALF_UP at eight
fractional digits; no binary floating-point division is used. Min/max unit prices refer
to per-transaction quotes already rounded at that precision, explicitly named in metadata.

Physical sums/prices require one unit or explicit grouping by unit. Summing lots additionally
requires common lot size and recorded unit; otherwise LOT_MEANING ambiguity is returned.
Original-money/physical threshold filters across incompatible currencies/units are also
ambiguous, even for a count query. Filter `amount` always means original amount;
`amount_uzs` is the converted amount. These are never silently interchanged.

Unknown delivery is not zero. SUM over all-NULL delivered quantities remains NULL.
Evidence records the number of missing delivered_lots values. A zero count is VERIFIED
when SQL proves it; empty detail/lookup or a missing amount population is NOT_FOUND.
All statuses, including cancelled and partly fulfilled, remain unless explicitly filtered.

## Entity resolution and languages

Dictionary values come from actual participants, brokers, contracts, transaction regions,
TN VED and the observed transaction-status dictionary. NFKC, case folding, apostrophe
normalization and Uzbek/Russian Cyrillic-to-Latin transliteration preserve a set of all
possible identifiers rather than a single winning match. Region translations are the 14
Phase-2-verified pairs. Product-family aliases only reference observed matching strings;
several recorded variants cause AMBIGUOUS. This finite alias set is not an exhaustive
translation system; Phase 4 must request clarification for unsupported names.

Exact unique normalized matches are verified. Exact collisions return candidates.
RapidFuzz WRatio >=82 produces **only AMBIGUOUS suggestions**, even if one suggestion
looks best. Identifier domains never use fuzzy matching. Unknown identifiers return
NOT_FOUND. Company/product suggestions are never silently selected. A caller can confirm
an exact recorded identifier/string in a later independent plan; no history is saved.

Templates support only `uz-Latn`, `uz-Cyrl`, `ru`. An unsupported formatter language returns
a polite language notice without factual rows. Natural-language detection, misspelling
interpretation and conversational context are not implemented here; they belong to Phase 4.
Templates are plain text, not trusted HTML; a future frontend must render using textContent.

## Verified result and privacy

`VerifiedResult` exposes status, rows, row_count, aggregate meanings, original currencies,
measurement units, resolved typed filters, evidence and dataset version. Evidence includes
actual source tables, snapshot, matched transaction count, grouping count, delivery gaps
and output-limit flags when applicable. Non-verified results carry no invented rows.
Statuses are VERIFIED, NOT_FOUND, AMBIGUOUS, UNSUPPORTED, ERROR; database timeout/capacity/
internal failures always use ERROR. No SQL or exception details are leaked in reason codes.

`internal_sql` contains safe parameterized compiler/probe SQL and bound parameters for
in-memory inspection. It is excluded from repr and normal model serialization. There is
no audit file/table/sink. **Do not log or persist it**, or the result/filters themselves.
Public SQL is not displayed by default. Serialized filters are request-local evidence,
not application logging. No user question, result, entity selection or plan is added to
source dictionaries or durable caches. Benchmarks save only aggregate technical timings.

## Verification and measurement

The full suite uses direct, independently written SQL as oracle for counts, sums, means,
rankings, lookups, date boundaries, monthly groups, period comparisons, code/status filters,
partial delivery and conversion. Independent Python Decimal checks price arithmetic.
Tests cover ambiguous names, all three scripts, invalid fields, literal injection payloads,
nonfinite/overflow values, input/output/group bounds, result stability, concurrent reads,
artifact tampering, timeout classification, no payload-bearing warnings and golden templates.
Phase 1/2 tests still run, including every source column and no runtime database writes.

```bash
.venv/bin/python -m pytest -q -c pyproject.toml tests --source-archive=/home/doston/Downloads/uzex_spot_data.zip
.venv/bin/python scripts/benchmark_query_engine.py
```

The benchmark initializes one engine, uses three warm-ups plus 30 sequential samples for
lookup/aggregation/ranking/multi-table details, and records p50 median / p95 nearest rank.
It includes plan validation, artifact signature check, semantic probes, compilation,
read-only connection lifecycle, exact arithmetic, bounded sorting and result validation.
It excludes initialization, formatting, Gemini and HTTP. OS file cache is warm; these are
local timings, not Render performance or a claim of sustained concurrent capacity.

Primary references:
- [Pydantic model construction and validation](https://pydantic.dev/docs/validation/dev/concepts/models/)
- [RapidFuzz process.extract](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html)
