import hashlib
import hmac
import json
import secrets
from collections.abc import Awaitable
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from gateway.errors import GatewayError
from gateway.models import KeyIdentity


class RedisKeyStore:
    """Shared identity metadata for production replicas. Redis must persist without eviction."""

    prefix = "gateway:identity:{identity}:"

    def __init__(self, client: Redis) -> None:
        self.client = client

    async def initialize(self) -> None:
        await cast(Awaitable[bool], self.client.ping())

    async def close(self) -> None:
        await self.client.aclose()

    async def put_tenant(self, tenant: str, budget: int) -> None:
        if not tenant or budget <= 0:
            raise ValueError("tenant and positive budget required")
        await self.client.set(self.prefix + "tenant:" + tenant, budget)

    async def create(
        self,
        tenant: str,
        models: list[str],
        permissions: list[str],
        rpm: int,
        tpm: int,
        max_cost: float = 1,
    ) -> tuple[str, KeyIdentity]:
        budget = await self.client.get(self.prefix + "tenant:" + tenant)
        if budget is None:
            raise ValueError("tenant does not exist")
        identity = KeyIdentity(
            id=uuid4().hex,
            tenant=tenant,
            allowed_models=models,
            permissions=permissions,
            rpm=rpm,
            tpm=tpm,
            monthly_budget=int(budget),
            max_cost=max_cost,
        )
        raw = "gw_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        record = {**identity.model_dump(), "digest": digest, "revoked": False}
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.set(self.prefix + "digest:" + digest, json.dumps(record))
            pipe.set(self.prefix + "id:" + identity.id, digest)
            await pipe.execute()
        return raw, identity

    async def authenticate(self, raw: str) -> KeyIdentity:
        digest = hashlib.sha256(raw.encode()).hexdigest()
        data = await self.client.get(self.prefix + "digest:" + digest)
        record: dict[str, Any] = json.loads(data) if data else {}
        if not record or record["revoked"] or not hmac.compare_digest(record["digest"], digest):
            raise GatewayError(
                401, "invalid_api_key", "Invalid or revoked API key", {"WWW-Authenticate": "Bearer"}
            )
        budget = await self.client.get(self.prefix + "tenant:" + record["tenant"])
        if budget is None:
            raise GatewayError(401, "invalid_api_key", "Tenant no longer exists")
        record["monthly_budget"] = int(budget)
        return KeyIdentity.model_validate(record)

    async def revoke(self, key_id: str) -> None:
        digest = await self.client.get(self.prefix + "id:" + key_id)
        if digest is None:
            raise ValueError("key not found")
        digest_text = digest.decode() if isinstance(digest, bytes) else digest
        path = self.prefix + "digest:" + digest_text
        data = await self.client.get(path)
        if data is None:
            raise ValueError("key not found")
        record = json.loads(data)
        record["revoked"] = True
        await self.client.set(path, json.dumps(record))

    async def list_keys(self) -> list[dict[str, object]]:
        records = []
        async for key in self.client.scan_iter(match=self.prefix + "digest:*"):
            data = await self.client.get(key)
            if data:
                records.append(json.loads(data))
        return records
