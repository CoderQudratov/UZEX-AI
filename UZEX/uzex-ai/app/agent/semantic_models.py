"""Closed model output and request-local semantic results; no factual prose from Gemini."""

from typing import Literal

from pydantic import Field

from app.agent.query_models import QueryPlan, Status, StrictModel, VerifiedResult

SemanticLanguage = Literal["uz_latn", "uz_cyrl", "ru", "unsupported"]
LANGUAGE_MAP = {"uz_latn": "uz-Latn", "uz_cyrl": "uz-Cyrl", "ru": "ru"}
Reason = Literal[
    "NONE",
    "METRIC_AMBIGUOUS",
    "CURRENCY_AMBIGUOUS",
    "ENTITY_AMBIGUOUS",
    "NEGATION_UNRESOLVED",
    "FOLLOWUP_UNRESOLVED",
    "OUT_OF_SCOPE",
    "UNSUPPORTED_LANGUAGE",
    "UNSUPPORTED_CONDITION",
    "UNSUPPORTED_SCHEMA",
    "MODEL_REFUSAL",
]


class SemanticDecision(StrictModel):
    status: Literal["PLAN", "AMBIGUOUS", "UNSUPPORTED"]
    language: SemanticLanguage
    reason: Reason
    plan: QueryPlan | None


class SemanticResult(StrictModel):
    status: Status
    language: SemanticLanguage
    reason: str
    plan: QueryPlan | None = None
    verified_result: VerifiedResult | None = None
    answer: str = ""
    model_calls: int = Field(default=0, ge=0, le=2)
    model_latency_ms: float | None = None
    end_to_end_ms: float = 0
