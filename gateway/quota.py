import asyncio
import hashlib
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from gateway.errors import GatewayError
from gateway.models import KeyIdentity


def month_window(now: float) -> tuple[str, int]:
    date = datetime.fromtimestamp(now, UTC)
    next_month = datetime(date.year + (date.month == 12), date.month % 12 + 1, 1, tzinfo=UTC)
    return date.strftime("%Y-%m"), int(next_month.timestamp()) + 86400


def rate_headers(key: KeyIdentity, requests: float, tokens: float) -> dict[str, str]:
    return {
        "x-ratelimit-limit-requests": str(key.rpm),
        "x-ratelimit-limit-tokens": str(key.tpm),
        "x-ratelimit-remaining-requests": str(max(0, int(requests))),
        "x-ratelimit-remaining-tokens": str(max(0, int(tokens))),
        "x-ratelimit-reset-requests": f"{math.ceil(60 / key.rpm)}s",
        "x-ratelimit-reset-tokens": f"{math.ceil(60 / key.tpm)}s",
    }


def reject(code: int, headers: dict[str, str], retry: int = 60) -> None:
    if code == 2:
        raise GatewayError(429, "budget_exceeded", "Monthly tenant token budget exceeded", headers)
    raise GatewayError(
        429,
        "rate_limit_exceeded",
        "API key rate limit exceeded",
        {**headers, "Retry-After": str(max(1, retry))},
    )


@dataclass
class Reservation:
    id: str
    key: KeyIdentity
    reserved: int
    month: str
    headers: dict[str, str]


class Quota(Protocol):
    async def reserve(self, key: KeyIdentity, tokens: int) -> Reservation: ...
    async def finalize(self, reservation: Reservation, actual_tokens: int) -> None: ...
    async def ready(self) -> None: ...
    async def close(self) -> None: ...


class MemoryQuota:
    """Single-process demo only; state is lost on restart."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.lock = asyncio.Lock()
        self.buckets: dict[str, tuple[float, float, float]] = {}
        self.budgets: dict[tuple[str, str], int] = {}
        self.pending: dict[str, Reservation] = {}

    async def reserve(self, key: KeyIdentity, tokens: int) -> Reservation:
        if tokens <= 0:
            raise ValueError("positive reservation required")
        async with self.lock:
            now = self.clock()
            month, _ = month_window(now)
            r, t, stamp = self.buckets.get(key.id, (float(key.rpm), float(key.tpm), now))
            elapsed = max(0, now - stamp)
            r, t = (
                min(key.rpm, r + elapsed * key.rpm / 60),
                min(key.tpm, t + elapsed * key.tpm / 60),
            )
            headers = rate_headers(key, r, t)
            if r < 1 or t < tokens:
                reject(
                    1, headers, math.ceil(max((1 - r) * 60 / key.rpm, (tokens - t) * 60 / key.tpm))
                )
            budget_key = (key.tenant, month)
            used = self.budgets.get(budget_key, 0)
            if used + tokens > key.monthly_budget:
                reject(2, headers)
            self.buckets[key.id] = (r - 1, t - tokens, now)
            self.budgets[budget_key] = used + tokens
            reservation = Reservation(
                uuid4().hex, key, tokens, month, rate_headers(key, r - 1, t - tokens)
            )
            self.pending[reservation.id] = reservation
            return reservation

    async def finalize(self, reservation: Reservation, actual_tokens: int) -> None:
        async with self.lock:
            if self.pending.pop(reservation.id, None) is None:
                return
            refund = max(0, reservation.reserved - max(0, actual_tokens))
            budget_key = (reservation.key.tenant, reservation.month)
            self.budgets[budget_key] -= refund
            r, t, stamp = self.buckets[reservation.key.id]
            self.buckets[reservation.key.id] = (r, min(reservation.key.tpm, t + refund), stamp)

    async def ready(self) -> None:
        return None

    async def close(self) -> None:
        return None


RESERVE_LUA = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000
local rpm, tpm, needed, budget, expiry, month_start = unpack(ARGV)
if now >= tonumber(expiry) - 86400 or now < tonumber(month_start) then
  return {3, 0, 0, 0}
end
rpm, tpm, needed, budget = tonumber(rpm), tonumber(tpm), tonumber(needed), tonumber(budget)
local b = redis.call('HMGET', KEYS[1], 'r', 't', 'stamp')
local elapsed = math.max(0, now - tonumber(b[3] or now))
local r = math.min(rpm, tonumber(b[1] or rpm) + elapsed * rpm / 60)
local t = math.min(tpm, tonumber(b[2] or tpm) + elapsed * tpm / 60)
if r < 1 or t < needed then
  local retry = math.ceil(math.max((1-r)*60/rpm, (needed-t)*60/tpm))
  return {1, math.floor(r), math.floor(t), retry}
end
local used = tonumber(redis.call('GET', KEYS[2]) or 0)
if used + needed > budget then return {2, math.floor(r), math.floor(t), 0} end
redis.call('HSET', KEYS[1], 'r', r-1, 't', t-needed, 'stamp', now)
redis.call('EXPIRE', KEYS[1], 120)
redis.call('INCRBY', KEYS[2], needed)
redis.call('EXPIREAT', KEYS[2], expiry)
redis.call('SET', KEYS[3], needed, 'EXAT', expiry)
return {0, math.floor(r-1), math.floor(t-needed), 0}
"""

