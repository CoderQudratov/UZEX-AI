import csv
import io
import json
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import lru_cache

import duckdb
import pytest

from app.core.config import Settings
from app.db.build import build_database, sha256
from app.db.integrity import IntegrityError, validate
from app.db.runtime import DatabaseBusy, DatabaseUnavailable, ReadOnlyWarehouse
from app.db.schema import SCHEMA


def manager(path, concurrency=4):
    return ReadOnlyWarehouse(Settings(database_path=path, max_concurrent_queries=concurrency))


def rows(archive, filename):
    with archive.open("uzex_spot_data/" + filename) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


@pytest.fixture(scope="module")
def source_oracle(source_archive):
    sums, counts, statuses, volumes, delivered = (Counter() for _ in range(5))
    converted, missing, samples = Decimal(0), 0, {}
    with zipfile.ZipFile(source_archive) as archive:
        contracts = {r["Номер контракта"]: r for r in rows(archive, "contracts.csv")}
        rates = {r["Дата"]: Decimal(r["Курс"]) for r in rows(archive, "usd_rates.csv")}
        for year in range(2022, 2027):
            for index, r in enumerate(rows(archive, f"deals_{year}.csv")):
                currency = contracts[r["Номер контракта"]]["Валюта"]
                amount = Decimal(r["Сумма сделки"].replace(" ", ""))
                volume = int(r["Количество"]) * int(r["Лот"])
                sums[currency] += amount
                counts[currency] += 1
                statuses[r["Состояние сделки"]] += 1
                volumes[r["Единица измерения"]] += volume
                if r["Поставлено"]:
                    delivered[r["Единица измерения"]] += int(r["Поставлено"]) * int(r["Лот"])
                else:
                    missing += 1
                uzs = amount * rates[r["Дата сделки"]] if currency == "Доллар США" else amount
                converted += uzs
                if index % 997 == 0 or (currency, r["Состояние сделки"]) not in samples:
                    key = (currency, r["Состояние сделки"])
                    samples.setdefault(key, [])
                    samples[key].append((int(r["Номер сделки"]), amount, volume, uzs))
    return {
        "sums": sums,
        "currency_counts": counts,
        "statuses": statuses,
        "volumes": volumes,
        "delivered": delivered,
        "converted": converted,
        "missing": missing,
        "samples": [item for group in samples.values() for item in group],
    }


def test_counts_primary_keys_foreign_keys_and_cardinality(warehouse_path):
    with manager(warehouse_path).connection() as connection:
        checks = validate(connection, include_view=True)
        assert checks["enriched_count"] == 500000
        assert checks["enriched_unique"] == 0
        assert len(checks) >= 50


def test_exact_source_financial_and_quantity_reconciliation(warehouse_path, source_oracle):
    with manager(warehouse_path).connection() as c:
        assert (
            dict(
                c.execute(
                    "SELECT currency,sum(amount) FROM deals_enriched GROUP BY currency"
                ).fetchall()
            )
            == source_oracle["sums"]
        )
        assert (
            dict(
                c.execute(
                    "SELECT currency,count(*) FROM deals_enriched GROUP BY currency"
                ).fetchall()
            )
            == source_oracle["currency_counts"]
        )
        assert (
            c.execute("SELECT sum(amount_uzs) FROM deals_enriched").fetchone()[0]
            == source_oracle["converted"]
        )
        assert (
            dict(c.execute("SELECT status,count(*) FROM deals GROUP BY status").fetchall())
            == source_oracle["statuses"]
        )
        assert (
            dict(c.execute("SELECT unit,sum(volume) FROM deals_enriched GROUP BY unit").fetchall())
            == source_oracle["volumes"]
        )
        assert (
            dict(
                c.execute(
                    "SELECT unit,sum(delivered_volume) FROM deals_enriched GROUP BY unit"
                ).fetchall()
            )
            == source_oracle["delivered"]
        )
        assert (
            c.execute("SELECT count(*) FROM deals WHERE delivered_lots IS NULL").fetchone()[0]
            == source_oracle["missing"]
            == 46291
        )
        assert source_oracle["statuses"]["Аннулирован(Не оплачен)"] == 33719
        assert source_oracle["statuses"]["Исполнен(Частично)"] == 22648
        samples = source_oracle["samples"]
        ids = [r[0] for r in samples]
        actual = {
            r[0]: r[1:]
            for r in c.execute(
                """SELECT deal_id,amount,volume,amount_uzs,
            unit_price_rounded_8 FROM deals_enriched WHERE deal_id IN (SELECT unnest(?))""",
                [ids],
            ).fetchall()
        }
        with localcontext() as context:
            context.prec = 50
            for deal_id, amount, volume, uzs in samples:
                rounded = (amount / volume).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                assert actual[deal_id] == (amount, volume, uzs, rounded)
        types = c.execute("DESCRIBE deals_enriched").fetchall()
        assert not any(r[1] in ("DOUBLE", "FLOAT", "REAL") for r in types)


