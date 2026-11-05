"""One reused official async Gemini client; bounded inference, no payload logging."""

import asyncio
import time
from collections import Counter

from google import genai
from google.genai import errors, types

from app.agent.wire_schema import response_schema

# Explicitly reviewed profile. No fallback, 'latest' alias, tools or model auto-routing.
MODEL_PROFILES = {
    "gemini-3.8-flash": types.ThinkingConfig(thinking_level="LOW"),
    "gemini-3.5-flash-lite": types.ThinkingConfig(thinking_level="LOW"),
}


class PlannerFailure(RuntimeError):
    def __init__(self, reason, calls=0, latency_ms=None):
        self.reason, self.calls, self.latency_ms = reason, calls, latency_ms
        super().__init__(reason)


class GeminiPlanner:
    def __init__(self, settings):
        if not settings.gemini_api_key or not settings.gemini_model:
            raise PlannerFailure("GEMINI_NOT_CONFIGURED")
        if settings.gemini_model not in MODEL_PROFILES:
            raise PlannerFailure("UNREVIEWED_MODEL")
        self.model = settings.gemini_model
        self.timeout = settings.gemini_timeout_seconds
        self._slots = asyncio.Semaphore(settings.max_concurrent_queries)
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(self.timeout * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._aio = self._client.aio
        self._ready = False
        self._startup_lock = asyncio.Lock()
        self._closed = False
        self.api_error_counts = Counter()

    async def startup(self):
        """Verify the configured model for this account once, never choose a substitute."""
        async with self._startup_lock:
            if self._ready:
                return
            try:
                async with asyncio.timeout(self.timeout):
                    metadata = await self._aio.models.get(model=self.model)
                if metadata.name not in (self.model, "models/" + self.model):
                    raise PlannerFailure("MODEL_ID_MISMATCH")
                if (
                    metadata.supported_actions
                    and "generateContent" not in metadata.supported_actions
                ):
                    raise PlannerFailure("MODEL_UNSUPPORTED")
            except PlannerFailure:
                raise
            except Exception:
                raise PlannerFailure("MODEL_UNAVAILABLE") from None
            self._ready = True

    async def generate(self, system_instruction, contents):
        if self._closed:
            raise PlannerFailure("CLIENT_CLOSED")
        await self.startup()
        calls = 0
        start = time.perf_counter()
        try:
            async with asyncio.timeout(1):
                await self._slots.acquire()
        except TimeoutError:
            raise PlannerFailure("MODEL_CAPACITY") from None
        try:
            async with asyncio.timeout(self.timeout):
                for attempt in range(2):
                    calls += 1
                    try:
                        response = await self._aio.models.generate_content(
                            model=self.model,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                temperature=0,
                                max_output_tokens=2048,
                                response_mime_type="application/json",
                                response_json_schema=response_schema(),
                                candidate_count=1,
                                thinking_config=MODEL_PROFILES[self.model],
                                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                                    disable=True
                                ),
                            ),
                        )
                        candidates = response.candidates or []
                        if not candidates or str(candidates[0].finish_reason) not in (
                            "FinishReason.STOP",
                            "STOP",
                        ):
                            raise PlannerFailure("MODEL_INCOMPLETE", calls)
                        parts = candidates[0].content.parts if candidates[0].content else []
                        text = "".join(p.text for p in (parts or []) if p.text and not p.thought)
                        if not text or len(text.encode()) > 16384:
                            raise PlannerFailure("MODEL_RESPONSE_SIZE", calls)
                        return text, calls, (time.perf_counter() - start) * 1000
                    except errors.APIError as exc:
                        self.api_error_counts[exc.code] += 1
                        # Only one transient retry, inside the same absolute deadline.
                        if attempt == 0 and exc.code in (429, 500, 502, 503, 504):
                            await asyncio.sleep(1.0)
                            continue
                        raise PlannerFailure("MODEL_API_ERROR", calls) from None
        except TimeoutError:
            raise PlannerFailure(
                "MODEL_TIMEOUT", calls, (time.perf_counter() - start) * 1000
            ) from None
        except PlannerFailure:
            raise
        except Exception:
            raise PlannerFailure("MODEL_TRANSPORT_ERROR", calls) from None
        finally:
            self._slots.release()

    async def aclose(self):
        if not self._closed:
            self._closed = True
            await self._aio.aclose()
            self._client.close()
