"""SQL compiler: every SQL fragment is a private constant or validated enum mapping."""

# ruff: noqa: S608
# Identifiers come only from maps below after full semantic validation. Values are bound.
from dataclasses import dataclass

from app.agent.query_models import QueryPlan
from app.agent.query_validator import validate_plan
from app.db.schema import SCHEMA

VIEW_FIELDS = {c.name: c.name for c in SCHEMA["deals"]}
VIEW_FIELDS.update(
    {
        name: name
        for name in (
            "currency",
            "product_name",
            "brand",
            "size",
            "grade",
            "product_type",
            "product_class",
            "tn_ved_code",
            "product_group",
            "product_category",
            "industry",
            "contract_region",
            "warehouse_address",
            "base_price",
            "registered_date",
            "valid_until",
            "seller_name",
            "buyer_name",
            "seller_broker_name",
            "buyer_broker_name",
            "volume",
            "delivered_volume",
            "amount_uzs",
            "unit_price_rounded_8",
        )
    }
)
DIMENSIONS = dict(VIEW_FIELDS, month="date_trunc('month',deal_date)::DATE")
DEFAULT_FIELDS = tuple(c.name for c in SCHEMA["deals"]) + ("currency", "seller_name", "buyer_name")
LOOKUPS = {
    "transaction": ("deals_enriched", "deal_id", DEFAULT_FIELDS),
    "contract": ("contracts", "contract_id", tuple(c.name for c in SCHEMA["contracts"])),
    "company": ("participants", "inn", tuple(c.name for c in SCHEMA["participants"])),
    "broker": ("brokers", "broker_code", tuple(c.name for c in SCHEMA["brokers"])),
}
METRIC_MEANINGS = {
    "count": "Number of matched transactions, including all statuses unless filtered",
    "delivered_count": "Transactions with recorded delivered_lots > 0; NULL is unknown",
    "sum_amount": "Sum in explicitly selected currency basis",
    "avg_amount": "Arithmetic mean transaction amount: sum(amount)/count, not a unit price",
    "min_amount": "Minimum transaction amount in selected currency basis",
    "max_amount": "Maximum transaction amount in selected currency basis",
    "sum_volume": "Sum quantity * lot_size, within one recorded measurement unit",
    "sum_delivered_volume": "Sum known delivered_lots * lot_size; missing evidence remains NULL",
    "sum_lots": "Sum lots only when all records share the same unit and lot_size",
    "sum_delivered_lots": "Sum known delivered lots with common unit and lot_size",
    "weighted_unit_price": "Sum amount / sum physical volume; ROUND_HALF_UP to 8 decimals",
    "min_unit_price": "Minimum per-transaction rounded-8 unit price, same currency and unit",
    "max_unit_price": "Maximum per-transaction rounded-8 unit price, same currency and unit",
}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: tuple
    columns: tuple[str, ...]
    probe_sql: str | None = None
    probe_parameters: tuple = ()
    group_sql: str | None = None
    group_parameters: tuple = ()
    tables: tuple = ("deals", "contracts", "participants", "brokers", "usd_rates")


def where_clause(plan):
    parts, parameters = [], []
    operators = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for f in plan.filters:
        field = VIEW_FIELDS[f.field]
        if f.op in operators:
            parts.append(f"{field} {operators[f.op]} ?")
        elif f.op == "between":
            parts.append(f"{field} BETWEEN ? AND ?")
        elif f.op == "in":
            parts.append(f"{field} IN ({','.join('?' for _ in f.values)})")
        else:
            parts.append(f"{field} IS {'NOT ' if f.op == 'not_null' else ''}NULL")
        parameters.extend(f.values)
    if plan.periods:
        parts.append("(" + " OR ".join("deal_date BETWEEN ? AND ?" for _ in plan.periods) + ")")
        for period in plan.periods:
            parameters.extend((period.start, period.end))
    return (" WHERE " + " AND ".join(parts) if parts else ""), tuple(parameters)


def source_for_plan(plan):
    required = set(plan.fields or DEFAULT_FIELDS) if plan.kind == "records" else set(plan.group_by)
    required.update(f.field for f in plan.filters)
    if required & {
        "seller_name",
        "buyer_name",
        "seller_broker_name",
        "buyer_broker_name",
        "unit_price_rounded_8",
    } or set(plan.metrics) & {"min_unit_price", "max_unit_price"}:
        return "deals_enriched", ("deals", "contracts", "participants", "brokers", "usd_rates")
    contract_fields = (
        "currency",
        "product_name",
        "brand",
        "size",
        "grade",
        "product_type",
        "product_class",
        "tn_ved_code",
        "product_group",
        "product_category",
        "industry",
        "warehouse_address",
        "base_price",
        "registered_date",
        "valid_until",
    )
    selection = ["d.*"] + ["c." + f for f in contract_fields]
    selection += [
        "c.region AS contract_region",
        "quantity::HUGEINT* d.lot_size::HUGEINT AS volume",
        "delivered_lots::HUGEINT*d.lot_size::HUGEINT AS delivered_volume",
    ]
    joins = "deals d JOIN contracts c USING(contract_id)"
    tables = ("deals", "contracts")
    if plan.money_mode == "uzs" or "amount_uzs" in required:
        selection.append(
            "CASE WHEN c.currency='Доллар США' THEN amount*r.usd_uzs_rate "
            "ELSE CAST(amount AS DECIMAL(30,4)) END AS amount_uzs"
        )
        joins += " JOIN usd_rates r ON d.deal_date=r.rate_date"
        tables += ("usd_rates",)
    return "(SELECT " + ",".join(selection) + " FROM " + joins + ") scoped_deals", tables


