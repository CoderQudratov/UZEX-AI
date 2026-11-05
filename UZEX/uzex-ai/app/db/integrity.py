"""Build/test-only invariants. SQL is fixed developer code; never user-controlled."""
# ruff: noqa: S608
# SQL fragments below use only fixed SCHEMA constants. Data values use bound parameters;
# this privileged offline module never receives SQL/identifiers from requests or an LLM.

import json
from pathlib import Path

import duckdb

from app.db.schema import EXPECTED_COUNTS, JOINS, PRIMARY_KEYS, STATUSES, UNITS, YEAR_COUNTS


class IntegrityError(ValueError):
    """A warehouse must not be published after any failed invariant."""


def validate(connection: duckdb.DuckDBPyConnection, *, include_view: bool = False) -> dict:
    checks = {}

    def require(label: str, sql: str, expected=0, parameters=None):
        actual = connection.execute(sql, parameters or []).fetchone()[0]
        if actual != expected:
            raise IntegrityError(f"Integrity check failed: {label}")
        checks[label] = actual

    for table, count in EXPECTED_COUNTS.items():
        key = PRIMARY_KEYS[table]
        require(f"count:{table}", f"SELECT count(*) FROM {table}", count)
        require(f"null_pk:{table}", f"SELECT count(*) FROM {table} WHERE {key} IS NULL")
        require(f"unique_pk:{table}", f"SELECT count(*)-count(DISTINCT {key}) FROM {table}")
    for year, count in YEAR_COUNTS.items():
        require(f"year:{year}", "SELECT count(*) FROM deals WHERE year(deal_date)=?", count, [year])
    for child, fk, parent, pk in JOINS:
        require(
            f"fk:{child}.{fk}",
            f"""SELECT count(*) FROM {child} d
            LEFT JOIN {parent} p ON d.{fk}=p.{pk} WHERE p.{pk} IS NULL""",
        )
        require(
            f"cardinality:{child}.{fk}",
            f"""SELECT count(*) FROM {child} d
            JOIN {parent} p ON d.{fk}=p.{pk}""",
            EXPECTED_COUNTS[child],
        )
    require(
        "currencies",
        "SELECT count(*) FROM contracts WHERE currency NOT IN (?,?)",
        parameters=["Узбекский сум", "Доллар США"],
    )
    require(
        "currency_contract_type",
        """SELECT count(*) FROM contracts WHERE
        (currency='Доллар США') != (contract_type='Экспортный')""",
    )
    require(
        "date_range",
        """SELECT count(*) FROM deals WHERE
        deal_date NOT BETWEEN DATE '2022-01-03' AND DATE '2026-10-30'""",
    )
    require(
        "rate_range",
        """SELECT CAST(max(rate_date)-min(rate_date)+1 AS BIGINT)
        FROM usd_rates""",
        EXPECTED_COUNTS["usd_rates"],
    )
    require("rate_min", "SELECT min(rate_date)::VARCHAR FROM usd_rates", "2022-01-01")
    require("rate_max", "SELECT max(rate_date)::VARCHAR FROM usd_rates", "2026-10-31")
    require("rates_positive", "SELECT count(*) FROM usd_rates WHERE usd_uzs_rate<=0")
    require(
        "deal_positive",
        """SELECT count(*) FROM deals WHERE deal_id<=0 OR contract_id<=0
        OR quantity<=0 OR lot_size<=0 OR amount<=0 OR starting_price<=0""",
    )
    require(
        "contract_positive",
        """SELECT count(*) FROM contracts WHERE contract_id<=0
        OR lot_size<=0 OR base_price<=0 OR payment_days<0 OR delivery_days<0
        OR deposit_percent<0 OR deposit_percent>100 OR registered_date>valid_until""",
    )
    require(
        "deal_units",
        "SELECT count(*) FROM deals WHERE unit NOT IN (SELECT unnest(?))",
        parameters=[list(UNITS)],
    )
    require(
        "contract_units",
        "SELECT count(*) FROM contracts WHERE unit NOT IN (SELECT unnest(?))",
        parameters=[list(UNITS)],
    )
    require(
        "statuses",
        "SELECT count(*) FROM deals WHERE status NOT IN (SELECT unnest(?))",
        parameters=[list(STATUSES)],
    )
    for table in ("deals", "contracts"):
        for field, values in {
            "auction_type": ["Английский аукцион", "Обратный аукцион", "Двусторонний аукцион"],
            "contract_type": ["Внутренний", "Экспортный"],
            "contract_form": ["Спот", "Форвард", "Фьючерс"],
        }.items():
            require(
                f"enum:{table}.{field}",
                f"SELECT count(*) FROM {table} WHERE {field} NOT IN (SELECT unnest(?))",
                parameters=[values],
            )
    require(
        "roles", "SELECT count(*) FROM participants WHERE role NOT IN ('Продавец','Покупатель')"
    )
    require("vat", "SELECT count(*) FROM participants WHERE vat_payer NOT IN ('Да','Нет')")
    require(
        "participant_roles",
        """SELECT count(*) FROM deals d
        JOIN participants s ON s.inn=d.seller_inn JOIN participants b ON b.inn=d.buyer_inn
        WHERE s.role!='Продавец' OR b.role!='Покупатель'""",
    )
    require(
        "contract_seller_role",
        """SELECT count(*) FROM contracts c JOIN participants p
        ON p.inn=c.seller_inn WHERE p.role!='Продавец'""",
    )
    require(
        "delivery_quantities",
        """SELECT count(*) FROM deals WHERE delivered_lots<0
        OR delivered_lots>quantity OR
        (status='Исполнен' AND (delivered_lots IS NULL OR delivered_lots!=quantity)) OR
        (status='Исполнен(Частично)' AND
            (delivered_lots IS NULL OR delivered_lots<=0 OR delivered_lots>=quantity))""",
    )
    require(
        "payment_dates",
        """SELECT count(*) FROM deals WHERE
        (status IN ('Исполнен','Исполнен(Частично)','Оплачен') AND payment_date IS NULL)
        OR (delivered_lots>0 AND delivery_date IS NULL)
        OR payment_date<deal_date OR delivery_date<deal_date OR delivery_date<payment_date
        OR payment_date>DATE '2026-10-30' OR delivery_date>DATE '2026-10-30'""",
    )
    require(
        "new_snapshot",
        """SELECT count(*) FROM deals WHERE
        status='Новый' AND deal_date!=DATE '2026-10-30'""",
    )
    require(
        "contract_dates",
        """SELECT count(*) FROM deals d JOIN contracts c USING(contract_id)
        WHERE d.deal_date<c.registered_date OR d.deal_date>c.valid_until""",
    )
    for field in (
        "unit",
        "lot_size",
        "auction_type",
        "contract_type",
        "contract_form",
        "seller_inn",
    ):
        require(
            f"contract_match:{field}",
            f"""SELECT count(*) FROM deals d
            JOIN contracts c USING(contract_id) WHERE d.{field} IS DISTINCT FROM c.{field}""",
        )
    regions = json.loads(Path(__file__).with_name("source_regions.json").read_text())
    require(
        "region_mapping",
        """SELECT count(*) FROM deals d JOIN contracts c USING(contract_id)
        WHERE map_extract_value(?, d.region) IS DISTINCT FROM c.region""",
        parameters=[{"key": list(regions), "value": list(regions.values())}],
    )
    if include_view:
        require("enriched_count", "SELECT count(*) FROM deals_enriched", EXPECTED_COUNTS["deals"])
        require("enriched_unique", "SELECT count(*)-count(DISTINCT deal_id) FROM deals_enriched")
    return checks
