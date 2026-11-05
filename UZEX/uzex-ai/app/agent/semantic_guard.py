"""Independent semantic invariants. Confidence never authorizes execution."""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.agent.entity_resolver import normalize
from app.agent.language_detector import conservative_normalize, outside_names
from app.agent.query_validator import PlanRejected, validate_plan
from app.agent.semantic_models import LANGUAGE_MAP


@dataclass(frozen=True)
class Signals:
    role: str
    metric: str
    negation: str
    year: int | None
    boundary: str
    status: str | None


def signals(question):
    text = normalize(outside_names(conservative_normalize(question)))
    buyer = bool(re.search(r"sotib ol|\bolgan\b|xaridor|pokup|kupil|kupila|priobrel", text))
    seller = bool(re.search(r"sotgan|sotuvchi|prodal|prodav", text))
    role = "both" if buyer and seller else "buyer" if buyer else "seller" if seller else "unknown"
    money = bool(re.search(r"summa|summ[aue]|qiymat|pul|summe|stoimost", text))
    volume = bool(re.search(r"tonna|tonn|hajm|miqdor|obyom|kilogram|\bkg\b", text))
    counts = bool(re.search(r"nechta|necha|qanca|qancha|soni|skolko sdel|kolichestvo sdel", text))
    if re.search(r"miqdor emas|hajm emas|ne obyom", text):
        volume = False
    if re.search(r"summa emas|ne summa", text):
        money = False
    if re.search(r"soni emas|ne kolichestvo", text):
        counts = False
    explicit_count = counts and bool(
        re.search(
            r"bitimlar? soni|bitimlar? nechta|nechta bitim|skolko sdel|kolichestvo sdel", text
        )
    )
    metric = (
        "count"
        if explicit_count
        else "mixed"
        if money and volume
        else "amount"
        if money
        else "volume"
        if volume
        else "count"
        if counts
        else "unknown"
    )
    negation = (
        "double"
        if re.search(r"emas demadim|emasligini aytmadim|ne govoril.*ne", text)
        else "question"
        if re.search(r"emasmi|ne nuzhno li", text)
        else "negative"
        if re.search(r"\bemas\b|chiqarma|isklyuch|\bne\b", text)
        else "none"
    )
    years = re.findall(r"\b20[0-9]{2}\b", text)
    year = int(years[0]) if len(set(years)) == 1 else None
    boundary = (
        "through"
        if re.search(r"oxirigacha|oxirigaca|vplot do|do kontsa|до конца", text)
        else "before"
        if re.search(r"dan oldin|\bdo 20", text)
        else "after"
        if re.search(r"dan keyin|posle 20", text)
        else "within"
    )
    status = (
        "Исполнен(Частично)"
        if re.search(r"qisman|chastich", text)
        else "Аннулирован(Не оплачен)"
        if re.search(r"bekor|annul|otmen", text)
        else "Исполнен"
        if re.search(r"bajarilgan|ispolnenn|vipolnenn", text)
        else None
    )
    return Signals(role, metric, negation, year, boundary, status)


def relative_range(question, reference):
    text = normalize(outside_names(question))
    if re.search(r"\bbugun\b|\bsegodnya\b", text):
        return reference, reference
    if re.search(r"\bkecha\b|\bvchera\b", text):
        day = reference - timedelta(days=1)
        return day, day
    if re.search(r"bu yil|etom godu|tekushchem godu", text):
        return date(reference.year, 1, 1), date(reference.year, 12, 31)
    if re.search(r"otgan yil|proshlom godu", text):
        return date(reference.year - 1, 1, 1), date(reference.year - 1, 12, 31)
    if re.search(r"otgan oy|proshlom mesyatse", text):
        end = reference.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    return None


class GuardRejected(ValueError):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)


def fail(reason, status="AMBIGUOUS"):
    raise GuardRejected(status, reason)


