"""Compact provider JSON grammar; full strict Pydantic/semantic validation is mandatory.

The complete local schema contains Python Decimal regex and date/time scalar unions that
were rejected by the live provider as a full schema. The exact unsupported
constraint is not inferred. A compact grammar was accepted by the live provider.
The wire grammar constrains
shape; local enums, types, bounds and business rules remain authoritative and stricter.
"""

from copy import deepcopy
from typing import get_args

from app.agent.query_models import Dimension, EntityReference, Metric
from app.agent.semantic_models import Reason


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def array(item):
    return {"type": "array", "items": item}


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


TEXT = {"type": "string"}
SCALAR = {"type": ["string", "number", "null"]}
FILTER = obj(
    {
        "field": TEXT,
        "op": {
            "type": "string",
            "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "is_null", "not_null"],
        },
        "values": array(SCALAR),
    },
    ("field", "op", "values"),
)
LOOKUP = obj(
    {
        "entity": {"type": "string", "enum": ["transaction", "contract", "company", "broker"]},
        "identifier": {"type": ["string", "integer"]},
    },
    ("entity", "identifier"),
)
PLAN = obj(
    {
        "kind": {"type": "string", "enum": ["lookup", "records", "aggregate", "compare"]},
        "language": {"type": "string", "enum": ["uz-Latn", "uz-Cyrl", "ru"]},
        "lookup": nullable(LOOKUP),
        "filters": array(FILTER),
        "entities": array(
            obj(
                {
                    "field": {
                        "type": "string",
                        "enum": list(get_args(EntityReference.model_fields["field"].annotation)),
                    },
                    "text": TEXT,
                },
                ("field", "text"),
            )
        ),
        "metrics": array({"type": "string", "enum": list(get_args(Metric))}),
        "group_by": array({"type": "string", "enum": list(get_args(Dimension))}),
        "fields": array(TEXT),
        "order_by": array(
            obj(
                {"field": TEXT, "direction": {"type": "string", "enum": ["asc", "desc"]}},
                ("field", "direction"),
            )
        ),
        "money_mode": {"type": ["string", "null"], "enum": ["original", "uzs", None]},
        "periods": array(obj({"start": TEXT, "end": TEXT}, ("start", "end"))),
        "limit": {"type": "integer"},
    },
    ("kind", "language"),
)
# Closed variants also enforce cross-field shape at generation time. A single-period
# year filter cannot be put into comparison periods on an aggregate plan.
COMMON = {
    k: PLAN["properties"][k] for k in ("language", "filters", "entities", "order_by", "limit")
}
LOOKUP_PLAN = obj(
    {
        "kind": {"type": "string", "enum": ["lookup"]},
        "language": PLAN["properties"]["language"],
        "lookup": LOOKUP,
    },
    ("kind", "language", "lookup"),
)
RECORD_PLAN = obj(
    {
        "kind": {"type": "string", "enum": ["records"]},
        **COMMON,
        "fields": PLAN["properties"]["fields"],
    },
    ("kind", "language"),
)
AGG_PLAN = obj(
    {
        "kind": {"type": "string", "enum": ["aggregate"]},
        **COMMON,
        **{k: PLAN["properties"][k] for k in ("metrics", "group_by", "money_mode")},
    },
    (
        "kind",
        "language",
        "metrics",
        "filters",
        "group_by",
        "order_by",
        "entities",
        "money_mode",
        "limit",
    ),
)
COMPARE_PLAN = obj(
    {
        "kind": {"type": "string", "enum": ["compare"]},
        **COMMON,
        **{k: PLAN["properties"][k] for k in ("metrics", "group_by", "money_mode", "periods")},
    },
    ("kind", "language", "metrics", "periods"),
)
WIRE_SCHEMA = obj(
    {
        "status": {"type": "string", "enum": ["PLAN", "AMBIGUOUS", "UNSUPPORTED"]},
        "language": {"type": "string", "enum": ["uz_latn", "uz_cyrl", "ru", "unsupported"]},
        "reason": {"type": "string", "enum": list(get_args(Reason))},
        "plan": {"anyOf": [LOOKUP_PLAN, RECORD_PLAN, AGG_PLAN, COMPARE_PLAN, {"type": "null"}]},
    },
    ("status", "language", "reason", "plan"),
)


def response_schema():
    return deepcopy(WIRE_SCHEMA)
