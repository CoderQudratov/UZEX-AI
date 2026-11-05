"""Privileged offline preparation. No runtime request path imports this module."""
# ruff: noqa: S608
# SQL fragments below use only fixed SCHEMA constants. Data values use bound parameters;
# this privileged offline module never receives SQL/identifiers from requests or an LLM.

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath

import duckdb

from app.db.integrity import IntegrityError, validate
from app.db.schema import EXPECTED_COUNTS, JOINS, PRIMARY_KEYS, SCHEMA, STATUSES, UNITS, YEAR_COUNTS

SOURCE_SHA256 = "88182bf4dad3569eea5fac611e8a16db7a455110fdaa6495650e7d87e09ac258"
NUMBER_PATTERN = r"(?:[0-9]+|[0-9]{1,3}(?: [0-9]{3})+)(?:\.[0-9]{1,2})?"
# Exact integer arithmetic: amount has two decimal places; quote scale is eight.
# Positive-price ROUND_HALF_UP; no DOUBLE division enters the financial path.
ENRICHED_VIEW = """
CREATE VIEW deals_enriched AS
WITH joined AS (
    SELECT d.*, c.currency, c.product_name, c.brand, c.size, c.grade,
        c.product_type, c.product_class, c.tn_ved_code, c.product_group,
        c.product_category, c.industry, c.region AS contract_region,
        c.warehouse_address, c.delivery_basis, c.packaging,
        c.base_price, c.deposit_percent, c.payment_days, c.delivery_days,
        c.registered_date, c.valid_until,
        s.name AS seller_name, s.region AS seller_region,
        b.name AS buyer_name, b.region AS buyer_region,
        sb.name AS seller_broker_name, bb.name AS buyer_broker_name,
        r.usd_uzs_rate,
        d.quantity::HUGEINT * d.lot_size::HUGEINT AS volume,
        d.delivered_lots::HUGEINT * d.lot_size::HUGEINT AS delivered_volume,
        CASE WHEN c.currency='Доллар США'
            THEN d.amount * r.usd_uzs_rate
            ELSE CAST(d.amount AS DECIMAL(30,4)) END AS amount_uzs
    FROM deals d
    JOIN contracts c ON d.contract_id=c.contract_id
    JOIN participants s ON d.seller_inn=s.inn
    JOIN participants b ON d.buyer_inn=b.inn
    JOIN brokers sb ON d.seller_broker_code=sb.broker_code
    JOIN brokers bb ON d.buyer_broker_code=bb.broker_code
    JOIN usd_rates r ON d.deal_date=r.rate_date
)
SELECT *, amount AS unit_price_numerator, volume AS unit_price_denominator,
    CAST(((CAST(amount * 100 AS HUGEINT) * 1000000 + volume // 2)
         // NULLIF(volume, 0)) AS DECIMAL(30,0))
        * CAST('0.00000001' AS DECIMAL(9,8)) AS unit_price_rounded_8
FROM joined
"""


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    expected = {f"{name}.csv" for name in SCHEMA if name != "deals"}
    expected |= {f"deals_{year}.csv" for year in YEAR_COUNTS} | {"README.md"}
    members = {}
    total = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise IntegrityError("Unsafe archive member path")
        total += info.file_size
        if total > 500_000_000 or info.file_size > 200_000_000:
            raise IntegrityError("Archive exceeds source size budget")
        if info.is_dir():
            continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise IntegrityError("Archive links are forbidden")
        if path.name not in expected or path.name in members:
            raise IntegrityError("Unexpected or duplicate archive member")
        members[path.name] = info
    if set(members) != expected:
        raise IntegrityError("Missing source member")
    return members


def source_files(table: str) -> list[str]:
    return [f"deals_{y}.csv" for y in YEAR_COUNTS] if table == "deals" else [f"{table}.csv"]


def raw_condition(column) -> tuple[str, str]:
    """Only fixed schema identifiers are compiled here, not source/request text."""
    field = '"' + column.source + '"'
    if column.kind == "money":
        condition = f"regexp_full_match({field}, '{NUMBER_PATTERN}')"
        expression = f"CAST(replace({field}, ' ', '') AS {column.sql_type})"
    elif column.kind in ("integer", "id"):
        condition = f"regexp_full_match({field}, '[0-9]+')"
        expression = f"CAST({field} AS {column.sql_type})"
    elif column.kind == "inn":
        condition, expression = f"regexp_full_match({field}, '[0-9]{{9}}')", field
    elif column.kind == "broker":
        condition, expression = f"regexp_full_match({field}, 'BK[0-9]{{3}}')", field
    elif column.kind == "code":
        condition, expression = f"regexp_full_match({field}, '[0-9]+')", field
    elif column.kind == "percent":
        condition = f"regexp_full_match({field}, '[0-9]{{1,3}}(?:\\.[0-9]{{1,2}})? %')"
        expression = f"CAST(replace({field}, ' %', '') AS {column.sql_type})"
    elif column.kind == "date":
        condition = f"regexp_full_match({field}, '[0-9]{{2}}\\.[0-9]{{2}}\\.[0-9]{{4}}')"
        expression = f"CAST(strptime({field}, '%d.%m.%Y') AS DATE)"
    elif column.kind == "time":
        condition = f"regexp_full_match({field}, '[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}')"
        expression = f"CAST({field} AS TIME)"
    else:
        condition, expression = f"length({field})>0", field
    invalid = f"({field} IS NOT NULL AND NOT ({condition}))"
    if not column.nullable:
        invalid = f"({field} IS NULL OR {invalid})"
    return invalid, expression + ' AS "' + column.name + '"'


