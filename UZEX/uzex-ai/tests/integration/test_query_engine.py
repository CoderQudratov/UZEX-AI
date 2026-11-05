# ruff: noqa: S608
# Independent oracle SQL fragments use only literal parameterized test cases, never requests.
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest
from pydantic import ValidationError

from app.agent.answer_formatter import format_answer
from app.agent.query_compiler import compile_plan
from app.agent.query_executor import QueryExecutor
from app.agent.query_models import EntityReference, Filter, Lookup, Order, Period, QueryPlan
from app.core.config import Settings
from app.db.runtime import DatabaseTimeout


@pytest.fixture(scope="module")
def engine(warehouse_path):
    return QueryExecutor(Settings(database_path=warehouse_path))


def oracle(engine, sql, parameters=()):
    with engine.warehouse.connection() as c:
        return c.execute(sql, parameters).fetchall()


def test_count_and_empty_count(engine):
    result = engine.execute(QueryPlan(kind="aggregate", metrics=("count", "delivered_count")))
    expected = oracle(engine, "SELECT count(*),count(*) FILTER(WHERE delivered_lots>0) FROM deals")[
        0
    ]
    assert result.status == "VERIFIED"
    assert result.rows == ({"count": expected[0], "delivered_count": expected[1]},)
    empty = engine.execute(
        QueryPlan(
            kind="aggregate",
            metrics=("count",),
            filters=(Filter(field="deal_id", op="eq", values=(1,)),),
        )
    )
    assert empty.status == "VERIFIED" and empty.rows == ({"count": 0},)


@pytest.mark.parametrize("mode", ["original", "uzs"])
def test_sum_min_max_arithmetic_average(engine, mode):
    plan = QueryPlan(
        kind="aggregate",
        metrics=("sum_amount", "avg_amount", "min_amount", "max_amount"),
        money_mode=mode,
        filters=(Filter(field="currency", op="eq", values=("Доллар США",)),),
    )
    result = engine.execute(plan)
    assert result.status == "VERIFIED", result.reason
    column = "amount" if mode == "original" else "amount_uzs"
    total, count, minimum, maximum = oracle(
        engine,
        (
            f"SELECT sum({column}),count(*),min({column}),max({column}) FROM "
            f"deals_enriched WHERE currency='Доллар США'"
        ),
    )[0]  # noqa: S608
    with localcontext() as context:
        context.prec = 60
        mean = (total / count).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    assert result.rows == (
        {"sum_amount": total, "avg_amount": mean, "min_amount": minimum, "max_amount": maximum},
    )
    assert "not a unit price" in result.aggregates["avg_amount"]


@pytest.mark.parametrize(
    "field", ["seller_inn", "buyer_inn", "product_name", "seller_broker_code", "buyer_broker_code"]
)
def test_rankings_independent_oracle(engine, field):
    result = engine.execute(
        QueryPlan(
            kind="aggregate",
            metrics=("sum_amount", "count"),
            money_mode="uzs",
            group_by=(field,),
            order_by=(Order(field="sum_amount"),),
            limit=7,
        )
    )
    assert result.status == "VERIFIED", result.reason
    expected = oracle(
        engine,
        (
            f"SELECT {field},sum(amount_uzs),count(*) FROM deals_enriched GROUP BY "
            f"{field} ORDER BY sum(amount_uzs) DESC,{field} ASC LIMIT 7"
        ),
    )  # noqa: S608
    assert result.rows == tuple({field: r[0], "sum_amount": r[1], "count": r[2]} for r in expected)
    assert result.evidence.output_limited


@pytest.mark.parametrize(
    ("entity", "table", "key"),
    [
        ("transaction", "deals_enriched", "deal_id"),
        ("contract", "contracts", "contract_id"),
        ("company", "participants", "inn"),
        ("broker", "brokers", "broker_code"),
    ],
)
def test_lookups_and_missing(engine, entity, table, key):
    identifier = oracle(engine, f"SELECT min({key}) FROM {table}")[0][0]  # noqa: S608
    result = engine.execute(
        QueryPlan(kind="lookup", lookup=Lookup(entity=entity, identifier=identifier))
    )
    assert result.status == "VERIFIED" and result.row_count == 1
    columns = tuple(result.rows[0])
    expected = oracle(
        engine, f"SELECT {','.join(columns)} FROM {table} WHERE {key}=?", (identifier,)
    )[0]  # noqa: S608
    assert tuple(result.rows[0].values()) == expected
    absent = (
        1
        if entity in ("transaction", "contract")
        else "000000000"
        if entity == "company"
        else "BK999"
    )
    assert (
        engine.execute(
            QueryPlan(kind="lookup", lookup=Lookup(entity=entity, identifier=absent))
        ).status
        == "NOT_FOUND"
    )


