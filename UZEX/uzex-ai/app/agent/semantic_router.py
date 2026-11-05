"""Stateless request orchestration. No conversations, user-data cache or payload logging."""

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.agent.answer_formatter import format_answer
from app.agent.gemini_client import PlannerFailure
from app.agent.language_detector import conservative_normalize, detect_language
from app.agent.prompt_builder import PromptBuilder
from app.agent.query_models import Lookup, QueryPlan
from app.agent.semantic_guard import GuardRejected, check_decision, signals
from app.agent.semantic_models import LANGUAGE_MAP, SemanticDecision, SemanticResult


@dataclass
class SemanticMetrics:
    requests: int = 0
    model_calls: int = 0
    model_responses: int = 0
    json_validation_failures: int = 0
    guard_rejections: int = 0
    language_rejections: int = 0
    model_ms: deque = field(default_factory=lambda: deque(maxlen=512))
    end_to_end_ms: deque = field(default_factory=lambda: deque(maxlen=512))


CLARIFY = {
    "METRIC_AMBIGUOUS": (
        "Miqdormi, summami yoki bitimlar sonimi?",
        "Миқдорми, суммами ёки битимлар соними?",
        "Уточните: объём, сумма или количество сделок?",
    ),
    "CURRENCY_AMBIGUOUS": (
        "Asl valyutadami yoki UZSga aylantiribmi?",
        "Асл валютадами ёки UZSга айлантирибми?",
        "В исходной валюте или с пересчётом в UZS?",
    ),
    "FOLLOWUP_UNRESOLVED": (
        "Qaysi bitim yoki tashkilotni nazarda tutyapsiz?",
        "Қайси битим ёки ташкилотни назарда тутяпсиз?",
        "Уточните, какую сделку или организацию вы имеете в виду.",
    ),
    "NEGATION_QUESTION": (
        "Inkor savolining ma’nosini aniqlashtiring.",
        "Инкор саволининг маъносини аниқлаштиринг.",
        "Уточните смысл вопроса с отрицанием.",
    ),
    "DOUBLE_NEGATION": (
        "Ikki inkor bilan nima talab qilinganini aniqlashtiring.",
        "Икки инкор билан нима талаб қилинганини аниқлаштиринг.",
        "Уточните смысл двойного отрицания.",
    ),
    "NEGATION_TARGET": (
        "Nimani chiqarib tashlash kerakligini aniqlashtiring.",
        "Нимани чиқариб ташлаш кераклигини аниқлаштиринг.",
        "Уточните, что именно требуется исключить.",
    ),
    "MISSING_TASK": (
        "Qaysi ma’lumot kerakligini aniqlashtiring.",
        "Қайси маълумот кераклигини аниқлаштиринг.",
        "Уточните, какие данные нужны.",
    ),
}
GENERIC = {
    "AMBIGUOUS": ("So‘rovni aniqlashtiring.", "Сўровни аниқлаштиринг.", "Уточните запрос."),
    "UNSUPPORTED": (
        "Bu so‘rov qo‘llab-quvvatlanmaydi.",
        "Бу сўров қўллаб-қувватланмайди.",
        "Этот запрос не поддерживается.",
    ),
    "ERROR": (
        "So‘rovni bajarib bo‘lmadi.",
        "Сўровни бажариб бўлмади.",
        "Не удалось выполнить запрос.",
    ),
}


def notice(language, status, reason):
    if language == "unsupported":
        return (
            "Faqat o‘zbekcha yoki ruscha murojaat qiling. / "
            "Пожалуйста, используйте узбекский или русский язык."
        )
    index = {"uz_latn": 0, "uz_cyrl": 1, "ru": 2}.get(language, 0)
    return CLARIFY.get(reason, GENERIC.get(status, GENERIC["AMBIGUOUS"]))[index]


def exact_lookup(question, language):
    if language not in LANGUAGE_MAP:
        return None
    patterns = {
        "transaction": (
            r"(?:(?:покажи|кўрсат|korsat)\s+)?"
            r"(?:(?:bitim(?:ni)?|битим(?:ни)?|сделк[ау])\s*(?:raqami|рақами|номер)?|"
            r"(?:номер|рақами|raqami)\s*(?:bitim(?:ni)?|битим(?:ни)?|сделк[аиу]))\s*[:№#]?\s*([0-9]{1,18})"
            r"(?:\s+(?:haqida|ҳақида))?"
        ),
        "contract": (
            r"(?:(?:покажи|кўрсат|korsat)\s+)?"
            r"(?:(?:shartnoma|шартнома|контракт|договор)\s*(?:raqami|рақами|номер)?|"
            r"(?:номер|рақами|raqami)\s*(?:shartnoma|шартнома|контракт|договор[ау]?))\s*[:№#]?\s*([0-9]{1,18})"
            r"(?:\s+(?:haqida|ҳақида))?"
        ),
        "company": (
            r"(?:(?:покажи|кўрсат|korsat)\s+)?"
            r"(?:STIR|ИНН|СТИР)(?:\s+(?:raqami|рақами|номер|компании))?\s*[:№#]?\s*([0-9]{9})"
            r"(?:\s+(?:haqida|ҳақида))?"
        ),
        "broker": (
            r"(?:(?:покажи|кўрсат|korsat)\s+)?"
            r"(?:broker|брокер[а]?)\s*[:№#]?\s*(BK[0-9]{3})"
            r"(?:\s+(?:haqida|ҳақида|to[\x27\x60\u2018\u2019]g[\x27\x60\u2018\u2019]risida|тўғрисида))?"
        ),
    }
    for entity, pattern in patterns.items():
        match = re.fullmatch(pattern + r"\s*[?.]?\s*", question.strip(), re.I)
        if match:
            identifier = (
                int(match[1]) if entity in ("transaction", "contract") else match[1].upper()
            )
            return QueryPlan(
                kind="lookup",
                language=LANGUAGE_MAP[language],
                lookup=Lookup(entity=entity, identifier=identifier),
            )
    return None


