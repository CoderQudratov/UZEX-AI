# Data warehouse design — Phase 2

## Source and scope

The sole authority is `uzex_spot_data.zip`. The whole README was read before schema work;
all nine CSV headers, samples and categorical distributions were inspected. README declares
the data synthetic. No source fields or relationships were invented. Typed tables contain
only mapped source columns; derived values are confined to a non-materialized view.

The builder pins the approved ZIP SHA-256. A different archive is rejected, including one
with the same filename. A later approved dataset requires an explicit reviewed checksum,
count/schema update and integrity run; there is no silent auto-discovery or fallback.

## Build and publication

Run with Python 3.12 from the installed project:

```bash
.venv/bin/python scripts/build_database.py --archive /home/doston/Downloads/uzex_spot_data.zip
.venv/bin/python -m pytest -q -c pyproject.toml tests --source-archive=/home/doston/Downloads/uzex_spot_data.zip
.venv/bin/python scripts/benchmark_warehouse.py
```

Default output: `data/processed/uzex.duckdb`, alongside `schema_catalog.json` and
`build_report.json`. The catalog is the machine-readable mapping, status dictionary,
join allowlist, semantics, exact source-file checksums and logical dataset version.
The report contains actual counts/check results, timing and closed database SHA-256.
Neither artifact contains user questions or query plans.

Preparation is offline only. ZIP paths, membership, symlinks and uncompressed size are
checked; no archive instructions are executed. Exactly one CSV is temporarily copied into
a controlled build directory, read with explicitly declared VARCHAR columns by DuckDB,
validated, typed, inserted and deleted. There is no pandas dependency or all-deals Python
list. The largest source file is about 35.5 MB. Temporary build resources are cleaned on
failure. The old final database is untouched until the new artifact passes all checks.

Tables have explicit types, NOT NULL constraints and primary keys. All parent uniqueness,
foreign-key coverage and per-join cardinalities pass before the enriched view is created.
The view is then checked for exactly 500,000 unique deal rows. No implicit status filters
or grouping summaries are applied. CHECKPOINT completes before closing and publication;
no WAL is shipped. The final file is chmod 0444 and published by atomic replacement.
Run builds while the service is stopped; database, catalog and report are individually
atomic files, not a transactional multi-file publication protocol.

Rebuilding guarantees canonical typed-content identity (logical SHA-256), not byte-identical
DuckDB headers/layout. The test suite performs a second build in a temporary directory and
compares the logical/source checksums. The artifact checksum identifies each physical file.

## Types and exact financial semantics

- Deal/contract IDs are positive validated BIGINT identifiers; duplicate/cast collisions fail.
- STIR/INN, TN VED and broker codes are VARCHAR. Nine-digit STIR including leading zeros is
  preserved. Original names, products, regions and codes are not transliterated or normalized.
- Quantities and lot sizes are BIGINT (observed source values are integral). They must be
  positive; delivered lots may be NULL, otherwise between zero and quantity.
- Money and starting/base prices are DECIMAL(18,2); rates DECIMAL(12,2).
  Financial syntax is checked before casting, including valid three-digit space grouping.
  Exponents, commas, NaN/Infinity, negatives and more than two fractional digits fail;
  rounding an invalid input into the allowed scale is forbidden.
- Deposit percent is DECIMAL(5,2), in percentage points: source `10 %` becomes 10.00.
- Required dates parse exactly DD.MM.YYYY into DATE. Local deal TIME remains Asia/Tashkent
  wall-clock time. Missing payment/delivery dates and delivered lots remain NULL, not zero.
  Product attribute blanks also become declared NULLs.
- Snapshot status is end of 2026-10-30. Deal dates range 2022-01-03–2026-10-30; daily
  USD/UZS rates cover 2022-01-01–2026-10-31, with exactly 1,765 unique contiguous dates.
- `volume = quantity * lot_size` and `delivered_volume = delivered_lots * lot_size` use
  HUGEINT multiplication (not floating point). NULL delivery propagates. Volumes must be
  grouped by their recorded measurement unit; no kg/ton conversion is assumed.
- The original amount is in the joined contract currency. USD converts using the rate
  on deal_date; UZS stays unchanged. `amount_uzs` is DECIMAL(30,4), SUM is DECIMAL(38,4).
  Never sum original amounts across UZS and USD. Aggregates in tests remain currency-separated.
