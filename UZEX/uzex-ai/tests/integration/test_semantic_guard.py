from datetime import date

import pytest

from app.agent.query_executor import QueryExecutor
from app.agent.query_models import Filter, Lookup, Order, QueryPlan
from app.agent.semantic_models import SemanticDecision
from app.agent.semantic_router import SemanticRouter
from app.core.config import Settings


@pytest.fixture(scope="module")
def engine(warehouse_path):
    return QueryExecutor(Settings(database_path=warehouse_path))


class FixedPlanner:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    async def generate(self, *args):
        self.calls += 1
        return self.output, 1, 0.0


def plan_output(plan, language="uz_latn"):
    return SemanticDecision(
        status="PLAN", language=language, reason="NONE", plan=plan
    ).model_dump_json()


@pytest.mark.parametrize(
    ("question", "plan", "reason"),
    [
        (
            "2025 yilda nechta bitim?",
            QueryPlan(
                kind="aggregate",
                metrics=("sum_amount",),
                money_mode="uzs",
                filters=(
                    Filter(
                        field="deal_date",
                        op="between",
                        values=(date(2025, 1, 1), date(2025, 12, 31)),
                    ),
                ),
            ),
            "CURRENCY_AMBIGUOUS",
        ),
        (
            "2025 dan oldin nechta bitim?",
            QueryPlan(
                kind="aggregate",
                metrics=("count",),
                filters=(Filter(field="deal_date", op="gte", values=(date(2026, 1, 1),)),),
            ),
            "TIME_MISMATCH",
        ),
        (
            "faqat bajarilgan bitimlar soni",
            QueryPlan(
                kind="aggregate",
                metrics=("count",),
                filters=(Filter(field="status", op="ne", values=("Исполнен",)),),
            ),
            "STATUS_MISMATCH",
        ),
        (
            "bajarilgan bitimlar kerak emas, qolgan bitimlar soni",
            QueryPlan(
                kind="aggregate",
                metrics=("count",),
                filters=(Filter(field="status", op="eq", values=("Исполнен",)),),
            ),
            "NEGATION_MISMATCH",
        ),
        (
            "2025 yilda tonnada eng kop sement olgan firma",
            QueryPlan(
                kind="aggregate",
                metrics=("sum_volume",),
                group_by=("seller_inn",),
                order_by=(Order(field="sum_volume"),),
                filters=(
                    Filter(
                        field="deal_date",
                        op="between",
                        values=(date(2025, 1, 1), date(2025, 12, 31)),
                    ),
                    Filter(field="unit", op="eq", values=("тонна",)),
                ),
            ),
            "ROLE_MISMATCH",
        ),
        (
            "bitim 100001 haqida malumot ber",
            QueryPlan(kind="lookup", lookup=Lookup(entity="transaction", identifier=100002)),
            "IDENTIFIER_NOT_GROUNDED",
        ),
    ],
)
@pytest.mark.anyio
async def test_independent_guard_rejects_wrong_but_schema_valid_plans(
    engine, question, plan, reason
):
    planner = FixedPlanner(plan_output(plan))
    result = await SemanticRouter(engine, planner).answer(question)
    assert result.status in ("AMBIGUOUS", "ERROR")
    assert result.reason == reason
    assert result.verified_result is None
    assert planner.calls == 1


@pytest.mark.anyio
async def test_uzbek_cyrillic_never_becomes_russian(engine):
    plan = QueryPlan(kind="aggregate", language="ru", metrics=("count",))
    result = await SemanticRouter(engine, FixedPlanner(plan_output(plan, "ru"))).understand(
        "Барча битимлар сони"
    )
    assert result.status == "AMBIGUOUS" and result.reason == "LANGUAGE_MISMATCH"
    assert result.language == "uz_cyrl"


