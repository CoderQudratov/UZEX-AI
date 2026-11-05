"""Semantic rejection happens before compilation. No invented source columns."""

import re
from datetime import date
from decimal import Decimal

from app.agent.query_models import QueryPlan
from app.db.schema import STATUSES, UNITS

MAX_GROUPS = 20000
MAX_RESPONSE_BYTES = 131072
ID_FIELDS = {"deal_id", "contract_id"}
DATE_FIELDS = {"deal_date", "payment_date", "delivery_date", "registered_date", "valid_until"}
NUMBER_FIELDS = {
    "quantity",
    "lot_size",
    "amount",
    "amount_uzs",
    "starting_price",
    "delivered_lots",
    "volume",
    "delivered_volume",
    "unit_price_rounded_8",
    "base_price",
}
MONEY_METRICS = {
    "sum_amount",
    "avg_amount",
    "min_amount",
    "max_amount",
    "weighted_unit_price",
    "min_unit_price",
    "max_unit_price",
}
PHYSICAL_METRICS = {
    "sum_volume",
    "sum_delivered_volume",
    "weighted_unit_price",
    "min_unit_price",
    "max_unit_price",
}
LOT_METRICS = {"sum_lots", "sum_delivered_lots"}


class PlanRejected(ValueError):
    def __init__(self, status: str, reason: str):
        self.status, self.reason = status, reason
        super().__init__(reason)


def reject(reason: str, status="UNSUPPORTED"):
    raise PlanRejected(status, reason)


def validate_plan(plan: QueryPlan) -> QueryPlan:
    # Revalidate even model_construct/model_copy inputs; callers cannot bypass invariants.
    plan = QueryPlan.model_validate(plan.model_dump(mode="python", warnings="error"))
    typed_filters = []
    for f in plan.filters:
        if f.field in DATE_FIELDS:
            values = []
            for value in f.values:
                if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    try:
                        value = date.fromisoformat(value)
                    except ValueError:
                        reject("DATE_TYPE")
                values.append(value)
            f = f.model_copy(update={"values": tuple(values)})
        typed_filters.append(f)
    plan = plan.model_copy(update={"filters": tuple(typed_filters)})
    if plan.kind == "lookup":
        if plan.lookup is None or any(
            (
                plan.filters,
                plan.entities,
                plan.metrics,
                plan.group_by,
                plan.fields,
                plan.order_by,
                plan.periods,
                plan.money_mode,
            )
        ):
            reject("LOOKUP_SHAPE")
        identifier = plan.lookup.identifier
        if plan.lookup.entity in ("transaction", "contract"):
            if type(identifier) is not int or not 1 <= identifier <= 9223372036854775807:
                reject("IDENTIFIER_TYPE")
        elif plan.lookup.entity == "company":
            if not isinstance(identifier, str) or not re.fullmatch("[0-9]{9}", identifier):
                reject("IDENTIFIER_TYPE")
        elif not isinstance(identifier, str) or not re.fullmatch("BK[0-9]{3}", identifier):
            reject("IDENTIFIER_TYPE")
        return plan
    if plan.lookup is not None:
        reject("LOOKUP_SHAPE")
    if plan.kind == "records":
        if plan.metrics or plan.group_by or plan.periods or plan.money_mode:
            reject("RECORD_SHAPE")
    elif not plan.metrics or plan.fields:
        reject("AGGREGATE_SHAPE")
    if len(set(plan.metrics)) != len(plan.metrics) or len(set(plan.group_by)) != len(plan.group_by):
        reject("DUPLICATE_SELECTION")
    if len(set(plan.fields)) != len(plan.fields):
        reject("DUPLICATE_SELECTION")
    if "price_average" in plan.metrics:
        reject("PRICE_AVERAGE_MEANING", "AMBIGUOUS")
    if set(plan.metrics) & MONEY_METRICS and plan.money_mode is None:
        reject("CURRENCY_INTERPRETATION", "AMBIGUOUS")
    if plan.kind == "compare":
        if len(plan.periods) != 2 or any(p.start > p.end for p in plan.periods):
            reject("COMPARISON_PERIODS")
        if not (
            plan.periods[0].end < plan.periods[1].start
            or plan.periods[1].end < plan.periods[0].start
        ):
            reject("OVERLAPPING_PERIODS", "AMBIGUOUS")
    elif plan.periods:
        reject("COMPARISON_PERIODS")
    if "contract_status" in plan.fields or any(e.field == "contract_status" for e in plan.entities):
        reject("CONTRACT_STATUS_ABSENT")
    for f in plan.filters:
        if f.field == "contract_status":
            reject("CONTRACT_STATUS_ABSENT")
        expected = 0 if f.op in ("is_null", "not_null") else 2 if f.op == "between" else None
        if expected is not None and len(f.values) != expected:
            reject("FILTER_ARITY")
        if (
            f.op == "in"
            and not f.values
            or f.op not in ("in", "between", "is_null", "not_null")
            and len(f.values) != 1
        ):
            reject("FILTER_ARITY")
        for value in f.values:
            if value is None:
                reject("NULL_OPERATOR_REQUIRED")
            if f.field in ID_FIELDS:
                if type(value) is not int or not 1 <= value <= 9223372036854775807:
                    reject("IDENTIFIER_TYPE")
            elif f.field in DATE_FIELDS:
                if type(value) is not date:
                    reject("DATE_TYPE")
            elif f.field in NUMBER_FIELDS:
                if type(value) not in (int, Decimal) or not Decimal(value).is_finite():
                    reject("NUMBER_TYPE")
                number = Decimal(value)
                if abs(number) >= Decimal("1e18") or number.as_tuple().exponent < -8:
                    reject("NUMERIC_BOUND")
            else:
                if not isinstance(value, str) or not 1 <= len(value) <= 256:
                    reject("TEXT_TYPE")
                if f.field in ("seller_inn", "buyer_inn") and not re.fullmatch("[0-9]{9}", value):
                    reject("IDENTIFIER_TYPE")
                if f.field in ("seller_broker_code", "buyer_broker_code") and not re.fullmatch(
                    "BK[0-9]{3}", value
                ):
                    reject("IDENTIFIER_TYPE")
                if f.field == "tn_ved_code" and not re.fullmatch("[0-9]{2,12}", value):
                    reject("IDENTIFIER_TYPE")
                if f.field == "currency" and value not in ("Узбекский сум", "Доллар США"):
                    reject("CURRENCY_VALUE")
                if f.field == "unit" and value not in UNITS:
                    reject("UNIT_VALUE")
                if f.field == "status" and value not in STATUSES:
                    reject("STATUS_VALUE")
        if f.op == "between" and f.values[0] > f.values[1]:
            reject("REVERSED_RANGE")
        if (
            f.op in ("gt", "gte", "lt", "lte", "between")
            and f.field not in DATE_FIELDS | NUMBER_FIELDS | ID_FIELDS
        ):
            reject("OPERATOR_TYPE")
    for order in plan.order_by:
        allowed = (
            set(plan.fields)
            if plan.kind == "records" and plan.fields
            else set(plan.group_by) | set(plan.metrics)
        )
        if plan.kind == "records" and not plan.fields:
            allowed = {"deal_id", "deal_date", "amount"}
        if order.field not in allowed:
            reject("ORDER_FIELD")
    return plan