def check_decision(question, hint, decision, context, engine, reference_date=None):
    if decision.language == "unsupported":
        if (
            decision.status != "UNSUPPORTED"
            or decision.plan is not None
            or decision.reason != "UNSUPPORTED_LANGUAGE"
        ):
            fail("MODEL_CONTRACT", "ERROR")
        return None
    if hint.language and decision.language != hint.language:
        fail("LANGUAGE_MISMATCH")
    if decision.status != "PLAN":
        if decision.plan is not None or decision.reason == "NONE":
            fail("MODEL_CONTRACT", "ERROR")
        return None
    if decision.plan is None or decision.reason != "NONE":
        fail("MODEL_CONTRACT", "ERROR")
    plan = decision.plan
    if plan.language != LANGUAGE_MAP[decision.language]:
        fail("LANGUAGE_MISMATCH")
    intent = signals(question)
    if intent.negation in ("question", "double"):
        fail("NEGATION_QUESTION" if intent.negation == "question" else "DOUBLE_NEGATION")
    try:
        plan = validate_plan(plan)
    except PlanRejected as exc:
        raise GuardRejected(exc.status, exc.reason) from None
    text = normalize(question)
    if not re.search(
        (
            r"bitim|sdel|shartnoma|kontrakt|stir|inn|tn ved|broker|firma|kompani|"
            r"sement|narx|summa|hajm|miqdor|yetkaz"
        ),
        text,
    ):
        fail("NEGATION_TARGET" if intent.negation == "negative" else "MISSING_TASK")
    if set(plan.metrics) & {
        "sum_amount",
        "avg_amount",
        "min_amount",
        "max_amount",
        "weighted_unit_price",
        "min_unit_price",
        "max_unit_price",
    }:
        if not re.search(r"uzs|usd|som|sumda|dollar|valyuta|sumakh|dollarakh", text):
            fail("CURRENCY_AMBIGUOUS")
    ranking = bool(re.search(r"eng kop|eng katta|bolshe vsego|naibol|top\s*[0-9]*", text))
    if ranking and intent.metric == "unknown":
        fail("METRIC_AMBIGUOUS")
    if plan.metrics:
        if intent.metric == "count" and set(plan.metrics) - {"count", "delivered_count"}:
            fail("METRIC_MISMATCH")
        if intent.metric == "volume" and set(plan.metrics) & {
            "sum_amount",
            "avg_amount",
            "max_amount",
            "min_amount",
        }:
            fail("METRIC_MISMATCH")
        if intent.metric in ("amount", "volume") and set(plan.metrics) <= {
            "count",
            "delivered_count",
        }:
            fail("METRIC_MISMATCH")
        if intent.metric == "amount" and set(plan.metrics) & {
            "sum_volume",
            "sum_lots",
            "sum_delivered_volume",
        }:
            fail("METRIC_MISMATCH")
    if ranking and plan.group_by and plan.order_by:
        minimum = bool(re.search(r"eng kichik|naimensh|minimaln", text))
        if plan.order_by[0].direction != ("asc" if minimum else "desc"):
            fail("COMPARATIVE_MISMATCH")
    expected = "buyer" if intent.role == "buyer" else "seller" if intent.role == "seller" else None
    role_fields = (
        set(plan.group_by) | {f.field for f in plan.filters} | {e.field for e in plan.entities}
    )
    if expected:
        opposite = "seller" if expected == "buyer" else "buyer"
        if any(f.startswith(opposite + "_") for f in role_fields):
            fail("ROLE_MISMATCH")
        if ranking and not any(f.startswith(expected + "_") for f in plan.group_by):
            fail("ROLE_REQUIRED")
    if intent.year and plan.kind != "lookup":
        year = intent.year
        relevant = [f for f in plan.filters if f.field == "deal_date"]
        if intent.boundary == "before":
            valid = any(f.op == "lt" and f.values == (date(year, 1, 1),) for f in relevant)
        elif intent.boundary == "after":
            valid = any(
                (f.op == "gte" and f.values == (date(year + 1, 1, 1),))
                or (f.op == "gt" and f.values == (date(year, 12, 31),))
                for f in relevant
            )
        elif intent.boundary == "through":
            valid = any(
                (f.op == "lte" and f.values == (date(year, 12, 31),))
                or (f.op == "between" and f.values[1] == date(year, 12, 31))
                for f in relevant
            )
        else:
            valid = any(
                f.op == "between" and f.values == (date(year, 1, 1), date(year, 12, 31))
                for f in relevant
            )
            valid = valid or (
                any(f.op == "gte" and f.values == (date(year, 1, 1),) for f in relevant)
                and any(f.op == "lte" and f.values == (date(year, 12, 31),) for f in relevant)
            )
        if not valid and plan.kind != "compare":
            fail("TIME_MISMATCH")
    if reference_date:
        expected_range = relative_range(question, reference_date)
        if expected_range:
            relevant = [f for f in plan.filters if f.field == "deal_date"]
            start, end = expected_range
            valid = any(
                (f.op == "eq" and f.values == (start,) and start == end)
                or (f.op == "between" and f.values == (start, end))
                for f in relevant
            )
            if not valid:
                fail("TIME_MISMATCH")
    if intent.status:
        op = "ne" if intent.negation == "negative" else "eq"
        if not any(
            f.field == "status" and f.op == op and f.values == (intent.status,)
            for f in plan.filters
        ):
            fail("NEGATION_MISMATCH" if op == "ne" else "STATUS_MISMATCH")
    if re.search(r"\bbarcha\b|\bvse sdel", text) and not intent.status:
        if any(f.field == "status" for f in plan.filters):
            fail("STATUS_MISMATCH")
    if plan.lookup:
        value = str(plan.lookup.identifier)
        tokens = re.findall(r"BK[0-9]{3}|[0-9]+", question, re.I)
        if value.upper() not in {token.upper() for token in tokens}:
            fail("IDENTIFIER_NOT_GROUNDED", "ERROR")
    kinds = {
        "seller_inn": "company",
        "buyer_inn": "company",
        "seller_broker_code": "broker",
        "buyer_broker_code": "broker",
        "product_name": "product",
        "tn_ved_code": "tn_ved",
        "region": "region",
    }
    for entity in plan.entities:
        if normalize(entity.text) not in text:
            fail("ENTITY_NOT_GROUNDED", "ERROR")
        kind = kinds.get(entity.field)
        if kind:
            resolution = engine.resolver.resolve(kind, entity.text)
            if resolution.status == "AMBIGUOUS":
                fail("ENTITY_AMBIGUOUS")
    for f in plan.filters:
        kind = kinds.get(f.field)
        if kind:
            for value in f.values:
                if not isinstance(value, str):
                    continue
                # String membership avoids Python's global regex cache retaining request IDs.
                literal = " " + normalize(value) + " " in " " + text + " "
                authorized = (kind, value) in context.authorized
                if not literal and not authorized:
                    fail("ENTITY_NOT_GROUNDED", "ERROR")
                if kind in context.ambiguous and not literal:
                    fail("ENTITY_AMBIGUOUS")
        if f.field == "currency":
            if not re.search(r"uzs|usd|som|sumda|dollar|dollar|rubl|valyuta", text):
                fail("CURRENCY_AMBIGUOUS")
        if f.field in (
            "amount",
            "amount_uzs",
            "quantity",
            "volume",
            "delivered_lots",
            "starting_price",
        ):
            for value in f.values:
                if isinstance(value, (int, Decimal)):
                    allowed = {
                        Decimal(v.replace(",", "."))
                        for v in re.findall(r"[0-9]+(?:[.,][0-9]+)?", question)
                    }
                    for number, multiplier in re.findall(
                        r"([0-9]+(?:[.,][0-9]+)?)\s*(mln|ming|million|mlrd)", text
                    ):
                        allowed.add(
                            Decimal(number.replace(",", "."))
                            * {
                                "mln": 1000000,
                                "million": 1000000,
                                "ming": 1000,
                                "mlrd": 1000000000,
                            }[multiplier]
                        )
                    if Decimal(value) not in allowed:
                        fail("NUMBER_NOT_GROUNDED", "ERROR")
    return plan
