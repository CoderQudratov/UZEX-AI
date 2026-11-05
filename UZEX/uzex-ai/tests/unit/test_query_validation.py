import warnings
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agent.query_compiler import compile_plan
from app.agent.query_executor import ratio
from app.agent.query_models import Filter, Lookup, Order, QueryPlan
from app.agent.query_validator import PlanRejected, validate_plan


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "aggregate", "metrics": ("DROP TABLE deals",)},
        {"kind": "records", "limit": 0},
        {"kind": "records", "limit": 101},
        {"kind": "records", "language": "en"},
        {"kind": "records", "sql": "SELECT 1"},
        {"kind": "records", "filters": [{"field": "deal_id", "op": "eq", "values": [1]}]},
    ],
)
def test_strict_schema_rejects_invalid_native_payloads(payload):
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


@pytest.mark.parametrize(
    "filter",
    [
        Filter(field="deal_date", op="between", values=(date(2024, 1, 1),)),
        Filter(field="deal_date", op="between", values=(date(2024, 1, 2), date(2024, 1, 1))),
        Filter(field="amount", op="eq", values=(None,)),
        Filter(field="product_name", op="gt", values=("abc",)),
        Filter(field="seller_inn", op="eq", values=("123",)),
        Filter(field="tn_ved_code", op="eq", values=("DROP",)),
    ],
)
def test_filter_semantics_reject(filter):
    with pytest.raises(PlanRejected):
        validate_plan(QueryPlan(kind="records", filters=(filter,)))


def test_json_date_ranges_and_typed_parameters():
    plan = QueryPlan.model_validate_json(
        """{"kind":"aggregate","metrics":["count"],"filters":[{"field":"deal_date","op":"between","values":["2023-01-01","2023-12-31"]}]}"""
    )
    compiled = compile_plan(plan)
    assert compiled.parameters == (date(2023, 1, 1), date(2023, 12, 31))
    assert "2023-01-01" not in compiled.sql


def test_nonnumeric_and_nonfinite_values_rejected():
    with pytest.raises(ValidationError):
        Filter(field="amount", op="eq", values=(Decimal("NaN"),))
    with pytest.raises(ValidationError):
        Filter(field="amount", op="eq", values=(1.5,))
    with pytest.raises(ValidationError):
        Filter(field="amount", op="eq", values=(float("inf"),))


def test_decimal_half_up_ratio():
    assert ratio(Decimal("1"), Decimal("3")) == Decimal("0.33333333")
    assert ratio(Decimal("0.000000005"), 1) == Decimal("0.00000001")
    assert ratio(None, 2) is None
    assert ratio(1, 0) is None


def test_bypass_models_fail_without_payload_warnings():
    plan = QueryPlan(kind="records").model_copy(
        update={"order_by": ({"field": "private-payload", "direction": "desc"},)}
    )
    with warnings.catch_warnings(record=True) as captured:
        with pytest.raises(ValueError):
            validate_plan(plan)
    assert not captured


def test_compiler_rejects_unselected_sort():
    with pytest.raises(PlanRejected):
        compile_plan(
            QueryPlan(kind="aggregate", metrics=("count",), order_by=(Order(field="amount"),))
        )
    with pytest.raises(PlanRejected):
        compile_plan(
            QueryPlan(kind="lookup", lookup=Lookup(entity="transaction", identifier="100001"))
        )


def test_phonemic_company_name_changes_never_auto_authorize():
    from app.agent.entity_resolver import EntityResolver, normalize

    resolver = EntityResolver.__new__(EntityResolver)
    resolver.index = {"company": {normalize("Gul MChJ"): {("001234567", "Gul MChJ")}}}
    assert resolver.resolve("company", "Gul MChJ").status == "VERIFIED"
    assert resolver.resolve("company", "G‘ul MChJ").status == "AMBIGUOUS"
    resolver.index = {"company": {normalize("G‘ul MChJ"): {("001234567", "G‘ul MChJ")}}}
    assert resolver.resolve("company", "G'ul MChJ").status == "VERIFIED"
    assert resolver.resolve("company", "Ғул МЧЖ").status == "VERIFIED"
