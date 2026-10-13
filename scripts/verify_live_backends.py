"""Opt-in checks against real Redis and optional Ollama routes; never prints bearer keys."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from redis.asyncio import Redis

from gateway.errors import GatewayError
from gateway.quota import RedisQuota, Reservation
from gateway.redis_auth import RedisKeyStore


async def redis_checks(url: str) -> dict[str, object]:
    client = Redis.from_url(url)
    store, quota = RedisKeyStore(client), RedisQuota(client)
    tenant = "verification-" + uuid4().hex
    identities = []
    reservations = []
    cleanup = {store.prefix + "tenant:" + tenant}
    try:
        await store.initialize()
        await store.put_tenant(tenant, 500)
        for rpm, tpm in [(60, 1000), (60, 1000), (1, 1000), (60, 10)]:
            raw, key = await store.create(tenant, ["mock-model"], ["chat"], rpm, tpm)
            identities.append((raw, key))
            cleanup.update(
                [
                    store.prefix + "id:" + key.id,
                    store.prefix + "digest:" + hashlib.sha256(raw.encode()).hexdigest(),
                ]
            )
        results = await asyncio.gather(
            *(quota.reserve(identities[i % 2][1], 200) for i in range(4)), return_exceptions=True
        )
        reservations.extend(result for result in results if isinstance(result, Reservation))
        assert len(reservations) == 2
        assert (
            sum(isinstance(r, GatewayError) and r.code == "budget_exceeded" for r in results) == 2
        )
        for reservation in reservations:
            await quota.finalize(reservation, 20)
            await quota.finalize(reservation, 20)
        admitted = await quota.reserve(identities[0][1], 450)
        reservations.append(admitted)
        try:
            await quota.reserve(identities[1][1], 20)
        except GatewayError as error:
            assert error.code == "budget_exceeded"
        else:
            raise AssertionError("shared monthly budget failed")
        await quota.finalize(admitted, 0)
        limited = await quota.reserve(identities[2][1], 1)
        reservations.append(limited)
        try:
            await quota.reserve(identities[2][1], 1)
        except GatewayError as error:
            assert error.code == "rate_limit_exceeded"
        else:
            raise AssertionError("RPM limit failed")
        try:
            await quota.reserve(identities[3][1], 11)
        except GatewayError as error:
            assert error.code == "rate_limit_exceeded"
        else:
            raise AssertionError("TPM limit failed")
        assert (await store.authenticate(identities[0][0])).tenant == tenant
        await store.revoke(identities[0][1].id)
        try:
            await store.authenticate(identities[0][0])
        except GatewayError as error:
            assert error.status == 401
        else:
            raise AssertionError("revoked identity was accepted")
        return {
            "redis": "passed",
            "concurrent_budget_admitted": 2,
            "concurrent_budget_rejected": 2,
            "refund_idempotency": "passed",
            "rpm_tpm": "passed",
            "revocation": "passed",
        }
    finally:
        for reservation in reservations:
            cleanup.update(quota.names(reservation.key, reservation.month, reservation.id))
        # Only exact keys created for this random verification tenant are removed.
        await client.delete(*cleanup)
        await client.aclose()


async def ollama_checks(url: str, base: str, directory: str, model: str) -> dict[str, object]:
    client = Redis.from_url(url)
    store = RedisKeyStore(client)
    path = Path(directory) / "ollama.key"
    try:
        if path.exists():
            raw = path.read_text("utf-8").strip()
            key = await store.authenticate(raw)
            assert model in key.allowed_models
        else:
            await store.put_tenant("local-ollama-demo", 1000000)
            raw, key = await store.create("local-ollama-demo", [model], ["chat"], 60, 100000)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(raw)
        statuses = []
        async with httpx.AsyncClient(base_url=base, timeout=180) as http:
            for stream in (False, True):
                response = await http.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer " + raw},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "user", "content": "Reply with exactly: gateway ready"}
                        ],
                        "max_tokens": 16,
                        "temperature": 0,
                        "stream": stream,
                    },
                )
                assert response.status_code == 200, response.text
                if stream:
                    assert "data: [DONE]" in response.text
                else:
                    assert response.json()["choices"][0]["message"]["content"]
                statuses.append(response.status_code)
        return {
            "ollama_gateway": "passed",
            "model": model,
            "json_sse_status": statuses,
            "key_file": str(path),
            "key_id": key.id,
        }
    finally:
        await client.aclose()


async def run(args):
    print(json.dumps(await redis_checks(args.redis_url)))
    if args.ollama:
        print(
            json.dumps(
                await ollama_checks(args.redis_url, args.base_url, args.directory, args.model)
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--redis-url", default=os.environ.get("GATEWAY_REDIS_URL", "redis://redis:6379/0")
    )
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--directory", default="data")
    parser.add_argument("--ollama", action="store_true")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