def compile_plan(input_plan: QueryPlan) -> CompiledQuery:
    plan = validate_plan(input_plan)
    if plan.entities:
        raise ValueError("Resolve entities before compilation")
    if plan.kind == "lookup":
        table, key, columns = LOOKUPS[plan.lookup.entity]
        return CompiledQuery(
            f"SELECT {','.join(columns)} FROM {table} WHERE {key}=? LIMIT 1",
            (plan.lookup.identifier,),
            columns,
        )
    where, params = where_clause(plan)
    source, tables = source_for_plan(plan)
    lot_probe = (
        "count(DISTINCT lot_size)"
        if set(plan.metrics) & {"sum_lots", "sum_delivered_lots"}
        else "0"
    )
    probe = (
        "SELECT count(*),list(DISTINCT currency ORDER BY currency),"
        "list(DISTINCT unit ORDER BY unit)," + lot_probe + ","
        "count(*) FILTER(WHERE delivered_lots IS NULL) FROM " + source + where
    )
    if plan.kind == "records":
        columns = plan.fields or DEFAULT_FIELDS
        order = [f"{VIEW_FIELDS[o.field]} {o.direction.upper()}" for o in plan.order_by]
        order.append("deal_id ASC")
        return CompiledQuery(
            f"SELECT {','.join(VIEW_FIELDS[f] for f in columns)} "
            f"FROM {source}{where} ORDER BY {','.join(order)} LIMIT ?",
            params + (plan.limit + 1,),
            tuple(columns),
            probe,
            params,
            tables=tables,
        )
    groups = list(plan.group_by)
    expressions = [f"{DIMENSIONS[g]} AS {g}" for g in groups]
    grouping = [DIMENSIONS[g] for g in groups]
    if plan.kind == "compare":
        # The public label is generated from validated period dates, not arbitrary SQL text.
        expressions.insert(0, "CASE WHEN deal_date BETWEEN ? AND ? THEN 0 ELSE 1 END AS period")
        groups.insert(0, "period")
        grouping.insert(0, "period")
    amount = "amount_uzs" if plan.money_mode == "uzs" else "amount"
    price = (
        "unit_price_rounded_8"
        if plan.money_mode != "uzs"
        else "CAST(((CAST(amount_uzs*10000 AS HUGEINT)*10000+volume//2)//NULLIF(volume,0)) "
        "AS DECIMAL(30,0))*CAST('0.00000001' AS DECIMAL(9,8))"
    )
    metrics = {
        "count": "count(*)",
        "delivered_count": "count(*) FILTER(WHERE delivered_lots>0)",
        "sum_amount": f"sum({amount})",
        "avg_amount": f"sum({amount})",
        "min_amount": f"min({amount})",
        "max_amount": f"max({amount})",
        "sum_volume": "sum(volume)",
        "sum_delivered_volume": "sum(delivered_volume)",
        "sum_lots": "sum(quantity)",
        "sum_delivered_lots": "sum(delivered_lots)",
        "weighted_unit_price": f"sum({amount})",
        "min_unit_price": f"min({price})",
        "max_unit_price": f"max({price})",
    }
    dimension_expressions = list(expressions)
    expressions.extend(f"{metrics[m]} AS {m}" for m in plan.metrics)
    expressions += [
        "count(*) AS _count",
        "sum(volume) AS _volume",
        "count(*) FILTER(WHERE delivered_lots IS NULL) AS _null_delivery",
    ]
    group_by = " GROUP BY " + ",".join(grouping) if grouping else ""
    sql = f"SELECT {','.join(expressions)} FROM {source}{where}{group_by}"
    args = params
    if plan.kind == "compare":
        args = (plan.periods[0].start, plan.periods[0].end) + params
    # Ratios are computed exactly in Python; sorting these aggregates in SQL would sort
    # their numerators. Executor sorts only the bounded <=MAX_GROUPS exact result set.
    cardinality = (
        f"SELECT count(*) FROM (SELECT {','.join(dimension_expressions)} FROM {source}"
        f"{where}{group_by} LIMIT 20001) bounded_groups"
        if grouping
        else "SELECT 1"
    )
    return CompiledQuery(
        sql + " LIMIT 20001",
        args,
        tuple(groups) + tuple(plan.metrics) + ("_count", "_volume", "_null_delivery"),
        probe,
        params,
        cardinality,
        args if grouping else (),
        tables,
    )