FINALIZE_LUA = """
local reserved = redis.call('GET', KEYS[3])
if not reserved then return 0 end
local refund = math.max(0, tonumber(reserved) - tonumber(ARGV[1]))
redis.call('DEL', KEYS[3])
if redis.call('EXISTS', KEYS[2]) == 1 then redis.call('DECRBY', KEYS[2], refund) end
if redis.call('EXISTS', KEYS[1]) == 1 then
  local t = tonumber(redis.call('HGET', KEYS[1], 't') or 0)
  redis.call('HSET', KEYS[1], 't', math.min(tonumber(ARGV[2]), t + refund))
end
return refund
"""


class RedisQuota:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def names(self, key: KeyIdentity, month: str, reservation_id: str) -> list[str]:
        # Hash tags co-locate tenant budget and all its key buckets in one cluster slot.
        tag = hashlib.sha256(key.tenant.encode()).hexdigest()
        prefix = f"gateway:{{{tag}}}"
        return [
            f"{prefix}:key:{key.id}",
            f"{prefix}:month:{month}",
            f"{prefix}:reservation:{reservation_id}",
        ]

    async def reserve(self, key: KeyIdentity, tokens: int) -> Reservation:
        if tokens <= 0:
            raise ValueError("positive reservation required")
        try:
            reservation_id = uuid4().hex
            for _ in range(3):
                stamp, micros = await self.client.time()
                month, expiry = month_window(stamp + micros / 1000000)
                current = datetime.fromtimestamp(stamp, UTC)
                month_start = int(datetime(current.year, current.month, 1, tzinfo=UTC).timestamp())
                result = cast(
                    list[Any],
                    await cast(
                        Awaitable[Any],
                        self.client.eval(
                            RESERVE_LUA,
                            3,
                            *self.names(key, month, reservation_id),
                            key.rpm,
                            key.tpm,
                            tokens,
                            key.monthly_budget,
                            expiry,
                            month_start,
                        ),
                    ),
                )
                if result[0] != 3:
                    break
            else:
                raise GatewayError(503, "quota_unavailable", "Quota clock boundary unavailable")
        except RedisError as exc:
            raise GatewayError(503, "quota_unavailable", "Quota service unavailable") from exc
        headers = rate_headers(key, result[1], result[2])
        if result[0] != 0:
            reject(result[0], headers, result[3])
        return Reservation(reservation_id, key, tokens, month, headers)

    async def finalize(self, reservation: Reservation, actual_tokens: int) -> None:
        try:
            await cast(
                Awaitable[Any],
                self.client.eval(
                    FINALIZE_LUA,
                    3,
                    *self.names(reservation.key, reservation.month, reservation.id),
                    max(0, actual_tokens),
                    reservation.key.tpm,
                ),
            )
        except RedisError as exc:
            raise GatewayError(503, "quota_unavailable", "Quota service unavailable") from exc

    async def ready(self) -> None:
        try:
            await cast(Awaitable[bool], self.client.ping())
        except RedisError as exc:
            raise GatewayError(503, "quota_unavailable", "Quota service unavailable") from exc

    async def close(self) -> None:
        await self.client.aclose()