def test_date_inclusive_monthly_and_comparison(engine):
    filters = (
        Filter(field="deal_date", op="between", values=(date(2023, 1, 1), date(2023, 3, 31))),
    )
    result = engine.execute(
        QueryPlan(kind="aggregate", metrics=("count",), group_by=("month",), filters=filters)
    )
    expected = oracle(
        engine,
        (
            "SELECT date_trunc('month',deal_date)::DATE,count(*) FROM deals WHERE "
            "deal_date BETWEEN '2023-01-01' AND '2023-03-31' GROUP BY 1 ORDER BY 1"
        ),
    )
    assert result.rows == tuple({"month": r[0], "count": r[1]} for r in expected)
    plan = QueryPlan(
        kind="compare",
        metrics=("count", "sum_amount"),
        money_mode="uzs",
        periods=(
            Period(start=date(2022, 1, 3), end=date(2022, 12, 31)),
            Period(start=date(2023, 1, 1), end=date(2023, 12, 31)),
        ),
    )
    comparison = engine.execute(plan)
    assert comparison.status == "VERIFIED", comparison.reason
    for index, period in enumerate(plan.periods):
        count, total = oracle(
            engine,
            "SELECT count(*),sum(amount_uzs) FROM deals_enriched WHERE deal_date BETWEEN ? AND ?",
            (period.start, period.end),
        )[0]
        assert comparison.rows[index]["period"] == index
        assert comparison.rows[index]["count"] == count
        assert comparison.rows[index]["sum_amount"] == total


@pytest.mark.parametrize(("op", "sql"), [("lt", "<"), ("lte", "<="), ("gt", ">"), ("gte", ">=")])
def test_date_operators(engine, op, sql):
    result = engine.execute(
        QueryPlan(
            kind="aggregate",
            metrics=("count",),
            filters=(Filter(field="deal_date", op=op, values=(date(2023, 1, 2),)),),
        )
    )
    assert (
        result.rows[0]["count"]
        == oracle(
            engine, f"SELECT count(*) FROM deals WHERE deal_date {sql} ?", (date(2023, 1, 2),)
        )[0][0]
    )  # noqa: S608


@pytest.mark.parametrize("status", ["Аннулирован(Не оплачен)", "Исполнен(Частично)", "Исполнен"])
def test_status_and_partial_delivery(engine, status):
    result = engine.execute(
        QueryPlan(
            kind="aggregate",
            metrics=("count", "delivered_count", "sum_delivered_volume"),
            filters=(Filter(field="status", op="eq", values=(status,)),),
            group_by=("unit",),
        )
    )
    assert result.status == "VERIFIED", result.reason
    expected = oracle(
        engine,
        (
            "SELECT unit,count(*),count(*) FILTER(WHERE "
            "delivered_lots>0),sum(delivered_lots::HUGEINT*lot_size) FROM deals WHERE "
            "status=? GROUP BY unit ORDER BY unit"
        ),
        (status,),
    )
    assert result.rows == tuple(
        {"unit": r[0], "count": r[1], "delivered_count": r[2], "sum_delivered_volume": r[3]}
        for r in expected
    )
    if status == "Аннулирован(Не оплачен)":
        assert all(r["sum_delivered_volume"] is None for r in result.rows)


def test_multifilter_product_code_and_contract_fields(engine):
    code = oracle(engine, "SELECT min(tn_ved_code) FROM contracts")[0][0]
    filters = (
        Filter(field="tn_ved_code", op="eq", values=(code,)),
        Filter(field="contract_type", op="eq", values=("Внутренний",)),
        Filter(field="contract_form", op="in", values=("Спот", "Форвард")),
        Filter(field="deal_date", op="between", values=(date(2022, 1, 3), date(2026, 10, 30))),
    )
    result = engine.execute(QueryPlan(kind="aggregate", metrics=("count",), filters=filters))
    assert result.status == "VERIFIED"
    assert (
        result.rows[0]["count"]
        == oracle(
            engine,
            (
                "SELECT count(*) FROM deals d JOIN contracts c USING(contract_id) WHERE "
                "c.tn_ved_code=? AND d.contract_type='Внутренний' AND d.contract_form IN "
                "('Спот','Форвард') AND d.deal_date BETWEEN '2022-01-03' AND '2026-10-30'"
            ),
            (code,),
        )[0][0]
    )


