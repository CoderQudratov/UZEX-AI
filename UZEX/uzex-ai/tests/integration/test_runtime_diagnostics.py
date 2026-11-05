import json
import logging

import pytest

from app.agent.gemini_client import PlannerFailure, api_category
from app.agent.query_executor import QueryExecutor
from app.agent.query_models import EntityReference, QueryPlan
from app.agent.semantic_models import SemanticDecision
from app.agent.semantic_router import SemanticRouter
from app.core.config import Settings
from app.core.logging import DiagnosticFilter, DiagnosticFormatter


@pytest.fixture(scope="module")
def engine(warehouse_path):
    executor = QueryExecutor(Settings(database_path=warehouse_path))
    yield executor
    executor.warehouse.close()


class Planner:
    def __init__(self, result):
        self.result = result

    async def generate(self, *_args):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result, 1, 1.0


def decision(plan):
    return SemanticDecision(
        status="PLAN", language="uz_latn", reason="NONE", plan=plan
    ).model_dump_json()


@pytest.mark.anyio
async def test_unknown_company_is_not_infrastructure_error(engine):
    plan = QueryPlan(
        kind="records",
        fields=("deal_id",),
        entities=(EntityReference(field="buyer_inn", text="Qwertyunikal"),),
    )
    result = await SemanticRouter(engine, Planner(decision(plan))).answer(
        "Qwertyunikal kompaniyasi xaridor bolgan bitimlar"
    )
    assert result.status == "NOT_FOUND"
    assert result.verified_result.rows == ()
    assert "topilmadi" in result.answer
    assert not any(character.isdigit() for character in result.answer)


@pytest.mark.anyio
async def test_ambiguous_entity_asks_for_clarification_without_facts(engine):
    raw = SemanticDecision(
        status="AMBIGUOUS", language="uz_latn", reason="ENTITY_AMBIGUOUS", plan=None
    ).model_dump_json()
    result = await SemanticRouter(engine, Planner(raw)).answer("Yabgu bitimlar haqida malumot ber")
    assert result.status == "AMBIGUOUS"
    assert "STIR" in result.answer
    assert result.verified_result is None
    assert not any(character.isdigit() for character in result.answer)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "fragment"),
    [
        (PlannerFailure("MODEL_TIMEOUT", category="GEMINI_TIMEOUT"), "vaqtda"),
        (PlannerFailure("MODEL_API_ERROR", category="GEMINI_UNAVAILABLE"), "vaqtincha"),
        (PlannerFailure("MODEL_API_ERROR", category="GEMINI_QUOTA_EXHAUSTED"), "limitiga"),
        (PlannerFailure("MODEL_UNAVAILABLE", category="GEMINI_AUTHENTICATION"), "sozlamalari"),
    ],
)
async def test_gemini_failures_are_useful_safe_uzbek_without_facts(engine, failure, fragment):
    result = await SemanticRouter(engine, Planner(failure)).answer("2025 yilda nechta bitim?")
    assert result.status == "ERROR" and result.language == "uz_latn"
    assert fragment in result.answer
    assert result.verified_result is None
    assert not any(character.isdigit() for character in result.answer)


@pytest.mark.anyio
async def test_invalid_structured_json_fails_closed(engine):
    result = await SemanticRouter(engine, Planner('{"sql":"private-untrusted"}')).answer(
        "barcha bitimlar soni"
    )
    assert result.status == "ERROR" and result.reason == "MODEL_JSON_INVALID"
    assert result.verified_result is None
    assert "private" not in result.answer and "SQL" not in result.answer


@pytest.mark.parametrize(
    ("code", "category"),
    [
        (401, "GEMINI_AUTHENTICATION"),
        (403, "GEMINI_AUTHENTICATION"),
        (404, "GEMINI_MODEL_NOT_FOUND"),
        (429, "GEMINI_QUOTA_EXHAUSTED"),
        (503, "GEMINI_UNAVAILABLE"),
        (504, "GEMINI_TIMEOUT"),
    ],
)
def test_provider_categories_do_not_collapse(code, category):
    assert api_category(code) == category


def test_diagnostic_has_only_five_safe_fields():
    data = dict(
        stage="gemini_client",
        exception_class="ServerError",
        error_category="GEMINI_UNAVAILABLE",
        elapsed_ms=3.0,
        request_id="a" * 32,
    )
    record = logging.makeLogRecord(
        dict(
            msg="stage",
            args=(),
            diagnostic=data,
            api_key="private",
            question="private",
            exc_info=(ValueError, ValueError("private"), None),
        )
    )
    assert DiagnosticFilter().filter(record)
    rendered = DiagnosticFormatter().format(record)
    assert json.loads(rendered) == data
    assert "private" not in rendered
    data["question"] = "private"
    assert not DiagnosticFilter().filter(record)
