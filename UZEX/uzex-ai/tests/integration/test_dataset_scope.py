"""Explicit unrelated tasks never reach the planner or invent warehouse evidence."""

import pytest

from app.agent.query_executor import QueryExecutor
from app.agent.semantic_router import SemanticRouter, clearly_out_of_scope
from app.core.config import Settings


@pytest.fixture(scope="module")
def scope_engine(warehouse_path):
    engine = QueryExecutor(Settings(database_path=warehouse_path))
    yield engine
    engine.warehouse.close()


class NeverPlanner:
    calls = 0

    async def generate(self, *_args):
        self.calls += 1
        raise AssertionError("Out-of-scope input must not invoke a model")


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("python kod yozib ber", "uz_latn"),
        ("menga javascript dastur yaratib ber", "uz_latn"),
        ("пайтон код ёзиб бер", "uz_cyrl"),
        ("напиши код Python", "ru"),
        ("создай HTML код", "ru"),
        ("ob-havo qanday?", "uz_latn"),
        ("об-ҳаво қандай?", "uz_cyrl"),
        ("Какая погода сегодня?", "ru"),
        ("dori tavsiya qil", "uz_latn"),
        ("Как лечить кашель?", "ru"),
        ("O‘zbekiston poytaxti qaysi?", "uz_latn"),
        ("menga latifa ayt", "uz_latn"),
        ("2+2", "uz_latn"),
    ],
)
@pytest.mark.anyio
async def test_unrelated_requests_fail_closed_without_model_or_facts(
    scope_engine, question, language
):
    planner = NeverPlanner()
    result = await SemanticRouter(scope_engine, planner).answer(question)
    assert result.status == "UNSUPPORTED"
    assert result.reason == "OUT_OF_SCOPE"
    assert result.language == language
    assert result.plan is None and result.verified_result is None
    assert not any(character.isdigit() for character in result.answer)
    assert "UZEX" in result.answer
    assert planner.calls == 0


@pytest.mark.parametrize(
    "question",
    [
        '"Python kod yozib" kompaniyasi bitimlar soni',
        "Python kompaniyasi 2025 yilda nechta bitim sotgan?",
        "Kod mahsuloti boyicha bitimlar soni",
        '"Ob-havo" kompaniyasi nechta bitim tuzgan?',
        "Ob-havo kompaniyasi bitimlari haqida malumot ber",
        "Dori mahsulotining bitimlar soni qancha?",
        "2025 yilda bitimlar soni qancha?",
    ],
)
def test_technical_entity_words_are_not_coding_or_general_tasks(question):
    assert not clearly_out_of_scope(question)


@pytest.mark.parametrize("question", ["2024", "100001", "123456789"])
@pytest.mark.anyio
async def test_numeric_input_asks_for_meaning_instead_of_rejecting_language(scope_engine, question):
    planner = NeverPlanner()
    result = await SemanticRouter(scope_engine, planner).answer(question)
    assert result.status == "AMBIGUOUS"
    assert result.reason == "IDENTIFIER_CONTEXT"
    assert result.language == "uz_latn"
    assert "identifikator" in result.answer
    assert "Faqat o‘zbekcha" not in result.answer
    assert result.plan is None and result.verified_result is None
    assert planner.calls == 0