- Exact unit price is represented by `unit_price_numerator=amount` and
  `unit_price_denominator=volume`. `unit_price_rounded_8` is a separately named DECIMAL(38,8)
  quote, rounded HALF_UP using integer arithmetic. It is not an asserted exact finite ratio.
  The exact numerator and denominator remain available for later precision policies.
  DuckDB decimal `/` returns floating point, so it is deliberately absent from this view's
  financial calculations. See the official numeric-types reference below.
- Cancelled, paid-only and partially fulfilled transactions remain distinct and present.
  No default cancellation/partial-delivery exclusions exist. Query meaning must choose filters
  explicitly in Phase 3 and later.

## Relationships and enriched view

`deals -> contracts`, seller/buyer `-> participants`, seller/buyer broker `-> brokers`,
and `deal_date -> usd_rates.rate_date` are many-to-one, validated for all rows. Contract
seller also refers to participants. Primary keys enforce parent uniqueness; foreign-key
coverage is explicitly validated rather than delegated to runtime writes (which are forbidden).

`deals_enriched` contains original deal fields, joined contract product/classification/currency,
warehouse and deadline attributes, seller/buyer names/regions, seller/buyer broker names,
rate, exact volumes, UZS conversion and explicit unit-price operands/rounded quote.
It is a view, not a second stored 500,000-row table. The catalog lists all view fields/types.

Region strings differ by language across contracts and deals. Fourteen one-to-one aliases
were verified against every source deal-contract relationship and are fixed in
`app/db/source_regions.json`. The original columns are preserved; aliases are only used
for integrity validation. Tashkent city and Tashkent region remain separate.

## Runtime boundary

`ReadOnlyWarehouse(Settings(...))` is explicitly initialized by future orchestration,
never by `/health` or module import. The path comes from deployment settings, not user/LLM
text. Each read gets its own connection and cursor; no shared cursor is reused concurrently.
A single process-wide manager is intended. Its bounded semaphore follows
MAX_CONCURRENT_QUERIES, with a one-second lease wait. Settings are identical across connections
because DuckDB may share the underlying database instance/cache.

Connections open `read_only=True`, disallow external file/network access, extension
loading/autoinstallation, settings reconfiguration and logging. Engine memory is capped
at 128 MB with one worker thread. Empty temp_directory and zero spill budget prohibit disk
spilling. Oversized queries fail closed rather than creating temporary files. The full-width
500,000-row source audit sorts under a separate offline 512 MB budget; it is not a supported
runtime result payload.

Each lease has a five-second absolute execution window: a timer interrupts an active
DuckDB query and all execute/fetch operations check the deadline. The timer is cancelled
and joined before the connection closes. Timeout/capacity/internal errors are separate safe
exception types with no SQL, path or request text. A connection is always closed and capacity
released. The test suite verifies interruption, idle-deadline rejection and capacity reuse.

This is an internal connection layer, not a public SQL executor. Only Phase 3's deterministic
compiler may supply SQL. DuckDB configuration is defense in depth; it does not replace
allowlisting typed plans or request/response size limits. No HTTP query endpoint exists here.

## Indexes, artifacts and performance

Only primary-key ART indexes needed for uniqueness are present. No speculative index,
materialized summary, external extension, new dependency, chat table or user-data cache
was added. Fixed integrity lookup/count/currency-reconciliation reads are measured with
30 samples after three warm-ups per operation. Measurements include lease/open/close and
use a warm OS filesystem cache. They are not AI, HTTP, concurrency or Render performance.
Actual numbers are in `docs/warehouse_performance.json` and the phase report.

Docker includes `data/processed`. Git explicitly allows only the final prepared database,
catalog and build report there so Git-backed Render builds also receive them; raw archives,
credentials and WAL/temp files remain excluded. The prepared file has read-only mode for the non-root container. Docker execution
remains unavailable on this machine and is not claimed as tested. `/health` remains a pure
liveness response; application startup does not implicitly query the warehouse.

## Original Russian-to-English mappings

All table columns below correspond one-to-one to actual source columns. The machine-readable
catalog also records parser kind/nullability. Derived view fields are documented separately.

### participants

| Original source column | English column | Type | Nullable |
| --- | --- | --- | --- |
| ИНН | `inn` | `VARCHAR` | no |
| Наименование | `name` | `VARCHAR` | no |
| Регион | `region` | `VARCHAR` | no |
| Вид деятельности | `activity` | `VARCHAR` | no |
| Роль | `role` | `VARCHAR` | no |
| Плательщик НДС | `vat_payer` | `VARCHAR` | no |

