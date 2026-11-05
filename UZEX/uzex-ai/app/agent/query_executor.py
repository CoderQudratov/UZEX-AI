"""Verified structured execution only. No SQL entrypoint, logs, telemetry or result cache."""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import cmp_to_key

from pydantic import ValidationError

from app.agent.entity_resolver import EntityResolver
from app.agent.evidence import EvidenceContext, EvidenceMismatch
from app.agent.query_compiler import LOOKUPS, METRIC_MEANINGS, compile_plan
from app.agent.query_models import AuditSQL, Filter, QueryPlan, VerifiedResult
from app.agent.query_validator import (
    LOT_METRICS,
    MAX_GROUPS,
    MAX_RESPONSE_BYTES,
    MONEY_METRICS,
    PHYSICAL_METRICS,
    PlanRejected,
    validate_plan,
)
from app.db.runtime import DatabaseBusy, DatabaseTimeout, DatabaseUnavailable, ReadOnlyWarehouse

ENTITY_KINDS = {
    "seller_inn": "company",
    "buyer_inn": "company",
    "seller_broker_code": "broker",
    "buyer_broker_code": "broker",
    "product_name": "product",
    "tn_ved_code": "tn_ved",
    "region": "region",
    "status": "status",
    "contract_status": "contract_status",
}
ALL_TABLES = ("deals", "contracts", "participants", "brokers", "usd_rates")


def ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    with localcontext() as context:
        context.prec = 60
        return (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )


class QueryEngineUnavailable(RuntimeError):
    """Safe deployment initialization error."""