def create_tables(connection):
    for table, columns in SCHEMA.items():
        ddl = []
        for col in columns:
            suffix = "" if col.nullable else " NOT NULL"
            if col.name == PRIMARY_KEYS[table]:
                suffix += " PRIMARY KEY"
            ddl.append(f'"{col.name}" {col.sql_type}{suffix}')
        connection.execute(f"CREATE TABLE {table} ({', '.join(ddl)})")


def import_csv(connection, table: str, path: Path) -> int:
    columns = SCHEMA[table]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        if next(csv.reader(handle)) != [c.source for c in columns]:
            raise IntegrityError("CSV header mismatch")
    connection.execute("DROP TABLE IF EXISTS raw_import")
    connection.execute(
        """CREATE TEMP TABLE raw_import AS
        SELECT * FROM read_csv(?, header=true, auto_detect=false, delim=',',
            quote='"', escape='"', columns=?, nullstr='', strict_mode=true,
            ignore_errors=false, parallel=false, max_line_size=1048576)""",
        [str(path), {c.source: "VARCHAR" for c in columns}],
    )
    expressions = []
    for col in columns:
        invalid, expression = raw_condition(col)
        if connection.execute(f"SELECT count(*) FROM raw_import WHERE {invalid}").fetchone()[0]:
            raise IntegrityError(f"Invalid source type: {table}.{col.name}")
        expressions.append(expression)
    count = connection.execute("SELECT count(*) FROM raw_import").fetchone()[0]
    connection.execute(f"INSERT INTO {table} SELECT {', '.join(expressions)} FROM raw_import")
    connection.execute("DROP TABLE raw_import")
    return count