def test_weighted_price_is_not_average_transaction_amount(engine):
    plan = QueryPlan(
        kind="aggregate",
        metrics=("weighted_unit_price", "avg_amount"),
        money_mode="original",
        filters=(
            Filter(field="currency", op="eq", values=("Узбекский сум",)),
            Filter(field="unit", op="eq", values=("тонна",)),
        ),
    )
    result = engine.execute(plan)
    assert result.status == "VERIFIED", result.reason
    amount, volume, count = oracle(
        engine,
        (
            "SELECT sum(amount),sum(d.quantity::HUGEINT*d.lot_size),count(*) FROM deals "
            "d JOIN contracts c USING(contract_id) WHERE c.currency='Узбекский сум' AND "
            "d.unit='тонна'"
        ),
    )[0]
    with localcontext() as context:
        context.prec = 60
        assert result.rows[0]["weighted_unit_price"] == (amount / volume).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )
        assert result.rows[0]["avg_amount"] == (amount / count).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )
    assert result.rows[0]["weighted_unit_price"] != result.rows[0]["avg_amount"]


def test_semantic_ambiguities_and_absent_contract_status(engine):
    cases = [
        (QueryPlan(kind="aggregate", metrics=("sum_amount",)), "CURRENCY_INTERPRETATION"),
        (
            QueryPlan(kind="aggregate", metrics=("sum_amount",), money_mode="original"),
            "MIXED_CURRENCIES",
        ),
        (QueryPlan(kind="aggregate", metrics=("sum_volume",)), "MIXED_UNITS"),
        (QueryPlan(kind="aggregate", metrics=("sum_lots",)), "LOT_MEANING"),
        (QueryPlan(kind="aggregate", metrics=("price_average",)), "PRICE_AVERAGE_MEANING"),
    ]
    for plan, reason in cases:
        result = engine.execute(plan)
        assert result.status == "AMBIGUOUS" and result.reason == reason
        assert not result.rows
    result = engine.execute(
        QueryPlan(
            kind="aggregate",
            metrics=("count",),
            filters=(Filter(field="contract_status", op="eq", values=("active",)),),
        )
    )
    assert result.status == "UNSUPPORTED" and result.reason == "CONTRACT_STATUS_ABSENT"


def test_injection_bound_as_literal_and_invalid_fields(engine):
    payload = "' OR 1=1; ATTACH '/etc/passwd' AS secret; --"
    plan = QueryPlan(
        kind="records",
        fields=("deal_id", "product_name"),
        filters=(Filter(field="product_name", op="eq", values=(payload,)),),
    )
    compiled = compile_plan(plan)
    assert payload not in compiled.sql and payload in compiled.parameters
    result = engine.execute(plan)
    assert result.status == "NOT_FOUND" and result.row_count == 0
    assert payload not in format_answer(result, "ru")
    assert engine.execute("SELECT * FROM deals").status == "UNSUPPORTED"
    with pytest.raises(ValidationError):
        QueryPlan(kind="aggregate", metrics=("count",), sql="DROP TABLE deals")
    with pytest.raises(ValidationError):
        Filter(field="amount);DROP TABLE deals;--", op="eq", values=(1,))
    bypass = QueryPlan(kind="aggregate", metrics=("count",)).model_copy(
        update={"order_by": ({"field": "count;DROP TABLE deals", "direction": "desc"},)}
    )
    assert engine.execute(bypass).status == "UNSUPPORTED"
    assert (
        engine.execute(QueryPlan(kind="aggregate", metrics=("count",))).rows[0]["count"] == 500000
    )


def test_overflow_null_operator_and_limits(engine, monkeypatch):
    for value in (Decimal("1e100"), 9223372036854775808):
        result = engine.execute(
            QueryPlan(kind="records", filters=(Filter(field="amount", op="eq", values=(value,)),))
        )
        assert result.status == "UNSUPPORTED"
    result = engine.execute(
        QueryPlan(
            kind="records",
            fields=("deal_id", "delivered_lots"),
            limit=3,
            filters=(Filter(field="delivered_lots", op="is_null"),),
        )
    )
    assert result.status == "VERIFIED" and result.row_count == 3 and result.evidence.output_limited
    assert all(r["delivered_lots"] is None for r in result.rows)
    with pytest.raises(ValidationError):
        QueryPlan(kind="records", limit=101)
    monkeypatch.setattr("app.agent.query_executor.MAX_GROUPS", 2)
    grouped = engine.execute(
        QueryPlan(kind="aggregate", metrics=("count",), group_by=("seller_inn",))
    )
    assert grouped.status == "UNSUPPORTED" and grouped.reason == "GROUP_LIMIT"


