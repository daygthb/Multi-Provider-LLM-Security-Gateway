import base64
import time

import httpx
import pytest

from gateway.errors import GatewayError
from gateway.policy import PolicyEngine
from gateway.providers import Provider
from gateway.routing import Router
from gateway.settings import Settings
from tests.test_providers import chat, completion, config
from tests.test_quota import identity


def encoded(text):
    return base64.b64encode(text.encode()).decode()


def test_encoded_pii_still_blocks_with_direct_match():
    result = PolicyEngine("config/policy.yaml").inspect(
        "a@example.com " + encoded("private.person@example.com"), "request"
    )
    assert result.action == "block"


def test_secret_after_many_encoded_candidates_is_blocked():
    prefix = " ".join(encoded("harmless example value " + str(i)) for i in range(16))
    text = prefix + " " + encoded("sk-" + "x" * 30)
    assert PolicyEngine("config/policy.yaml").inspect(text, "response").action == "block"


def test_gateway_bearer_keys_are_response_secrets():
    assert (
        PolicyEngine("config/policy.yaml").inspect("gw_" + "a" * 43, "response").action == "block"
    )


@pytest.mark.asyncio
async def test_readiness_recovers_after_circuit_cooldown():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=completion()))
    ) as client:
        router = Router([config()], client, Settings(circuit_threshold=1, circuit_reset=1))
        router.states["mock"].failures = 1
        router.states["mock"].opened = time.monotonic()
        assert not router.available()
        router.states["mock"].opened -= 2
        assert router.available()
        assert (await router.complete(chat(), identity())).completion.text == "Hello"
        assert router.states["mock"].failures == 0


@pytest.mark.parametrize("failure", ["unhealthy", "upstream", "timeout"])
async def test_failure_quota_finalization_and_sanitized_audit(
    tmp_path, caplog, monkeypatch, failure
):
    import asyncio
    import json
    import logging

    from gateway.app import create_app
    from gateway.auth import KeyStore
    from gateway.quota import MemoryQuota

    store = KeyStore(str(tmp_path / "keys.db"))
    await store.initialize()
    await store.put_tenant("demo", 100000)
    raw, _ = await store.create("demo", ["mock-model"], ["chat"], 60, 10000)
    deadline = None
    if failure == "timeout":
        real_timeout = asyncio.timeout

        def controlled_timeout(delay):
            nonlocal deadline
            deadline = real_timeout(delay)
            return deadline

        # Expire the real middleware deadline only after dispatch. A tiny wall
        # clock deadline can instead cancel request parsing/auth on a busy host.
        monkeypatch.setattr("gateway.middleware.asyncio.timeout", controlled_timeout)
    settings = Settings(environment="test", retries=0, request_timeout=5)
    quota = MemoryQuota()
    calls = []

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(503 if failure == "unhealthy" else 200, json={"data": []})
        calls.append(request)
        if failure == "timeout":
            assert deadline is not None
            deadline.reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()
        return httpx.Response(503, text="sensitive provider error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(settings, store=store, quota=quota, client=upstream, configs=[config()])
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://g"
            ) as client:
                with caplog.at_level(logging.INFO, logger="gateway.audit"):
                    response = await client.post(
                        "/v1/chat/completions",
                        json=chat().model_dump(),
                        headers={"Authorization": "Bearer " + raw},
                    )
                assert response.status_code == (504 if failure == "timeout" else 503)
                assert raw not in caplog.text and "sensitive provider error" not in response.text
                event = json.loads(caplog.records[-1].message)
                expected = (
                    0 if failure == "unhealthy" else chat().prompt_reservation() + chat().max_tokens
                )
                assert event["charged_tokens"] == expected
                assert sum(quota.budgets.values()) == expected
                assert len(calls) == (0 if failure == "unhealthy" else 1)


async def test_undispatched_routing_failure_charges_zero():
    async with httpx.AsyncClient() as client:
        router = Router([config()], client, Settings())
        router.states["mock"].healthy = False
        with pytest.raises(GatewayError) as exc:
            await router.complete(chat(), identity())
        assert getattr(exc.value, "charged_tokens", None) == 0


async def test_failed_routing_charges_only_dispatched_attempts():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as client:
        router = Router(
            [config("a"), config("b", priority=1)], client, Settings(retries=0, backoff=0)
        )
        router.states["b"].healthy = False
        with pytest.raises(GatewayError) as exc:
            await router.complete(chat(), identity())
        assert (
            getattr(exc.value, "charged_tokens", None)
            == chat().prompt_reservation() + chat().max_tokens
        )


async def test_compressed_upstream_response_rejected_before_decoding():
    import gzip

    reads = []

    class CompressedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            reads.append(True)
            yield gzip.compress(b"x" * (4 * 1024 * 1024))

    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=CompressedStream(), headers={"Content-Encoding": "gzip"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GatewayError) as exc:
            await Provider(config(), client, Settings()).complete(chat())
        assert "encoding" in exc.value.message.lower()
        assert reads == []


async def test_cost_exhaustion_does_not_open_undispatched_provider_circuit():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        router = Router(
            [config("first", price=10000), config("second", priority=1, price=10000)],
            client,
            Settings(retries=0, circuit_threshold=1),
        )
        with pytest.raises(GatewayError):
            await router.complete(chat(), identity())
        assert len(calls) == 1
        assert router.states["first"].failures == 1
        assert router.states["second"].failures == 0


async def test_cross_message_redaction_fails_closed_before_forwarding(tmp_path):
    import json

    from gateway.app import create_app
    from gateway.auth import KeyStore
    from gateway.quota import MemoryQuota

    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n  - id: confidential\n    direction: request\n"
        "    pattern: 'confidential\\s+phrase'\n    score: 30\n    action: redact\n"
        "  - id: greeting\n    direction: response\n    pattern: Hello\n"
        "    score: 10\n    action: redact\n",
        encoding="utf-8",
    )
    store = KeyStore(str(tmp_path / "keys.db"))
    await store.initialize()
    await store.put_tenant("demo", 100000)
    raw, _ = await store.create("demo", ["mock-model"], ["chat"], 60, 10000)
    calls = []

    def handler(request):
        if request.method == "POST":
            calls.append(request)
            if json.loads(request.content)["stream"]:
                return httpx.Response(
                    200,
                    content='data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
                    'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
                    "data: [DONE]\n\n",
                )
            return httpx.Response(200, json=completion())
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(
            Settings(environment="test", policy_file=str(policy)),
            store=store,
            quota=MemoryQuota(),
            client=upstream,
            configs=[config()],
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://g"
            ) as client:
                response = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer " + raw},
                    json={
                        "model": "mock-model",
                        "messages": [
                            {"role": "user", "content": "confidential"},
                            {"role": "user", "content": "phrase"},
                        ],
                    },
                )
                assert response.status_code == 403
                assert calls == []
                for stream in (False, True):
                    response = await client.post(
                        "/v1/chat/completions",
                        json=chat(stream).model_dump(),
                        headers={"Authorization": "Bearer " + raw},
                    )
                    assert response.status_code == 200
                    assert "[REDACTED:greeting]" in response.text
                    assert "Hello" not in response.text
