import asyncio
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from gateway.errors import GatewayError
from gateway.models import KeyIdentity
from gateway.quota import MemoryQuota, RedisQuota


def identity(id="key", tenant="alice", rpm=10, tpm=1000, budget=500):
    return KeyIdentity(
        id=id,
        tenant=tenant,
        allowed_models=["mock-model"],
        permissions=["chat"],
        rpm=rpm,
        tpm=tpm,
        monthly_budget=budget,
    )


@pytest.fixture(params=["memory", "redis"])
async def quota(request):
    q = MemoryQuota() if request.param == "memory" else RedisQuota(fakeredis.aioredis.FakeRedis())
    yield q
    await q.close()


async def test_budget_atomic_across_tenant_keys_and_isolated(quota):
    results = await asyncio.gather(
        *[quota.reserve(identity(id=str(i)), 200) for i in range(4)], return_exceptions=True
    )
    assert sum(not isinstance(r, Exception) for r in results) == 2
    assert sum(isinstance(r, GatewayError) for r in results) == 2
    assert (await quota.reserve(identity(tenant="bob"), 200)).reserved == 200


async def test_refund_is_idempotent_and_does_not_refund_rpm(quota):
    key = identity(rpm=2)
    reservation = await quota.reserve(key, 400)
    await quota.finalize(reservation, 10)
    await quota.finalize(reservation, 10)
    await quota.reserve(key, 400)
    with pytest.raises(GatewayError) as error:
        await quota.reserve(key, 1)
    assert error.value.code == "rate_limit_exceeded"
    assert "Retry-After" in error.value.headers


async def test_token_rate_and_budget_rejections(quota):
    with pytest.raises(GatewayError) as error:
        await quota.reserve(identity(tpm=100), 101)
    assert error.value.code == "rate_limit_exceeded"
    with pytest.raises(GatewayError) as error:
        await quota.reserve(identity(budget=50), 100)
    assert error.value.code == "budget_exceeded"
    await quota.ready()


async def test_memory_refill_and_month_rollover():
    now = [datetime(2026, 1, 31, 23, 59, 30, tzinfo=UTC).timestamp()]
    q = MemoryQuota(clock=lambda: now[0])
    key = identity(rpm=1, budget=50)
    await q.reserve(key, 50)
    now[0] += 61
    assert (await q.reserve(key, 50)).reserved == 50


async def test_redis_fails_closed():
    from redis.asyncio import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    q = RedisQuota(
        Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.05, retry=Retry(NoBackoff(), 0))
    )
    with pytest.raises(GatewayError) as error:
        await q.reserve(identity(), 20)
    assert error.value.status == 503
    with pytest.raises(GatewayError):
        await q.ready()
    await q.close()


async def test_redis_month_boundary_uses_server_clock(monkeypatch):
    from unittest.mock import AsyncMock

    client = fakeredis.aioredis.FakeRedis()
    actual = await client.time()
    monkeypatch.setattr(client, "time", AsyncMock(side_effect=[(1, 0), actual]))
    q = RedisQuota(client)
    result = await q.reserve(identity(), 50)
    assert result.month == datetime.fromtimestamp(actual[0], UTC).strftime("%Y-%m")
    await q.finalize(result, 20)
    await q.close()
