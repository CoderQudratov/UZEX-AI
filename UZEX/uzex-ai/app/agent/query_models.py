"""Closed structured query language. No SQL, paths, expressions or aliases from callers."""

from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["uz-Latn", "uz-Cyrl", "ru"]
Status = Literal["VERIFIED", "NOT_FOUND", "AMBIGUOUS", "UNSUPPORTED", "ERROR"]
FieldName = Literal[
    "deal_id",
    "contract_id",
    "deal_date",
    "payment_date",
    "delivery_date",
    "deal_time",
    "seller_inn",
    "buyer_inn",
    "seller_name",
    "buyer_name",
    "seller_broker_code",
    "buyer_broker_code",
    "seller_broker_name",
    "buyer_broker_name",
    "product_name",
    "product_description",
    "tn_ved_code",
    "product_group",
    "product_category",
    "industry",
    "brand",
    "grade",
    "size",
    "product_type",
    "product_class",
    "region",
    "contract_region",
    "status",
    "contract_status",
    "contract_type",
    "contract_form",
    "auction_type",
    "currency",
    "unit",
    "quantity",
    "lot_size",
    "amount",
    "amount_uzs",
    "starting_price",
    "delivered_lots",
    "volume",
    "delivered_volume",
    "unit_price_rounded_8",
    "registered_date",
    "valid_until",
    "warehouse_address",
    "base_price",
]
Dimension = Literal[
    "seller_inn",
    "buyer_inn",
    "seller_name",
    "buyer_name",
    "seller_broker_code",
    "buyer_broker_code",
    "seller_broker_name",
    "buyer_broker_name",
    "product_name",
    "tn_ved_code",
    "product_group",
    "product_category",
    "region",
    "contract_region",
    "status",
    "contract_type",
    "contract_form",
    "auction_type",
    "currency",
    "unit",
    "month",
]
Metric = Literal[
    "count",
    "delivered_count",
    "sum_amount",
    "avg_amount",
    "min_amount",
    "max_amount",
    "sum_volume",
    "sum_delivered_volume",
    "sum_lots",
    "sum_delivered_lots",
    "weighted_unit_price",
    "min_unit_price",
    "max_unit_price",
    "price_average",
]
Scalar = str | int | Decimal | date | time | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Filter(StrictModel):
    field: FieldName
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "is_null", "not_null"]
    values: tuple[Scalar, ...] = Field(default=(), max_length=50)


class EntityReference(StrictModel):
    field: Literal[
        "seller_inn",
        "buyer_inn",
        "seller_broker_code",
        "buyer_broker_code",
        "product_name",
        "tn_ved_code",
        "region",
        "status",
        "contract_status",
    ]
    text: str = Field(min_length=1, max_length=256)


class Lookup(StrictModel):
    entity: Literal["transaction", "contract", "company", "broker"]
    identifier: str | int


class Period(StrictModel):
    start: date
    end: date


class Order(StrictModel):
    field: str = Field(min_length=1, max_length=40)
    direction: Literal["asc", "desc"] = "desc"


class QueryPlan(StrictModel):
    kind: Literal["lookup", "records", "aggregate", "compare"]
    language: Language = "uz-Latn"
    lookup: Lookup | None = None
    filters: tuple[Filter, ...] = Field(default=(), max_length=16)
    entities: tuple[EntityReference, ...] = Field(default=(), max_length=4)
    metrics: tuple[Metric, ...] = Field(default=(), max_length=8)
    group_by: tuple[Dimension, ...] = Field(default=(), max_length=3)
    fields: tuple[FieldName, ...] = Field(default=(), max_length=30)
    order_by: tuple[Order, ...] = Field(default=(), max_length=2)
    money_mode: Literal["original", "uzs"] | None = None
    periods: tuple[Period, ...] = Field(default=(), max_length=2)
    limit: int = Field(default=20, ge=1, le=100)


class Candidate(StrictModel):
    value: str
    label: str


class Resolution(StrictModel):
    status: Status
    candidates: tuple[Candidate, ...] = ()
    reason: str = ""


class AuditSQL(StrictModel):
    # Bound SQL + parameters, RAM only. Never log or persist this structure.
    sql: str
    parameters: tuple[Scalar, ...] = ()


class Evidence(StrictModel):
    source: str = "uzex_spot_data.zip"
    dataset_version: str
    snapshot: date
    tables: tuple[str, ...]
    matched_transactions: int | None = None
    output_limited: bool = False
    grouping_cardinality: int = 0
    null_delivery_transactions: int | None = None
    note_codes: tuple[str, ...] = ()


class VerifiedResult(StrictModel):
    status: Status
    rows: tuple[dict[str, Scalar], ...] = ()
    row_count: int = 0
    aggregates: dict[str, str] = Field(default_factory=dict)
    original_currency: tuple[str, ...] = ()
    measurement_units: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    evidence: Evidence | None = None
    dataset_version: str
    internal_sql: tuple[AuditSQL, ...] = Field(default=(), repr=False, exclude=True)
    reason: str = ""
    candidates: tuple[Candidate, ...] = ()