@pytest.mark.parametrize(
    "raw",
    [
        '{"sql":"DROP TABLE deals"}',
        '{"answer":"invented factual amount"}',
        "not JSON",
        '{"status":"PLAN","language":"uz_latn","reason":"NONE","plan":null,"confidence":1.0}',
    ],
)
@pytest.mark.anyio
async def test_model_cannot_return_sql_answers_or_confidence_authorization(engine, raw):
    router = SemanticRouter(engine, FixedPlanner(raw))
    result = await router.answer("barcha bitimlar soni")
    assert result.status == "ERROR" and result.reason == "MODEL_JSON_INVALID"
    assert result.verified_result is None
    assert router.metrics.json_validation_failures == 1
    assert raw not in result.answer


@pytest.mark.anyio
async def test_direct_lookup_and_missing_credentials_are_distinct(engine):
    router = SemanticRouter(engine)
    direct = await router.answer("bitim 100001")
    assert direct.status == "VERIFIED" and direct.model_calls == 0
    assert direct.verified_result.rows[0]["deal_id"] == 100001
    unavailable = await router.answer("2025 yilda nechta bitim?")
    assert unavailable.status == "ERROR" and unavailable.reason == "GEMINI_NOT_CONFIGURED"


@pytest.mark.anyio
async def test_single_turn_no_invented_context_and_unsupported_languages(engine):
    planner = FixedPlanner(plan_output(QueryPlan(kind="aggregate", metrics=("count",))))
    router = SemanticRouter(engine, planner)
    for text in ("How many transactions?", "Show broker BK001", "有多少笔交易？"):
        result = await router.answer(text)
        assert result.status == "UNSUPPORTED" and result.verified_result is None
    result = await router.answer("shularni ham korsat")
    assert result.status == "AMBIGUOUS" and result.reason == "FOLLOWUP_UNRESOLVED"
    assert planner.calls == 0


@pytest.mark.anyio
async def test_one_plan_call_then_deterministic_answer_with_real_database(engine):
    planner = FixedPlanner(plan_output(QueryPlan(kind="aggregate", metrics=("count",))))
    router = SemanticRouter(engine, planner)
    result = await router.answer("barcha bitimlar soni")
    assert result.status == "VERIFIED" and result.verified_result.rows[0]["count"] == 500000
    assert "500000" in result.answer and planner.calls == 1
    assert "internal_sql" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("question", "start", "end", "language"),
    [
        ("bugun nechta bitim?", date(2026, 11, 5), date(2026, 11, 5), "uz_latn"),
        ("kecha nechta bitim?", date(2026, 11, 4), date(2026, 11, 4), "uz_latn"),
        ("бу йил битимлар сони", date(2026, 1, 1), date(2026, 12, 31), "uz_cyrl"),
        ("Сколько сделок в прошлом году?", date(2025, 1, 1), date(2025, 12, 31), "ru"),
    ],
)
@pytest.mark.anyio
async def test_relative_time_is_anchored_to_tashkent_reference_date(
    engine, question, start, end, language
):
    from app.agent.semantic_models import LANGUAGE_MAP

    plan = QueryPlan(
        kind="aggregate",
        language=LANGUAGE_MAP[language],
        metrics=("count",),
        filters=(Filter(field="deal_date", op="between", values=(start, end)),),
    )
    router = SemanticRouter(
        engine, FixedPlanner(plan_output(plan, language)), reference_date=date(2026, 11, 5)
    )
    assert (await router.understand(question)).status == "VERIFIED"
    wrong = plan.model_copy(
        update={
            "filters": (
                Filter(
                    field="deal_date", op="between", values=(date(2020, 1, 1), date(2020, 12, 31))
                ),
            )
        }
    )
    router = SemanticRouter(
        engine, FixedPlanner(plan_output(wrong, language)), reference_date=date(2026, 11, 5)
    )
    assert (await router.understand(question)).reason == "TIME_MISMATCH"


@pytest.mark.anyio
async def test_request_identifiers_are_not_retained_in_regex_pattern_cache(engine):
    import re

    identifier = "919283746"
    question = "STIR " + identifier + " haqida malumot ber"
    plan = QueryPlan(kind="lookup", lookup=Lookup(entity="company", identifier=identifier))
    router = SemanticRouter(engine, FixedPlanner(plan_output(plan)))
    re.purge()
    result = await router.understand(question)
    assert result.status == "VERIFIED"
    assert not any(identifier in str(key) for key in re._cache)