class QueryExecutor:
    def __init__(self, settings):
        # Initialize once before requests. Only source dictionaries/metadata stay in RAM.
        try:
            self.warehouse = ReadOnlyWarehouse(settings)
            self.source = EvidenceContext(settings.database_path.resolve(strict=True))
            self.resolver = EntityResolver(self.warehouse)
        except (OSError, ValueError, KeyError, DatabaseUnavailable):
            raise QueryEngineUnavailable("Verified query engine is unavailable") from None

    def execute(self, input_plan: QueryPlan) -> VerifiedResult:
        audit = []
        stage = "input"

        def result(status, reason="", **kwargs):
            return VerifiedResult(
                status=status,
                reason=reason,
                dataset_version=self.source.version,
                internal_sql=tuple(audit),
                **kwargs,
            )

        try:
            if not isinstance(input_plan, QueryPlan):
                return result("UNSUPPORTED", "INVALID_PLAN")
            if len(input_plan.model_dump_json(warnings="error").encode()) > 16384:
                return result("UNSUPPORTED", "PLAN_SIZE")
            plan = validate_plan(input_plan)
            filters = list(plan.filters)
            for entity in plan.entities:
                resolution = self.resolver.resolve(ENTITY_KINDS[entity.field], entity.text)
                if resolution.status != "VERIFIED":
                    return result(
                        resolution.status, resolution.reason, candidates=resolution.candidates
                    )
                filters.append(
                    Filter(field=entity.field, op="eq", values=(resolution.candidates[0].value,))
                )
            plan = validate_plan(
                plan.model_copy(update={"filters": tuple(filters), "entities": ()})
            )
            stage = "execution"
            self.source.assert_current()
            compiled = compile_plan(plan)

            def run(connection, sql, parameters):
                audit.append(AuditSQL(sql=sql, parameters=parameters))
                return connection.execute(sql, parameters)

            with self.warehouse.connection() as connection:
                if plan.kind == "lookup":
                    values = run(connection, compiled.sql, compiled.parameters).fetchall()
                    rows = tuple(dict(zip(compiled.columns, row, strict=True)) for row in values)
                    table = LOOKUPS[plan.lookup.entity][0]
                    evidence = self.source.make(
                        tables=ALL_TABLES if table == "deals_enriched" else (table,)
                    )
                    output = result(
                        "VERIFIED" if rows else "NOT_FOUND",
                        rows=rows,
                        row_count=len(rows),
                        evidence=evidence,
                        original_currency=tuple(
                            sorted({r["currency"] for r in rows if "currency" in r})
                        ),
                        measurement_units=tuple(sorted({r["unit"] for r in rows if "unit" in r})),
                    )
                    return self._size_guard(output)
                stats = run(connection, compiled.probe_sql, compiled.probe_parameters).fetchone()
                count, currencies, units, lot_count, nulls = stats
                currency_count, unit_count = len(currencies or ()), len(units or ())
                currencies, units = tuple(currencies or ()), tuple(units or ())
                semantics = dict(
                    filters=plan.filters, original_currency=currencies, measurement_units=units
                )
                original_filter = any(
                    f.field in {"amount", "starting_price", "base_price", "unit_price_rounded_8"}
                    for f in plan.filters
                )
                physical_filter = any(
                    f.field in {"volume", "delivered_volume", "unit_price_rounded_8"}
                    for f in plan.filters
                )
                if original_filter and currency_count > 1:
                    return result("AMBIGUOUS", "MIXED_CURRENCIES", **semantics)
                if physical_filter and unit_count > 1:
                    return result("AMBIGUOUS", "MIXED_UNITS", **semantics)
                if plan.kind != "records":
                    if (
                        set(plan.metrics) & MONEY_METRICS
                        and plan.money_mode == "original"
                        and currency_count > 1
                        and "currency" not in plan.group_by
                    ):
                        return result("AMBIGUOUS", "MIXED_CURRENCIES", **semantics)
                    if (
                        set(plan.metrics) & PHYSICAL_METRICS
                        and unit_count > 1
                        and "unit" not in plan.group_by
                    ):
                        return result("AMBIGUOUS", "MIXED_UNITS", **semantics)
                    if set(plan.metrics) & LOT_METRICS and (unit_count > 1 or lot_count > 1):
                        return result("AMBIGUOUS", "LOT_MEANING", **semantics)
                cardinality = 0
                if compiled.group_sql:
                    cardinality = run(
                        connection, compiled.group_sql, compiled.group_parameters
                    ).fetchone()[0]
                    if cardinality > MAX_GROUPS:
                        return result("UNSUPPORTED", "GROUP_LIMIT", **semantics)
                if count == 0 and (
                    plan.kind == "records" or set(plan.metrics) - {"count", "delivered_count"}
                ):
                    return result(
                        "NOT_FOUND",
                        "NO_MATCHES",
                        **semantics,
                        evidence=self.source.make(tables=compiled.tables, matched_transactions=0),
                    )
                raw = run(connection, compiled.sql, compiled.parameters).fetchall()
                records = [dict(zip(compiled.columns, row, strict=True)) for row in raw]
                if plan.kind != "records":
                    for row in records:
                        if "avg_amount" in row:
                            row["avg_amount"] = ratio(row["avg_amount"], row["_count"])
                        if "weighted_unit_price" in row:
                            row["weighted_unit_price"] = ratio(
                                row["weighted_unit_price"], row["_volume"]
                            )
                        for field in ("_count", "_volume", "_null_delivery"):
                            row.pop(field)
                    if plan.kind == "compare":
                        # Missing period evidence is never turned into a zero amount.
                        if {r.get("period") for r in records} != {0, 1}:
                            return result("NOT_FOUND", "COMPARISON_PERIOD_ABSENT", **semantics)
                        for row in records:
                            period = plan.periods[row["period"]]
                            row["period_start"], row["period_end"] = period.start, period.end

                def compare(a, b):
                    keys = [(o.field, o.direction) for o in plan.order_by]
                    ties = (["period"] if plan.kind == "compare" else []) + list(plan.group_by)
                    if plan.kind != "records":
                        keys += [(k, "asc") for k in ties]
                    for field, direction in keys:
                        av, bv = a.get(field), b.get(field)
                        if av is None or bv is None:
                            value = 0 if av is bv else 1 if av is None else -1
                        else:
                            value = (av > bv) - (av < bv)
                            if direction == "desc":
                                value = -value
                        if value:
                            return value
                    return 0

                if plan.kind != "records":
                    records.sort(key=cmp_to_key(compare))
                if plan.kind == "compare" and len(records) > plan.limit:
                    return result("UNSUPPORTED", "COMPARISON_OUTPUT_LIMIT", **semantics)
                limited = len(records) > plan.limit
                records = records[: plan.limit]
                notes = ["ALL_STATUSES_UNLESS_FILTERED", "NO_NULL_DELIVERY_IMPUTATION"]
                if plan.money_mode == "uzs":
                    notes.append("UZS_AT_TRADE_DATE_RATE")
                if plan.kind == "compare":
                    notes.append("PERIOD_LABELS_USE_EXPLICIT_INCLUSIVE_RANGES")
                evidence = self.source.make(
                    tables=compiled.tables,
                    matched_transactions=count,
                    output_limited=limited,
                    grouping_cardinality=cardinality,
                    null_delivery_transactions=nulls,
                    note_codes=tuple(notes),
                )
                metadata = {m: METRIC_MEANINGS[m] for m in plan.metrics}
                if plan.money_mode:
                    metadata["currency_basis"] = plan.money_mode
                if plan.kind == "compare":
                    metadata["comparison"] = (
                        "Side-by-side explicit periods; no imputed missing groups"
                    )
                output = result(
                    "VERIFIED",
                    rows=tuple(records),
                    row_count=len(records),
                    aggregates=metadata,
                    evidence=evidence,
                    **semantics,
                )
                return self._size_guard(output)
        except PlanRejected as exc:
            return result(exc.status, exc.reason)
        except (ValidationError, TypeError, ValueError, KeyError, OverflowError):
            return result(
                "ERROR" if stage == "execution" else "UNSUPPORTED",
                "INTERNAL_FAILURE" if stage == "execution" else "INVALID_PLAN",
            )
        except EvidenceMismatch:
            return result("ERROR", "ARTIFACT_CHANGED")
        except DatabaseTimeout:
            return result("ERROR", "TIME_BUDGET")
        except DatabaseBusy:
            return result("ERROR", "CAPACITY")
        except DatabaseUnavailable:
            return result("ERROR", "DATABASE_FAILURE")
        except Exception:
            return result("ERROR", "INTERNAL_FAILURE")

    def _size_guard(self, output):
        if len(output.model_dump_json().encode()) > MAX_RESPONSE_BYTES:
            return VerifiedResult(
                status="UNSUPPORTED", reason="RESPONSE_SIZE", dataset_version=self.source.version
            )
        return output
