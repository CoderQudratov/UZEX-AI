import csv
import io
import zipfile

import duckdb
import pytest

from app.db.build import archive_members, build_database, create_tables, import_csv
from app.db.integrity import IntegrityError
from app.db.schema import SCHEMA


@pytest.fixture
def first_deal(source_archive):
    with zipfile.ZipFile(source_archive) as archive:
        with archive.open("uzex_spot_data/deals_2022.csv") as raw:
            return next(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


def write_csv(path, row):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[c.source for c in SCHEMA["deals"]])
        writer.writeheader()
        writer.writerow(row)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("Сумма сделки", "NaN"),
        ("Сумма сделки", "1.001"),
        ("Сумма сделки", "12 34"),
        ("Сумма сделки", "1e6"),
        ("Сумма сделки", "-1"),
        ("Сумма сделки", "1,20"),
        ("Сумма сделки", "9999999999999999999"),
        ("Сумма сделки", ""),
        ("ИНН продавца", "123"),
        ("Номер сделки", "1;DROP TABLE deals"),
        ("Количество", "1.5"),
        ("Дата сделки", "31.02.2026"),
        ("Дата сделки", "1.1.2026"),
        ("Время сделки", "25:00:00"),
    ],
)
def test_import_rejects_malformed_values(tmp_path, first_deal, field, invalid):
    first_deal[field] = invalid
    path = tmp_path / "deals.csv"
    write_csv(path, first_deal)
    with duckdb.connect() as connection:
        create_tables(connection)
        with pytest.raises((IntegrityError, duckdb.Error)):
            import_csv(connection, "deals", path)
        assert connection.execute("SELECT count(*) FROM deals").fetchone()[0] == 0


def test_null_and_leading_zero_identifiers_are_preserved(tmp_path, first_deal):
    first_deal.update({"ИНН продавца": "001234567", "Поставлено": "", "Дата поставки": ""})
    path = tmp_path / "deals.csv"
    write_csv(path, first_deal)
    with duckdb.connect() as connection:
        create_tables(connection)
        assert import_csv(connection, "deals", path) == 1
        assert connection.execute(
            "SELECT seller_inn,delivered_lots,delivery_date FROM deals"
        ).fetchone() == (
            "001234567",
            None,
            None,
        )


def test_header_mismatch_fails(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("invented_header\n1\n")
    with duckdb.connect() as connection, pytest.raises(IntegrityError, match="header mismatch"):
        import_csv(connection, "deals", path)


def test_failed_build_preserves_existing_artifact(tmp_path):
    source, output = tmp_path / "wrong.zip", tmp_path / "uzex.duckdb"
    source.write_bytes(b"wrong dataset")
    output.write_bytes(b"existing prepared artifact")
    with pytest.raises(IntegrityError, match="checksum"):
        build_database(source, output)
    assert output.read_bytes() == b"existing prepared artifact"
    assert not list(tmp_path.glob(".uzex-build-*"))


@pytest.mark.parametrize("member", ["../README.md", "/README.md", "a\\README.md", "extra.csv"])
def test_unexpected_archive_member_rejected(member):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(member, "x")
    with zipfile.ZipFile(stream) as archive, pytest.raises(IntegrityError):
        archive_members(archive)
