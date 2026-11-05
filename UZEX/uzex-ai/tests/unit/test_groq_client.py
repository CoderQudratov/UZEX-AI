import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from groq import APIStatusError, AsyncGroq
from pydantic import SecretStr

from app.agent.gemini_client import PlannerFailure
from app.agent.groq_client import GroqPlanner, prepare_contents, strict_response_schema
from app.agent.prompt_builder import STRUCTURED_EXAMPLES
from app.agent.query_models import QueryPlan


class Completions:
    def __init__(self):
        self.calls = []
        self.error = None
        self.delay = 0
        self.finish = "stop"

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=self.finish,
                    message=SimpleNamespace(
                        content='{"status":"AMBIGUOUS","language":"uz_latn","reason":"ENTITY_AMBIGUOUS","plan":null}',
                        tool_calls=None,
                    ),
                )
            ]
        )


@pytest.fixture
def sdk(monkeypatch):
    completions = Completions()
    created = []
    closed = []

    async def close():
        closed.append(True)

    def client(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=completions), close=close)

    monkeypatch.setattr("app.agent.groq_client.AsyncGroq", client)
    settings = SimpleNamespace(
        groq_api_key=SecretStr("fixture-key"),
        groq_model="openai/gpt-oss-120b",
        gemini_timeout_seconds=20,
        max_concurrent_queries=2,
    )
    return completions, created, closed, settings


def test_strict_schema_every_object_required_and_closed():
    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert set(value["required"]) == set(value["properties"])
                assert value["additionalProperties"] is False
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(strict_response_schema())


def test_intent_examples_include_all_required_plan_defaults():
    original = json.dumps({"structured_intent_examples": STRUCTURED_EXAMPLES})
    output = json.loads(prepare_contents(original))
    for example in output["structured_intent_examples"]:
        plan = example["decision"]["plan"]
        assert set(plan) == set(QueryPlan.model_fields)
        assert plan["lookup"] is None
        assert plan["fields"] == [] and plan["periods"] == []
        QueryPlan.model_validate_json(json.dumps(plan))


@pytest.mark.anyio
async def test_one_reused_client_strict_no_tools_no_fallback(sdk):
    completions, created, closed, settings = sdk
    planner = GroqPlanner(settings)
    for _ in range(2):
        raw, calls, elapsed = await planner.generate("fixed-system", "untrusted")
        assert calls == 1 and elapsed >= 0 and "AMBIGUOUS" in raw
    assert len(created) == 1 and created[0]["max_retries"] == 0
    assert created[0]["base_url"] == "https://api.groq.com"
    assert len(completions.calls) == 2
    for request in completions.calls:
        assert request["model"] == "openai/gpt-oss-120b"
        assert request["temperature"] == 0
        assert request["response_format"]["json_schema"]["strict"] is True
        assert "tools" not in request
    await planner.aclose()
    await planner.aclose()
    assert len(closed) == 1


@pytest.mark.anyio
async def test_timeout_and_api_fail_closed_without_payload(sdk):
    completions, _, _, settings = sdk
    planner = GroqPlanner(settings)
    planner.timeout = 0.01
    completions.delay = 0.1
    with pytest.raises(PlannerFailure) as timeout:
        await planner.generate("system", "private-question")
    assert timeout.value.category == "LLM_TIMEOUT"
    completions.delay = 0
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
    completions.error = APIStatusError("private-provider-message", response=response, body={})
    with pytest.raises(PlannerFailure) as quota:
        await planner.generate("system", "private-question")
    assert quota.value.category == "LLM_QUOTA_EXHAUSTED"
    assert "private" not in str(quota.value)
    assert len(completions.calls) == 2
    await planner.aclose()


@pytest.mark.anyio
async def test_incomplete_and_unknown_model_rejected(sdk):
    completions, _, _, settings = sdk
    planner = GroqPlanner(settings)
    completions.finish = "length"
    with pytest.raises(PlannerFailure, match="MODEL_INCOMPLETE"):
        await planner.generate("system", "question")
    await planner.aclose()
    settings.groq_model = "unreviewed/model"
    with pytest.raises(PlannerFailure, match="UNREVIEWED_MODEL"):
        GroqPlanner(settings)


@pytest.mark.anyio
async def test_official_sdk_serializes_expected_endpoint_and_strict_schema(monkeypatch):
    captured = []
    raw = '{"status":"AMBIGUOUS","language":"uz_latn","reason":"ENTITY_AMBIGUOUS","plan":null}'

    def handle(request):
        captured.append(request)
        assert request.url.path == "/openai/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["max_completion_tokens"] == 2048
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "created": 0,
                "object": "chat.completion",
                "model": "openai/gpt-oss-120b",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": raw},
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)

    def create(**kwargs):
        return AsyncGroq(**kwargs, http_client=client)

    monkeypatch.setattr("app.agent.groq_client.AsyncGroq", create)
    settings = SimpleNamespace(
        groq_api_key=SecretStr("fixture-key"),
        groq_model="openai/gpt-oss-120b",
        gemini_timeout_seconds=20,
        max_concurrent_queries=2,
    )
    planner = GroqPlanner(settings)
    result, calls, _ = await planner.generate("system", "question")
    assert result == raw and calls == 1 and len(captured) == 1
    await planner.aclose()