class SemanticRouter:
    def __init__(self, engine, planner=None, *, reference_date=None, max_concurrency=4):
        self.engine, self.planner = engine, planner
        self.prompts = PromptBuilder(engine)
        self.reference_date = reference_date
        self.metrics = SemanticMetrics()
        self._slots = asyncio.Semaphore(max_concurrency)

    async def understand(self, question):
        start = time.perf_counter()
        self.metrics.requests += 1
        language = "unsupported"
        calls = 0
        model_ms = None

        def output(status, reason, plan=None):
            elapsed = (time.perf_counter() - start) * 1000
            self.metrics.end_to_end_ms.append(elapsed)
            return SemanticResult(
                status=status,
                language=language,
                reason=reason,
                plan=plan,
                answer="" if status == "VERIFIED" else notice(language, status, reason),
                model_calls=calls,
                model_latency_ms=model_ms,
                end_to_end_ms=elapsed,
            )

        if not isinstance(question, str) or not question.strip() or len(question.encode()) > 4096:
            return output("UNSUPPORTED", "REQUEST_SIZE")
        hint = detect_language(question)
        language = hint.language or "unsupported"
        if hint.disposition == "unsupported":
            self.metrics.language_rejections += 1
            return output("UNSUPPORTED", "UNSUPPORTED_LANGUAGE")
        if hint.disposition == "ambiguous":
            return output("AMBIGUOUS", "IDENTIFIER_CONTEXT")
        canonical = conservative_normalize(question)
        intent = signals(question)
        stripped = canonical.strip(" ?.").casefold()
        if stripped in ("kerak", "керак"):
            return output("AMBIGUOUS", "MISSING_TASK")
        if stripped in ("kerak emas", "керак эмас"):
            return output("AMBIGUOUS", "NEGATION_TARGET")
        if intent.negation == "question":
            return output("AMBIGUOUS", "NEGATION_QUESTION")
        if intent.negation == "double":
            return output("AMBIGUOUS", "DOUBLE_NEGATION")
        if re.search(
            (
                r"\b(?:shular(?:ni)?|ularni|undan|o‘sha|osha|шу битим|шулар(?:ни)?|уларни|"
                r"ундан|ўша|эти|тот|предыдущ)|(?<!(?:dan|дан)\s)\boldingi\b"
            ),
            canonical,
            re.I,
        ):
            return output("AMBIGUOUS", "FOLLOWUP_UNRESOLVED")
        direct = exact_lookup(question, language)
        if direct is not None:
            return output("VERIFIED", "EXACT_IDENTIFIER", direct)
        if self.planner is None:
            return output("ERROR", "GEMINI_NOT_CONFIGURED")
        acquired = False
        try:
            async with asyncio.timeout(1):
                await self._slots.acquire()
            acquired = True
            reference = self.reference_date or datetime.now(ZoneInfo("Asia/Tashkent")).date()
            system, contents, context = await asyncio.to_thread(
                self.prompts.build, question, hint, reference
            )
            raw, calls, model_ms = await self.planner.generate(system, contents)
            self.metrics.model_calls += calls
            self.metrics.model_responses += 1
            self.metrics.model_ms.append(model_ms)
            try:
                decision = SemanticDecision.model_validate_json(raw)
            except (ValidationError, ValueError, TypeError):
                self.metrics.json_validation_failures += 1
                return output("ERROR", "MODEL_JSON_INVALID")
            if not hint.language or decision.language == "unsupported":
                language = decision.language
            plan = check_decision(question, hint, decision, context, self.engine, reference)
            if decision.status == "UNSUPPORTED":
                if decision.language == "unsupported":
                    self.metrics.language_rejections += 1
                return output("UNSUPPORTED", decision.reason)
            if decision.status == "AMBIGUOUS":
                return output("AMBIGUOUS", decision.reason)
            if plan is None:
                return output("ERROR", "MODEL_CONTRACT")
            return output("VERIFIED", "NONE", plan)
        except GuardRejected as exc:
            self.metrics.guard_rejections += 1
            return output(exc.status, exc.reason)
        except PlannerFailure as exc:
            calls = exc.calls
            model_ms = exc.latency_ms
            self.metrics.model_calls += calls
            return output("ERROR", exc.reason)
        except TimeoutError:
            return output("ERROR", "SEMANTIC_CAPACITY")
        except Exception:
            return output("ERROR", "SEMANTIC_INTERNAL")
        finally:
            if acquired:
                self._slots.release()

    async def answer(self, question):
        start = time.perf_counter()
        semantic = await self.understand(question)
        if semantic.status != "VERIFIED":
            return semantic
        verified = await asyncio.to_thread(self.engine.execute, semantic.plan)
        internal_language = LANGUAGE_MAP[semantic.language]
        return semantic.model_copy(
            update={
                "status": verified.status,
                "reason": verified.reason,
                "verified_result": verified,
                "answer": format_answer(verified, internal_language),
                "end_to_end_ms": (time.perf_counter() - start) * 1000,
            }
        )