@lru_cache(maxsize=8192)
def source_date(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def python_value(column, value):
    if value == "" and column.nullable:
        return None
    match column.kind:
        case "id" | "integer":
            return int(value)
        case "money":
            return Decimal(value.replace(" ", ""))
        case "percent":
            return Decimal(value.removesuffix(" %"))
        case "date":
            return source_date(value)
        case "time":
            return datetime.strptime(value, "%H:%M:%S").time()
        case _:
            return value


def test_every_source_column_preserved(warehouse_path, source_archive):
    # Streaming independent Python parser vs typed DuckDB rows; no pandas/full deals list.
    # Offline full-width sort needs more RAM than a bounded runtime query. No spill.
    with (
        zipfile.ZipFile(source_archive) as archive,
        duckdb.connect(
            str(warehouse_path),
            read_only=True,
            config={"memory_limit": "512MB", "threads": 1, "temp_directory": ""},
        ) as c,
    ):
        for table, columns in SCHEMA.items():
            if table == "deals":
                cursor = c.execute("SELECT * FROM deals ORDER BY deal_id")
                for year in range(2022, 2027):
                    for row in rows(archive, f"deals_{year}.csv"):
                        expected = tuple(python_value(col, row[col.source]) for col in columns)
                        assert cursor.fetchone() == expected
                assert cursor.fetchone() is None
            else:
                expected = sorted(
                    tuple(python_value(col, r[col.source]) for col in columns)
                    for r in rows(archive, f"{table}.csv")
                )
                pk = {
                    "contracts": "contract_id",
                    "participants": "inn",
                    "brokers": "broker_code",
                    "usd_rates": "rate_date",
                }[table]
                assert c.execute(f"SELECT * FROM {table} ORDER BY {pk}").fetchall() == expected  # noqa: S608


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE forbidden(i INTEGER)",
        "DELETE FROM deals",
        "UPDATE deals SET amount=0",
        "SET enable_external_access=true",
        "SET enable_logging=true",
        "SET temp_directory='/tmp/forbidden-spill'",
        "SET lock_configuration=false",
        "SELECT * FROM read_csv('/etc/passwd')",
        "ATTACH '/tmp/forbidden-warehouse.duckdb' AS other",
        "INSTALL httpfs",
        "LOAD httpfs",
    ],
)
def test_runtime_blocks_writes_external_io_and_reconfiguration(warehouse_path, sql):
    with pytest.raises(DatabaseUnavailable, match="^Database operation could not be completed$"):
        with manager(warehouse_path).connection() as c:
            c.execute(sql)


def test_copy_out_is_blocked_without_creating_file(warehouse_path, tmp_path):
    with manager(warehouse_path).connection() as c:
        with pytest.raises(duckdb.PermissionException, match="disabled"):
            c.execute("COPY (SELECT 1) TO ?", [str(tmp_path / "forbidden.csv")])
    assert list(tmp_path.iterdir()) == []


