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
from app.core.diagnostics import correlation_id, diagnostic


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
    "ENTITY_AMBIGUOUS": (
        (
            "Qaysi kompaniya yoki mahsulotni nazarda tutyapsiz? Aniq nomi yoki STIRni "
            "kiriting; sotuvchi yoki xaridor ekanini belgilang."
        ),
        (
            "Қайси компания ёки маҳсулотни назарда тутяпсиз? Аниқ номи ёки СТИРни "
            "киритинг; сотувчи ёки харидор эканини белгиланг."
        ),
        (
            "Уточните компанию или продукт: укажите точное название или ИНН, а также роль "
            "продавца или покупателя."
        ),
    ),
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
INFRASTRUCTURE = {
    "GEMINI_QUOTA_EXHAUSTED": (
        (
            "AI xizmati so‘rovlar limitiga yetdi. Hozir javobni bazadan tekshira olmadim. "
            "Birozdan so‘ng qayta urinib ko‘ring."
        ),
        (
            "AI хизмати сўровлар лимитига етди. Ҳозир жавобни базадан текшира олмадим. "
            "Бироздан сўнг қайта уриниб кўринг."
        ),
        (
            "Достигнут лимит AI-сервиса. Сейчас не удалось проверить ответ по базе. "
            "Повторите попытку позже."
        ),
    ),
    "GEMINI_UNAVAILABLE": (
        "AI xizmati vaqtincha mavjud emas. Javobni bazadan tekshira olmadim. Qayta urinib ko‘ring.",
        "AI хизмати вақтинча мавжуд эмас. Жавобни базадан текшира олмадим. Қайта уриниб кўринг.",
        "AI-сервис временно недоступен. Не удалось проверить ответ по базе. Повторите попытку.",
    ),
    "GEMINI_TIMEOUT": (
        (
            "AI xizmati belgilangan vaqtda javob bermadi. Tasdiqlanmagan ma’lumot bera "
            "olmayman. Qayta urinib ko‘ring."
        ),
        (
            "AI хизмати белгиланган вақтда жавоб бермади. Тасдиқланмаган маълумот бера "
            "олмайман. Қайта уриниб кўринг."
        ),
        (
            "AI-сервис не ответил вовремя. Не могу сообщить неподтверждённые данные. "
            "Повторите попытку."
        ),
    ),
    "MODEL_JSON_INVALID": (
        (
            "AI so‘rovni to‘g‘ri shakllantira olmadi. Tasdiqlanmagan javob bera olmayman. "
            "Savolni aniqroq yozing yoki qayta urinib ko‘ring."
        ),
        (
            "AI сўровни тўғри шакллантира олмади. Тасдиқланмаган жавоб бера олмайман. "
            "Саволни аниқроқ ёзинг ёки қайта уриниб кўринг."
        ),
        (
            "AI-сервис не сформировал корректный запрос. Не могу дать неподтверждённый "
            "ответ. Уточните вопрос или повторите попытку."
        ),
    ),
    "GEMINI_CONFIGURATION": (
        "AI xizmati sozlamalari sababli so‘rov bajarilmadi. Javobni bazadan tekshira olmadim.",
        "AI хизмати созламалари сабабли сўров бажарилмади. Жавобни базадан текшира олмадим.",
        "Запрос не выполнен из-за настроек AI-сервиса. Не удалось проверить ответ по базе.",
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
    reason = {
        "MODEL_TIMEOUT": "GEMINI_TIMEOUT",
        "MODEL_UNAVAILABLE": "GEMINI_UNAVAILABLE",
        "MODEL_TRANSPORT_ERROR": "GEMINI_UNAVAILABLE",
        "GEMINI_TRANSPORT": "GEMINI_UNAVAILABLE",
        "GEMINI_AUTHENTICATION": "GEMINI_CONFIGURATION",
        "GEMINI_MODEL_NOT_FOUND": "GEMINI_CONFIGURATION",
        "GEMINI_NOT_CONFIGURED": "GEMINI_CONFIGURATION",
    }.get(reason, reason)
    if reason in INFRASTRUCTURE:
        return GENERIC["ERROR"][index] + " " + INFRASTRUCTURE[reason][index]
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

    async def understand(self, question, *, request_id=None):
        start = time.perf_counter()
        request_id = request_id or correlation_id()
        stage = "language_detector"
        stage_start = start
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
        diagnostic(stage, None, "SUCCESS", stage_start, request_id)
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
            stage, stage_start = "prompt_builder", time.perf_counter()
            system, contents, context = await asyncio.to_thread(
                self.prompts.build, question, hint, reference
            )
            diagnostic(stage, None, "SUCCESS", stage_start, request_id)
            stage, stage_start = "gemini_client", time.perf_counter()
            raw, calls, model_ms = await self.planner.generate(system, contents)
            diagnostic(stage, None, "SUCCESS", stage_start, request_id)
            self.metrics.model_calls += calls
            self.metrics.model_responses += 1
            self.metrics.model_ms.append(model_ms)
            stage, stage_start = "json_validation", time.perf_counter()
            try:
                decision = SemanticDecision.model_validate_json(raw)
            except (ValidationError, ValueError, TypeError) as exc:
                diagnostic(stage, type(exc).__name__, "MODEL_JSON_INVALID", stage_start, request_id)
                self.metrics.json_validation_failures += 1
                return output("ERROR", "MODEL_JSON_INVALID")
            diagnostic(stage, None, "SUCCESS", stage_start, request_id)
            if not hint.language or decision.language == "unsupported":
                language = decision.language
            stage, stage_start = "semantic_guard", time.perf_counter()
            plan = check_decision(question, hint, decision, context, self.engine, reference)
            diagnostic(stage, None, "SUCCESS", stage_start, request_id)
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
            diagnostic(stage, type(exc).__name__, exc.reason, stage_start, request_id)
            self.metrics.guard_rejections += 1
            return output(exc.status, exc.reason)
        except PlannerFailure as exc:
            diagnostic(stage, exc.exception_class, exc.category, stage_start, request_id)
            calls = exc.calls
            model_ms = exc.latency_ms
            self.metrics.model_calls += calls
            result = output("ERROR", exc.reason)
            return result.model_copy(update={"answer": notice(language, "ERROR", exc.category)})
        except TimeoutError as exc:
            diagnostic(stage, type(exc).__name__, "SEMANTIC_CAPACITY", stage_start, request_id)
            return output("ERROR", "SEMANTIC_CAPACITY")
        except Exception as exc:
            diagnostic(stage, type(exc).__name__, "SEMANTIC_INTERNAL", stage_start, request_id)
            return output("ERROR", "SEMANTIC_INTERNAL")
        finally:
            if acquired:
                self._slots.release()

    async def answer(self, question):
        start = time.perf_counter()
        request_id = correlation_id()
        semantic = await self.understand(question, request_id=request_id)
        if semantic.status != "VERIFIED":
            return semantic
        stage, stage_start = "query_execution", time.perf_counter()
        try:
            verified = await asyncio.to_thread(self.engine.execute, semantic.plan)
            diagnostic(stage, None, verified.reason or verified.status, stage_start, request_id)
            stage, stage_start = "answer_formatter", time.perf_counter()
            internal_language = LANGUAGE_MAP[semantic.language]
            answer = format_answer(verified, internal_language)
            diagnostic(stage, None, "SUCCESS", stage_start, request_id)
        except Exception as exc:
            diagnostic(stage, type(exc).__name__, "INTERNAL_FAILURE", stage_start, request_id)
            return semantic.model_copy(
                update={
                    "status": "ERROR",
                    "reason": "INTERNAL_FAILURE",
                    "plan": None,
                    "answer": notice(semantic.language, "ERROR", "INTERNAL_FAILURE"),
                    "end_to_end_ms": (time.perf_counter() - start) * 1000,
                }
            )
        return semantic.model_copy(
            update={
                "status": verified.status,
                "reason": verified.reason,
                "verified_result": verified,
                "answer": answer,
                "end_to_end_ms": (time.perf_counter() - start) * 1000,
            }
        )