def test_entities_source_dictionary_and_three_scripts(engine):
    candidates = engine.resolver.values["company"]
    candidate = candidates[0]
    assert (
        engine.resolver.resolve("company", candidate.value).candidates[0].value == candidate.value
    )
    # Same recorded name is never assumed to identify one company.
    resolution = engine.resolver.resolve("company", candidate.label)
    assert resolution.status in ("VERIFIED", "AMBIGUOUS")
    assert engine.resolver.resolve("product", "МУКА").status == "AMBIGUOUS"
    assert engine.resolver.resolve("product", "un").status == "AMBIGUOUS"
    for text in ("qisman bajarilgan", "қисман бажарилган", "Исполнен(Частично)"):
        resolution = engine.resolver.resolve("status", text)
        assert resolution.status == "VERIFIED"
        assert resolution.candidates[0].value == "Исполнен(Частично)"
    for text in ("Toshkent shahri", "Тошкент шаҳри", "г. Ташкент"):
        resolution = engine.resolver.resolve("region", text)
        assert resolution.status == "VERIFIED", text
        assert resolution.candidates[0].value == "Toshkent shahri"
    plan = QueryPlan(
        kind="aggregate",
        metrics=("count",),
        entities=(EntityReference(field="seller_inn", text=candidate.value),),
    )
    result = engine.execute(plan)
    assert (
        result.rows[0]["count"]
        == oracle(engine, "SELECT count(*) FROM deals WHERE seller_inn=?", (candidate.value,))[0][0]
    )


def test_stability_evidence_formatters_and_no_audit_serialization(engine):
    plan = QueryPlan(
        kind="aggregate",
        metrics=("count",),
        group_by=("seller_inn",),
        order_by=(Order(field="count"),),
        limit=3,
    )
    results = [engine.execute(plan) for _ in range(3)]
    assert len({r.model_dump_json() for r in results}) == 1
    result = results[0]
    assert (
        result.internal_sql
        and result.evidence
        and result.evidence.dataset_version == result.dataset_version
    )
    assert "internal_sql" not in json.loads(result.model_dump_json())
    assert result.evidence.matched_transactions == 500000
    for language, label in [
        ("uz-Latn", "Tasdiqlangan"),
        ("uz-Cyrl", "Тасдиқланган"),
        ("ru", "Подтверждённый"),
    ]:
        text = format_answer(result, language)
        assert label in text
        assert str(result.rows[0]["count"]) in text
        assert "SELECT" not in text
    assert str(result.rows[0]["count"]) not in format_answer(result, "en")
    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent = list(pool.map(engine.execute, [plan] * 4))
    assert all(r.model_dump_json() == result.model_dump_json() for r in concurrent)


def test_error_and_not_found_are_distinct(engine, monkeypatch):
    def timeout(*args, **kwargs):
        raise DatabaseTimeout("private internal error")

    monkeypatch.setattr(engine.warehouse, "connection", timeout)
    result = engine.execute(QueryPlan(kind="aggregate", metrics=("count",)))
    assert result.status == "ERROR" and result.reason == "TIME_BUDGET"
    assert "private" not in result.model_dump_json()


def test_product_exact_lookup_and_currency_separation(engine):
    name = oracle(engine, "SELECT min(product_name) FROM deals_enriched")[0][0]
    result = engine.execute(
        QueryPlan(
            kind="records",
            fields=("deal_id", "product_name"),
            filters=(Filter(field="product_name", op="eq", values=(name,)),),
            limit=3,
        )
    )
    assert result.status == "VERIFIED"
    expected = oracle(
        engine,
        (
            "SELECT deal_id,product_name FROM deals_enriched "
            "WHERE product_name=? ORDER BY deal_id LIMIT 3"
        ),
        (name,),
    )
    assert result.rows == tuple({"deal_id": r[0], "product_name": r[1]} for r in expected)
    separated = engine.execute(
        QueryPlan(
            kind="aggregate", metrics=("sum_amount",), money_mode="original", group_by=("currency",)
        )
    )
    expected = oracle(
        engine,
        ("SELECT currency,sum(amount) FROM deals_enriched GROUP BY currency ORDER BY currency"),
    )
    assert separated.rows == tuple({"currency": r[0], "sum_amount": r[1]} for r in expected)


