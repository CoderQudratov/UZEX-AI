import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors, types

from app.agent.gemini_client import GeminiPlanner, PlannerFailure
from app.core.config import Settings


class FakeModels:
    def __init__(self):
        self.calls = []
        self.gets = 0
        self.responses = []
        self.active = 0
        self.peak = 0
        self.delay = 0

    async def get(self, **kwargs):
        self.gets += 1
        return SimpleNamespace(
            name="models/gemini-3.8-flash", supported_actions=["generateContent"]
        )

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.peak = max(self.active, self.peak)
        try:
            await asyncio.sleep(self.delay)
            item = self.responses.pop(0) if self.responses else response()
            if isinstance(item, Exception):
                raise item
            return item
        finally:
            self.active -= 1


def response(
    text='{"status":"AMBIGUOUS","language":"uz_latn","reason":"METRIC_AMBIGUOUS","plan":null}',
    finish="STOP",
):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=finish, content=types.Content(parts=[types.Part(text=text)])
            )
        ]
    )


@pytest.fixture
def sdk(monkeypatch):
    models = FakeModels()
    closed = []

    async def aclose():
        closed.append("async")

    def close():
        closed.append("sync")

    instance = SimpleNamespace(aio=SimpleNamespace(models=models, aclose=aclose), close=close)
    created = []

    def create(**kwargs):
        created.append(kwargs)
        return instance

    monkeypatch.setattr("app.agent.gemini_client.genai.Client", create)
    return models, closed, created


def configured(**kwargs):
    return Settings(gemini_api_key="fixture-private-key", gemini_model="gemini-3.8-flash", **kwargs)


@pytest.mark.anyio
async def test_official_sdk_configuration_reuse_and_no_fallback(sdk):
    models, closed, created = sdk
    planner = GeminiPlanner(configured())
    for _ in range(2):
        text, calls, latency = await planner.generate("system", "untrusted-question")
        assert calls == 1 and latency >= 0
    assert len(created) == 1 and models.gets == 1 and len(models.calls) == 2
    options = created[0]["http_options"]
    assert options.timeout == 20000 and options.retry_options.attempts == 1
    config = models.calls[0]["config"]
    assert config.temperature == 0 and config.max_output_tokens == 2048
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["additionalProperties"] is False
    assert config.tools is None and config.automatic_function_calling.disable is True
    assert all(call["model"] == "gemini-3.8-flash" for call in models.calls)
    await planner.aclose()
    await planner.aclose()
    assert closed == ["async", "sync"]


@pytest.mark.anyio
async def test_bounded_retry_and_safe_api_error(sdk):
    models, _, _ = sdk
    models.responses = [
        errors.ServerError(503, {"error": {"message": "private-payload"}}),
        response(),
    ]
    planner = GeminiPlanner(configured())
    _, calls, _ = await planner.generate("system", "question")
    assert calls == 2 and len(models.calls) == 2
    models.responses = [errors.ClientError(400, {"error": {"message": "private-secret"}})]
    with pytest.raises(PlannerFailure) as caught:
        await planner.generate("system", "question")
    assert str(caught.value) == "MODEL_API_ERROR" and caught.value.calls == 1
    assert "private" not in str(caught.value)
    await planner.aclose()


@pytest.mark.anyio
async def test_deadline_concurrency_and_capacity_release(sdk):
    models, _, _ = sdk
    planner = GeminiPlanner(configured(max_concurrent_queries=2))
    models.delay = 0.01
    await asyncio.gather(*(planner.generate("system", "question") for _ in range(6)))
    assert models.peak <= 2
    planner.timeout = 0.01
    models.delay = 0.2
    with pytest.raises(PlannerFailure, match="MODEL_TIMEOUT"):
        await planner.generate("system", "question")
    models.delay = 0
    assert (await planner.generate("system", "question"))[1] == 1
    await planner.aclose()


@pytest.mark.anyio
async def test_incomplete_and_oversize_responses_are_not_repaired(sdk):
    models, _, _ = sdk
    planner = GeminiPlanner(configured())
    for item, reason in [
        (response(finish="MAX_TOKENS"), "MODEL_INCOMPLETE"),
        (response("x" * 16385), "MODEL_RESPONSE_SIZE"),
    ]:
        models.responses = [item]
        with pytest.raises(PlannerFailure, match=reason):
            await planner.generate("system", "question")
    assert len(models.calls) == 2
    await planner.aclose()


def test_missing_key_and_unreviewed_model_never_fall_back(sdk):
    with pytest.raises(PlannerFailure, match="GEMINI_NOT_CONFIGURED"):
        GeminiPlanner(Settings())
    with pytest.raises(PlannerFailure, match="UNREVIEWED_MODEL"):
        GeminiPlanner(
            Settings(gemini_api_key="fixture-private-key", gemini_model="gemini-untested-flash")
        )
    assert not sdk[2]


@pytest.mark.anyio
async def test_actual_official_sdk_serializes_structured_requests_without_network(monkeypatch):
    import json

    import httpx
    from google import genai

    requests = []
    decision = '{"status":"AMBIGUOUS","language":"uz_latn","reason":"METRIC_AMBIGUOUS","plan":null}'

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "name": "models/gemini-3.8-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
            )
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["temperature"] == 0
        assert body["generationConfig"]["maxOutputTokens"] == 2048
        assert body["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
        assert body["contents"][0]["parts"][0]["text"] == "untrusted-fixture-question"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": decision}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    real_client = genai.Client

    def client(**kwargs):
        kwargs["http_options"] = kwargs["http_options"].model_copy(
            update={"httpx_async_client": async_client}
        )
        return real_client(**kwargs)

    monkeypatch.setattr("app.agent.gemini_client.genai.Client", client)
    planner = GeminiPlanner(configured())
    raw, calls, _ = await planner.generate("fixed-system", "untrusted-fixture-question")
    assert raw == decision and calls == 1 and len(requests) == 2
    await planner.aclose()