### brokers

| Original source column | English column | Type | Nullable |
| --- | --- | --- | --- |
| Код брокера | `broker_code` | `VARCHAR` | no |
| Наименование | `name` | `VARCHAR` | no |
| ИНН | `inn` | `VARCHAR` | no |
| Регион | `region` | `VARCHAR` | no |

### usd_rates

| Original source column | English column | Type | Nullable |
| --- | --- | --- | --- |
| Дата | `rate_date` | `DATE` | no |
| Курс | `usd_uzs_rate` | `DECIMAL(12,2)` | no |

### contracts

| Original source column | English column | Type | Nullable |
| --- | --- | --- | --- |
| Номер контракта | `contract_id` | `BIGINT` | no |
| Наименование продукта | `product_name` | `VARCHAR` | no |
| Марка товара | `brand` | `VARCHAR` | yes |
| Размер товара | `size` | `VARCHAR` | yes |
| Сорт товара | `grade` | `VARCHAR` | yes |
| Тип товара | `product_type` | `VARCHAR` | yes |
| Класс товара | `product_class` | `VARCHAR` | yes |
| Код ТН ВЭД | `tn_ved_code` | `VARCHAR` | no |
| Группа товара | `product_group` | `VARCHAR` | no |
| Категория товара | `product_category` | `VARCHAR` | no |
| Отрасль промышленности | `industry` | `VARCHAR` | no |
| Единица измерения | `unit` | `VARCHAR` | no |
| Лот | `lot_size` | `BIGINT` | no |
| Валюта | `currency` | `VARCHAR` | no |
| Базисная цена | `base_price` | `DECIMAL(18,2)` | no |
| Сумма залога | `deposit_percent` | `DECIMAL(5,2)` | no |
| Базис поставки | `delivery_basis` | `VARCHAR` | no |
| Регион | `region` | `VARCHAR` | no |
| Адрес склада | `warehouse_address` | `VARCHAR` | no |
| Тип торгов | `auction_type` | `VARCHAR` | no |
| Тип контракта | `contract_type` | `VARCHAR` | no |
| Форма контракта | `contract_form` | `VARCHAR` | no |
| Срок оплаты | `payment_days` | `INTEGER` | no |
| Срок поставки | `delivery_days` | `INTEGER` | no |
| Упаковка | `packaging` | `VARCHAR` | no |
| ИНН продавца | `seller_inn` | `VARCHAR` | no |
| Дата регистрации | `registered_date` | `DATE` | no |
| Действует до | `valid_until` | `DATE` | no |

### deals

| Original source column | English column | Type | Nullable |
| --- | --- | --- | --- |
| Номер сделки | `deal_id` | `BIGINT` | no |
| Дата сделки | `deal_date` | `DATE` | no |
| Время сделки | `deal_time` | `TIME` | no |
| Тип торгов | `auction_type` | `VARCHAR` | no |
| Количество | `quantity` | `BIGINT` | no |
| Сумма сделки | `amount` | `DECIMAL(18,2)` | no |
| Стартовая цена | `starting_price` | `DECIMAL(18,2)` | no |
| Номер контракта | `contract_id` | `BIGINT` | no |
| Наименование товара | `product_description` | `VARCHAR` | no |
| Лот | `lot_size` | `BIGINT` | no |
| Единица измерения | `unit` | `VARCHAR` | no |
| Регион | `region` | `VARCHAR` | no |
| Тип контракта | `contract_type` | `VARCHAR` | no |
| Форма контракта | `contract_form` | `VARCHAR` | no |
| Состояние сделки | `status` | `VARCHAR` | no |
| ИНН продавца | `seller_inn` | `VARCHAR` | no |
| ИНН покупателя | `buyer_inn` | `VARCHAR` | no |
| Брокер продавца | `seller_broker_code` | `VARCHAR` | no |
| Брокер покупателя | `buyer_broker_code` | `VARCHAR` | no |
| Дата оплаты | `payment_date` | `DATE` | yes |
| Дата поставки | `delivery_date` | `DATE` | yes |
| Поставлено | `delivered_lots` | `BIGINT` | yes |

## Primary references

- [DuckDB numeric types and decimal division](https://duckdb.org/docs/current/sql/data_types/numeric)
- [DuckDB configuration](https://duckdb.org/docs/stable/configuration/overview)
- [DuckDB CSV import](https://duckdb.org/docs/stable/data/csv/overview)

