"""138 authored cases: offline contract/guard tests, explicitly NOT live LLM accuracy."""

from datetime import date

import pytest

from app.agent.language_detector import conservative_normalize, detect_language
from app.agent.query_executor import QueryExecutor
from app.agent.semantic_guard import signals
from app.agent.semantic_models import SemanticDecision
from app.agent.semantic_router import SemanticRouter
from app.core.config import Settings
from tests.fixtures.multilingual_cases import CASES, expected_plan


class OracleTransport:
    """Canned manually selected oracle output; no interpretation is performed here."""

    def __init__(self, case):
        self.case = case
        self.calls = 0

    async def generate(self, system, contents):
        self.calls += 1
        plan = expected_plan(self.case)
        if plan:
            decision = SemanticDecision(
                status="PLAN", language=self.case.language, reason="NONE", plan=plan
            )
        else:
            status, reason = self.case.expected.split(":", 1)
            # Local rejection reasons may not be model schema choices; those cases must
            # terminate before this transport is called.
            decision = SemanticDecision(
                status=status, language=self.case.language, reason=reason, plan=None
            )
        return decision.model_dump_json(), 1, 0.0


@pytest.fixture(scope="module")
def semantic_engine(warehouse_path):
    return QueryExecutor(Settings(database_path=warehouse_path))


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{i:03d}-{c.language}-{c.expected}" for i, c in enumerate(CASES)]
)
@pytest.mark.anyio
async def test_fixed_multilingual_oracles_offline(case, semantic_engine):
    hint = detect_language(case.text)
    if hint.language:
        assert hint.language == case.language
    transport = OracleTransport(case)
    router = SemanticRouter(semantic_engine, transport, reference_date=date(2026, 11, 5))
    result = await router.understand(case.text)
    if ":" in case.expected:
        status, reason = case.expected.split(":", 1)
        assert result.status == status, (result.status, result.reason)
        assert result.reason == reason
        assert result.plan is None
    else:
        assert result.status == "VERIFIED", result.reason
        assert result.plan.model_dump() == expected_plan(case).model_dump()
    assert transport.calls <= 1
    if case.language == "unsupported":
        assert transport.calls == 0
        assert not result.plan and not result.verified_result
    else:
        assert result.language == case.language


def test_corpus_size_and_equivalent_original_examples():
    assert len(CASES) >= 100
    equivalent = [
        c
        for c in CASES
        if c.text
        in {
            "2025 yilda eng kop sement olgan firma",
            "sementni 2025 da eng kop qaysi firma olgan",
            "2025 да цементни энг кўп олган фирма",
            "Какая компания купила больше всего цемента в 2025 году?",
        }
    ]
    assert len(equivalent) == 4
    assert {c.expected for c in equivalent} == {"AMBIGUOUS:METRIC_AMBIGUOUS"}


def test_normalization_does_not_rewrite_names_roles_time_or_negation():
    text = 'mn manga qanca kop kkmas "mn manga kop" MN MANGA KOP'
    assert (
        conservative_normalize(text)
        == 'men menga qancha ko\'p kerak emas "mn manga kop" MN MANGA KOP'
    )
    assert conservative_normalize("sttr 915688255") == "STIR 915688255"
    assert conservative_normalize("sttr zavodi") == "sttr zavodi"
    for text in (
        "sotgan",
        "sotib olgan",
        "2025 dan oldin",
        "2025 dan keyin",
        "kerak emasmi",
        "kerak emas demadim",
    ):
        assert conservative_normalize(text) == text


def test_contrastive_signatures_do_not_collapse():
    negatives = [
        signals(q).negation for q in ("kerak", "kerak emas", "kerak emasmi", "kerak emas demadim")
    ]
    assert len(set(negatives)) == 4
    assert signals("2025 dan oldin").boundary != signals("2025 dan keyin").boundary
    assert signals("sotgan").role != signals("sotib olgan").role
    assert signals("eng katta summa").metric != signals("eng katta miqdor").metric
    assert signals("barcha bitimlar").status != signals("faqat bajarilgan bitimlar").status
