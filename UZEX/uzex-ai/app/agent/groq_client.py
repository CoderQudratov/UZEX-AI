"""Explicit Groq semantic planner. No fallback, tools, factual prose or payload logging."""

import asyncio
import json
import time
from copy import deepcopy

from groq import APIConnectionError, APIStatusError, APITimeoutError, AsyncGroq

from app.agent.gemini_client import PlannerFailure
from app.agent.query_models import QueryPlan
from app.agent.wire_schema import PLAN, response_schema

MODELS = frozenset({"openai/gpt-oss-120b", "openai/gpt-oss-20b"})
WIRE_INSTRUCTION = (
    "\nGroq wire format: EVERY non-null plan MUST include ALL these keys: "
    + ", ".join(PLAN["properties"])
    + ". Never omit lookup, fields or periods. For unused lookup use null; "
    "unused fields, periods, filters, entities, metrics, group_by and order_by MUST be []; "
    "unused money_mode MUST be null. Fields-only-for-records means fields=[] for other kinds. "
    "Periods-only-for-compare means periods=[] for other kinds. "
    "Use limit=20 unless a different valid limit is requested. "
    "A non-PLAN decision has plan=null. All facts still require database execution."
)


def prepare_contents(contents):
    """Expand trusted intent examples into the provider's required full wire shape."""
    try:
        payload = json.loads(contents)
    except (TypeError, ValueError):
        return contents
    if not isinstance(payload, dict):
        return contents
    for example in payload.get("structured_intent_examples", ()):
        decision = example.get("decision", {})
        if decision.get("plan") is not None:
            decision["plan"] = QueryPlan.model_validate_json(
                json.dumps(decision["plan"])
            ).model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def strict_response_schema():
    """Groq strict mode requires every property on every closed object to be required.

    Groq rejects the overlapping object alternatives accepted by Gemini. One closed
    QueryPlan object uses empty arrays/null for unused fields, matching local defaults.
    Full local Pydantic and semantic checks still authorize execution independently.
    """
    schema = response_schema()
    schema["properties"]["plan"] = {"anyOf": [deepcopy(PLAN), {"type": "null"}]}

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["required"] = list(value["properties"])
                value["additionalProperties"] = False
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    return schema


def status_category(code):
    return {
        400: "LLM_INVALID_REQUEST",
        401: "LLM_AUTHENTICATION",
        403: "LLM_AUTHENTICATION",
        404: "LLM_MODEL_NOT_FOUND",
        429: "LLM_QUOTA_EXHAUSTED",
        500: "LLM_UNAVAILABLE",
        502: "LLM_UNAVAILABLE",
        503: "LLM_UNAVAILABLE",
        504: "LLM_TIMEOUT",
    }.get(code, "LLM_API_ERROR")


class GroqPlanner:
    def __init__(self, settings):
        if not settings.groq_api_key or not settings.groq_model:
            raise PlannerFailure("LLM_NOT_CONFIGURED")
        if settings.groq_model not in MODELS:
            raise PlannerFailure("UNREVIEWED_MODEL")
        self.model = settings.groq_model
        self.timeout = settings.gemini_timeout_seconds
        self._slots = asyncio.Semaphore(settings.max_concurrent_queries)
        self._closed = False
        self._client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(),
            base_url="https://api.groq.com",
            timeout=self.timeout,
            max_retries=0,
        )

    async def startup(self):
        if self._closed:
            raise PlannerFailure("CLIENT_CLOSED")

    async def generate(self, system_instruction, contents):
        await self.startup()
        started = time.perf_counter()
        try:
            async with asyncio.timeout(1):
                await self._slots.acquire()
        except TimeoutError:
            raise PlannerFailure("MODEL_CAPACITY") from None
        try:
            async with asyncio.timeout(self.timeout):
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_instruction + WIRE_INSTRUCTION},
                        {"role": "user", "content": prepare_contents(contents)},
                    ],
                    temperature=0,
                    reasoning_effort="low",
                    max_completion_tokens=2048,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "uzex_semantic_decision",
                            "strict": True,
                            "schema": strict_response_schema(),
                        },
                    },
                    stream=False,
                )
            choices = response.choices or []
            if not choices or choices[0].finish_reason != "stop":
                raise PlannerFailure("MODEL_INCOMPLETE", 1)
            message = choices[0].message
            if getattr(message, "tool_calls", None):
                raise PlannerFailure("MODEL_CONTRACT", 1)
            raw = message.content
            if not isinstance(raw, str) or not raw or len(raw.encode()) > 16384:
                raise PlannerFailure("MODEL_RESPONSE_SIZE", 1)
            return raw, 1, (time.perf_counter() - started) * 1000
        except (TimeoutError, APITimeoutError) as exc:
            raise PlannerFailure(
                "MODEL_TIMEOUT",
                1,
                (time.perf_counter() - started) * 1000,
                category="LLM_TIMEOUT",
                exception_class=type(exc).__name__,
            ) from None
        except APIStatusError as exc:
            raise PlannerFailure(
                "MODEL_API_ERROR",
                1,
                (time.perf_counter() - started) * 1000,
                category=status_category(exc.status_code),
                exception_class=type(exc).__name__,
            ) from None
        except APIConnectionError as exc:
            raise PlannerFailure(
                "MODEL_TRANSPORT_ERROR",
                1,
                (time.perf_counter() - started) * 1000,
                category="LLM_UNAVAILABLE",
                exception_class=type(exc).__name__,
            ) from None
        except PlannerFailure:
            raise
        except Exception as exc:
            raise PlannerFailure(
                "MODEL_TRANSPORT_ERROR",
                1,
                (time.perf_counter() - started) * 1000,
                category="LLM_UNAVAILABLE",
                exception_class=type(exc).__name__,
            ) from None
        finally:
            self._slots.release()

    async def aclose(self):
        if not self._closed:
            self._closed = True
            await self._client.close()