def logical_digest(connection) -> str:
    """Canonical typed content fingerprint, independent of DuckDB file headers/layout."""
    digest = hashlib.sha256()
    for table in SCHEMA:
        digest.update((table + "\n").encode())
        cursor = connection.execute(f"SELECT * FROM {table} ORDER BY {PRIMARY_KEYS[table]}")
        while rows := cursor.fetchmany(4096):
            for row in rows:
                digest.update(
                    (
                        json.dumps(row, default=str, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    ).encode()
                )
    return digest.hexdigest()


def catalog(connection, source_hash, source_manifest, logical_hash):
    return {
        "schema_version": 1,
        "dataset_version": f"sha256:{source_hash}",
        "source_sha256": source_hash,
        "logical_sha256": logical_hash,
        "synthetic_source": True,
        "source_files": source_manifest,
        "duckdb_version": duckdb.__version__,
        "tables": {
            table: {
                "primary_key": PRIMARY_KEYS[table],
                "expected_rows": EXPECTED_COUNTS[table],
                "columns": [asdict(c) for c in columns],
            }
            for table, columns in SCHEMA.items()
        },
        "allowed_joins": [
            {
                "child": c,
                "foreign_key": fk,
                "parent": p,
                "parent_key": pk,
                "cardinality": "many-to-one",
            }
            for c, fk, p, pk in JOINS
        ],
        "statuses": STATUSES,
        "units": list(UNITS),
        "semantics": {
            "currency": (
                "amount/base_price/starting_price are in contract currency; never sum UZS+USD"
            ),
            "currency_values": {"Узбекский сум": "UZS", "Доллар США": "USD"},
            "amount_uzs": (
                "USD amount * usd_uzs_rate on deal_date; UZS amount unchanged; DECIMAL(30,4)"
            ),
            "volume": "quantity * lot_size, HUGEINT, in recorded unit; do not mix units",
            "delivered_volume": "delivered_lots * lot_size; NULL means absent evidence, not zero",
            "unit_price_exact": "unit_price_numerator / NULLIF(unit_price_denominator,0)",
            "unit_price_rounded_8": (
                "DECIMAL(38,8), positive ROUND_HALF_UP with exact integer arithmetic"
            ),
            "dates": "source DD.MM.YYYY; stored DATE; times Asia/Tashkent, no timezone conversion",
            "snapshot": "2026-10-30 end of day; rate coverage 2022-01-01 through 2026-10-31",
            "status_filter": (
                "No implicit exclusion: cancelled and partial transactions remain present"
            ),
            "empty_values": "Only declared nullable source fields become NULL; no silent coercion",
            "deposit_percent": "Source '10 %' becomes DECIMAL 10.00, percentage points, not money",
            "regions": (
                "Original Russian/Uzbek values preserved; "
                "fixed verified aliases used for validation"
            ),
        },
        "view": {
            "name": "deals_enriched",
            "rows": EXPECTED_COUNTS["deals"],
            "columns": [
                {"name": row[0], "sql_type": row[1]}
                for row in connection.execute("DESCRIBE deals_enriched").fetchall()
            ],
        },
    }


def build_database(archive_path: Path, output: Path) -> dict:
    start = time.perf_counter()
    source_hash = sha256(archive_path)
    if source_hash != SOURCE_SHA256:
        raise IntegrityError("Source checksum differs from the approved dataset")
    if output.suffix != ".duckdb":
        raise IntegrityError("Output must be a .duckdb artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    timings, manifest = {}, {}
    with tempfile.TemporaryDirectory(prefix=".uzex-build-", dir=output.parent) as work:
        staging = Path(work)
        database = staging / "warehouse.duckdb"
        with zipfile.ZipFile(archive_path) as archive:
            members = archive_members(archive)
            # Read the complete README before any table/schema import.
            archive.read(members["README.md"]).decode("utf-8-sig")
            with duckdb.connect(
                str(database),
                config={
                    "threads": 2,
                    "memory_limit": "512MB",
                    "temp_directory": str(staging / "spill"),
                    "autoload_known_extensions": False,
                    "autoinstall_known_extensions": False,
                },
            ) as connection:
                connection.execute("SET enable_logging=false")
                create_tables(connection)
                for table in SCHEMA:
                    stamp = time.perf_counter()
                    for filename in source_files(table):
                        path = staging / filename
                        with archive.open(members[filename]) as source, path.open("wb") as target:
                            shutil.copyfileobj(source, target, length=1024 * 1024)
                        count = import_csv(connection, table, path)
                        manifest[filename] = {
                            "rows": count,
                            "sha256": sha256(path),
                            "uncompressed_bytes": path.stat().st_size,
                        }
                        expected = (
                            YEAR_COUNTS[int(filename[6:10])]
                            if table == "deals"
                            else EXPECTED_COUNTS[table]
                        )
                        if count != expected:
                            raise IntegrityError("Source file row count mismatch")
                        path.unlink()
                    timings[f"import_{table}_seconds"] = round(time.perf_counter() - stamp, 6)
                stamp = time.perf_counter()
                validate(connection)
                # All base uniqueness and individual join cardinalities pass BEFORE creation.
                connection.execute(ENRICHED_VIEW)
                checks = validate(connection, include_view=True)
                timings["validation_seconds"] = round(time.perf_counter() - stamp, 6)
                stamp = time.perf_counter()
                logical_hash = logical_digest(connection)
                timings["logical_fingerprint_seconds"] = round(time.perf_counter() - stamp, 6)
                metadata = catalog(connection, source_hash, manifest, logical_hash)
                connection.execute("CHECKPOINT")
        database_hash, database_bytes = sha256(database), database.stat().st_size
        report = {
            "acceptance": "PASS",
            "source_sha256": source_hash,
            "logical_sha256": logical_hash,
            "database_sha256": database_hash,
            "database_bytes": database_bytes,
            "checks": checks,
            "timings": timings,
            "total_build_seconds": round(time.perf_counter() - start, 6),
            "extra_indexes": [],
            "materialized_summaries": [],
            "note": "Primary-key ART indexes enforce uniqueness; enriched data is a view.",
        }
        for filename, value in (("schema_catalog.json", metadata), ("build_report.json", report)):
            (staging / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        # Publish only a fully validated, checkpointed database. Failed builds preserve the old one.
        database.chmod(0o444)
        os.replace(database, output)
        for filename in ("schema_catalog.json", "build_report.json"):
            os.replace(staging / filename, output.parent / filename)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/processed/uzex.duckdb"))
    args = parser.parse_args()
    try:
        report = build_database(args.archive, args.output)
    except (OSError, ValueError, duckdb.Error, zipfile.BadZipFile):
        print(json.dumps({"acceptance": "FAIL", "error": "Warehouse build failed"}))
        return 1
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("acceptance", "database_bytes", "total_build_seconds", "logical_sha256")
            }
        )
    )
    return 0
