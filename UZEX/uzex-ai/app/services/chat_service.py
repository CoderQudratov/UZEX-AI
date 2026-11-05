"""Request orchestration and response formatting for the Chat API.

Connects the semantic router, deterministic query engine, and in-memory cache.
"""

import asyncio
import time
from typing import Any

from app.agent.semantic_models import SemanticResult
from app.agent.semantic_router import SemanticRouter
from app.services.cache import ChatCache
from app.services.chat_models import ChatEvidence, ChatResponse


def parse_language_script(sem_lang: str) -> tuple[str, str]:
    if sem_lang == "uz_latn":
        return "uz", "latin"
    if sem_lang == "uz_cyrl":
        return "uz", "cyrillic"
    if sem_lang == "ru":
        return "ru", "cyrillic"
    return "unsupported", "unknown"


def serialize_filter_value(val: Any) -> Any:
    if isinstance(val, (int, float, bool)):
        return val
    return str(val)


class ChatService:
    """Orchestrates request validation, cache lookups, semantic routing, and evidence formatting."""

    def __init__(
        self,
        router: SemanticRouter,
        *,
        max_concurrency: int = 4,
        cache_size: int = 0,
        dataset_version: str | None = None,
    ) -> None:
        self.router = router
        resolved_version = (
            dataset_version
            or (
                getattr(getattr(router, "engine", None), "source", None)
                and getattr(router.engine.source, "version", None)
            )
            or "v1"
        )
        self.cache = ChatCache(maxsize=cache_size, dataset_version=str(resolved_version))
        self.semaphore = asyncio.Semaphore(max_concurrency)

    def _to_response(self, result: SemanticResult, start_time: float) -> ChatResponse:
        elapsed = round((time.perf_counter() - start_time) * 1000, 2)
        lang, script = parse_language_script(result.language)

        evidence: ChatEvidence | None = None
        if result.verified_result and result.verified_result.evidence:
            ev = result.verified_result.evidence
            raw_filters = result.verified_result.filters or ()
            filters_data = [
                {
                    "field": f.field,
                    "op": f.op,
                    "values": [serialize_filter_value(v) for v in f.values],
                }
                for f in raw_filters
            ]
            source_count = (
                ev.matched_transactions
                if ev.matched_transactions is not None
                else result.verified_result.row_count
            )
            evidence = ChatEvidence(
                dataset_version=ev.dataset_version,
                tables=list(ev.tables),
                filters=filters_data,
                source_count=source_count,
            )

        answer = result.answer.strip()
        if not answer:
            if result.status == "VERIFIED":
                answer = "Tasdiqlangan natija" if lang == "uz" else "Подтверждённый результат"
            else:
                answer = (
                    "So‘rovni bajarib bo‘lmadi." if lang == "uz" else "Не удалось выполнить запрос."
                )

        return ChatResponse(
            status=result.status,
            language=lang,  # type: ignore[arg-type]
            script=script,  # type: ignore[arg-type]
            answer=answer,
            evidence=evidence,
            latency_ms=elapsed,
        )

    async def chat(self, message: str) -> ChatResponse:
        start_time = time.perf_counter()

        # Step 1: Validate request length and content
        if not isinstance(message, str) or not message.strip():
            return ChatResponse(
                status="AMBIGUOUS",
                language="uz",
                script="latin",
                answer="So‘rovni aniqlashtiring.",
                evidence=None,
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )

        if len(message.encode("utf-8")) > 4096:
            return ChatResponse(
                status="UNSUPPORTED",
                language="unsupported",
                script="unknown",
                answer="Bu so‘rov qo‘llab-quvvatlanmaydi.",
                evidence=None,
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )

        # Step 2: Check RAM-only cache
        cached = await self.cache.get(message)
        if cached is not None:
            return cached.model_copy(
                update={"latency_ms": round((time.perf_counter() - start_time) * 1000, 2)}
            )

        # Step 3: Route, plan, and execute via SemanticRouter
        async with self.semaphore:
            result = await self.router.answer(message)

        # Step 4: Map to API response
        response = self._to_response(result, start_time)

        # Step 5: Cache deterministic successful responses
        await self.cache.set(message, response)

        return response