def test_min_max_unit_price_and_null_evidence(engine):
    filters = (
        Filter(field="currency", op="eq", values=("Доллар США",)),
        Filter(field="unit", op="eq", values=("тонна",)),
    )
    result = engine.execute(
        QueryPlan(
            kind="aggregate",
            metrics=("min_unit_price", "max_unit_price"),
            money_mode="uzs",
            filters=filters,
        )
    )
    assert result.status == "VERIFIED", result.reason
    pairs = oracle(
        engine,
        "SELECT amount_uzs,volume FROM deals_enriched WHERE currency='Доллар США' AND unit='тонна'",
    )
    with localcontext() as context:
        context.prec = 60
        prices = [(a / v).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP) for a, v in pairs]
    assert result.rows == ({"min_unit_price": min(prices), "max_unit_price": max(prices)},)


def test_original_money_and_physical_filters_require_consistent_units(engine):
    for field in ("amount", "volume"):
        result = engine.execute(
            QueryPlan(
                kind="aggregate",
                metrics=("count",),
                filters=(Filter(field=field, op="gt", values=(1,)),),
            )
        )
        assert result.status == "AMBIGUOUS"


def test_response_size_plan_size_and_error_classification(engine, monkeypatch):
    monkeypatch.setattr("app.agent.query_executor.MAX_RESPONSE_BYTES", 10)
    assert (
        engine.execute(
            QueryPlan(kind="lookup", lookup=Lookup(entity="transaction", identifier=100001))
        ).reason
        == "RESPONSE_SIZE"
    )
    values = tuple("x" * 256 for _ in range(50))
    large = QueryPlan(
        kind="records",
        filters=tuple(Filter(field="product_name", op="in", values=values) for _ in range(3)),
    )
    result = engine.execute(large)
    assert result.status == "UNSUPPORTED" and result.reason == "PLAN_SIZE"

    def broken(*args, **kwargs):
        raise ValueError("private-internal-value")

    monkeypatch.setattr(engine.warehouse, "connection", broken)
    result = engine.execute(QueryPlan(kind="aggregate", metrics=("count",)))
    assert result.status == "ERROR" and result.reason == "INTERNAL_FAILURE"
    assert "private-internal-value" not in result.model_dump_json()


def test_comparison_missing_overlap_and_no_truncated_comparison(engine):
    overlap = QueryPlan(
        kind="compare",
        metrics=("count",),
        periods=(
            Period(start=date(2022, 1, 1), end=date(2022, 2, 1)),
            Period(start=date(2022, 2, 1), end=date(2022, 3, 1)),
        ),
    )
    assert engine.execute(overlap).status == "AMBIGUOUS"
    missing = QueryPlan(
        kind="compare",
        metrics=("sum_amount",),
        money_mode="uzs",
        periods=(
            Period(start=date(2021, 1, 1), end=date(2021, 12, 31)),
            Period(start=date(2022, 1, 1), end=date(2022, 12, 31)),
        ),
    )
    assert engine.execute(missing).status == "NOT_FOUND"
    valid = missing.model_copy(
        update={
            "periods": (
                Period(start=date(2022, 1, 1), end=date(2022, 12, 31)),
                Period(start=date(2023, 1, 1), end=date(2023, 12, 31)),
            ),
            "limit": 1,
        }
    )
    assert engine.execute(valid).reason == "COMPARISON_OUTPUT_LIMIT"


def test_entity_resolver_never_silently_chooses_fuzzy_match(engine):
    resolution = engine.resolver.resolve("product", "бензн автомобилный")
    assert resolution.status == "AMBIGUOUS" and resolution.reason == "CONFIRM_FUZZY"
    unknown = engine.resolver.resolve("company", "000000000")
    assert unknown.status == "NOT_FOUND"
    entity = EntityReference(field="product_name", text="un")
    assert (
        engine.execute(QueryPlan(kind="aggregate", metrics=("count",), entities=(entity,))).status
        == "AMBIGUOUS"
    )


def test_artifact_tampering_is_not_reported_as_verified(warehouse_path, tmp_path):
    import os
    import shutil

    copy = tmp_path / "uzex.duckdb"
    shutil.copyfile(warehouse_path, copy)
    for name in ("schema_catalog.json", "build_report.json"):
        shutil.copyfile(warehouse_path.with_name(name), tmp_path / name)
    local = QueryExecutor(Settings(database_path=copy))
    stat = copy.stat()
    os.utime(copy, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
    result = local.execute(QueryPlan(kind="aggregate", metrics=("count",)))
    assert result.status == "ERROR" and result.reason == "ARTIFACT_CHANGED"