def test_independent_concurrent_connections_and_capacity(warehouse_path):
    warehouse = manager(warehouse_path)

    def read(_):
        with warehouse.connection() as c:
            return c.execute("SELECT count(*),sum(amount) FROM deals").fetchone()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, range(12)))
    assert len(set(results)) == 1
    single = manager(warehouse_path, concurrency=1)
    with single.connection(), pytest.raises(DatabaseBusy):
        with single.connection():
            pass
    # A rejected/failed lease must not leak capacity.
    with single.connection() as c:
        assert c.execute("SELECT 1").fetchone() == (1,)


def test_missing_database_is_not_created(tmp_path):
    with pytest.raises(DatabaseUnavailable):
        with manager(tmp_path / "missing.duckdb").connection():
            pass
    assert not list(tmp_path.iterdir())


def test_no_runtime_file_modification_and_restart(warehouse_path):
    before = (
        sha256(warehouse_path),
        warehouse_path.stat().st_mtime_ns,
        sorted(p.name for p in warehouse_path.parent.iterdir()),
    )
    code = """from pathlib import Path
from app.core.config import Settings
from app.db.runtime import ReadOnlyWarehouse
import sys
with ReadOnlyWarehouse(Settings(database_path=Path(sys.argv[1]))).connection() as c:
    assert c.execute('SELECT count(*) FROM deals_enriched').fetchone()[0] == 500000
print('PASS')
"""
    for _ in range(2):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code, str(warehouse_path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        assert result.stdout.strip() == "PASS"
        assert result.stderr == ""
    assert (
        sha256(warehouse_path),
        warehouse_path.stat().st_mtime_ns,
        sorted(p.name for p in warehouse_path.parent.iterdir()),
    ) == before


def test_integrity_validator_rejects_corrupt_quantity(warehouse_path, tmp_path):
    copy = tmp_path / "corrupt.duckdb"
    shutil.copyfile(warehouse_path, copy)
    copy.chmod(0o600)
    with duckdb.connect(str(copy)) as c:
        c.execute("UPDATE deals SET quantity=0 WHERE deal_id=(SELECT min(deal_id) FROM deals)")
        with pytest.raises(IntegrityError, match="deal_positive"):
            validate(c)


def test_rebuild_is_logically_deterministic(warehouse_path, source_archive, tmp_path):
    catalog = json.loads(warehouse_path.with_name("schema_catalog.json").read_text())
    report = build_database(source_archive, tmp_path / "rebuilt.duckdb")
    assert report["acceptance"] == "PASS"
    assert report["logical_sha256"] == catalog["logical_sha256"]
    assert report["source_sha256"] == catalog["source_sha256"]
    assert len(list(tmp_path.iterdir())) == 3
    assert (tmp_path / "rebuilt.duckdb").stat().st_mode & 0o222 == 0


def test_memory_pressure_fails_without_spill_files(warehouse_path):
    before = sorted(p.name for p in warehouse_path.parent.iterdir())
    with pytest.raises(DatabaseUnavailable):
        with manager(warehouse_path).connection() as c:
            c.execute("SELECT * FROM deals ORDER BY deal_id")
    assert sorted(p.name for p in warehouse_path.parent.iterdir()) == before


def test_query_deadline_interrupts_and_releases_capacity(warehouse_path):
    import time

    from app.db.runtime import DatabaseTimeout

    warehouse = ReadOnlyWarehouse(Settings(database_path=warehouse_path), query_budget_seconds=0.03)
    start = time.monotonic()
    with pytest.raises(DatabaseTimeout):
        with warehouse.connection() as c:
            c.execute("SELECT sum(i*j) FROM range(1000000000) a(i),range(1000000000) b(j)")
    assert time.monotonic() - start < 3
    with warehouse.connection() as c:
        assert c.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(DatabaseTimeout):
        with warehouse.connection() as c:
            time.sleep(0.05)
            c.execute("SELECT 1")
