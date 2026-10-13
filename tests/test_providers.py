import json

import httpx
import pytest

from gateway.errors import GatewayError
from gateway.models import ChatRequest
from gateway.providers import Provider, ProviderConfig
from gateway.routing import Router
from gateway.settings import Settings
from tests.test_quota import identity


def chat(stream=False):
    return ChatRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Hello"}],
        stream=stream,
        max_tokens=32,
    )


def config(name="mock", kind="mock", priority=0, price=0):
    return ProviderConfig(
        name=name,
        kind=kind,
        base_url="http://mock",
        models={"mock-model": "real"},
        priority=priority,
        input_cost_per_million=price,
        output_cost_per_million=price,
    )


def completion():
    return {
        "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


async def test_openai_json_and_health():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        payload = json.loads(request.content)
        assert payload["model"] == "real"
        return httpx.Response(200, json=completion())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = Provider(config(), client, Settings(environment="test"))
        assert await provider.health()
        assert (await provider.complete(chat())).text == "Hello"


async def test_openai_sse_and_ollama_stream():
    for kind, payload in [
        (
            "openai",
            'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\ndata: [DONE]\n\n',
        ),
        (
            "ollama",
            '{"message":{"content":"Hel"},"done":false}\n'
            '{"message":{"content":"lo"},"done":true,"prompt_eval_count":5,"eval_count":2}\n',
        ),
    ]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r, data=payload: httpx.Response(200, content=data))
        ) as client:
            provider = Provider(config(kind=kind), client, Settings(environment="test"))
            result = await provider.complete(chat(True))
            assert result.text == "Hello"
            assert result.total_tokens == 7


async def test_ollama_json_missing_usage_and_bad_upstream():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"message": {"content": "Hi"}, "done_reason": "stop"}
            )
        )
    ) as client:
        result = await Provider(config(kind="ollama"), client, Settings()).complete(chat())
        assert result.text == "Hi"
        assert result.prompt_tokens == chat().prompt_reservation()
    for payload in ["not json", '{"choices":[]}', '{"error":"secret password=abc123456"}']:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r, data=payload: httpx.Response(200, content=data))
        ) as client:
            with pytest.raises(GatewayError) as error:
                await Provider(config(), client, Settings()).complete(chat())
            assert "password" not in error.value.message


async def test_retry_fallback_circuit_and_cost():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "bad":
            return httpx.Response(503, text="sensitive failure")
        return httpx.Response(200, json=completion())

    settings = Settings(environment="test", retries=1, backoff=0, circuit_threshold=1)
    bad = config("bad").model_copy(update={"base_url": "http://bad"})
    good = config("good", priority=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        router = Router([bad, good], client, settings)
        result = await router.complete(chat(), identity())
        assert result.provider == "good"
        assert result.fallbacks == 1
        assert calls == ["bad", "bad", "mock"]
        await router.complete(chat(), identity())
        assert calls[-1] == "mock"
        assert calls.count("bad") == 2
        assert router.states["bad"].failures == 1
        expensive = Router([config(price=100000)], client, settings)
        with pytest.raises(GatewayError) as error:
            await expensive.complete(chat(), identity())
        assert error.value.code == "no_eligible_provider"


async def test_timeout_and_response_limit():
    def timeout(request):
        raise httpx.ReadTimeout("upstream credential could be in this exception")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(GatewayError):
            await Provider(config(), client, Settings()).complete(chat())
        assert not await Provider(config(), client, Settings()).health()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content="x" * 2000))
    ) as client:
        with pytest.raises(GatewayError):
            await Provider(config(), client, Settings(max_response_bytes=1024)).complete(chat())
