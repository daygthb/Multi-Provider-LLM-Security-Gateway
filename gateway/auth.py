import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import aiosqlite

from gateway.errors import GatewayError
from gateway.models import KeyIdentity


class IdentityStore(Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    async def put_tenant(self, tenant: str, budget: int) -> None: ...
    async def create(
        self,
        tenant: str,
        models: list[str],
        permissions: list[str],
        rpm: int,
        tpm: int,
        max_cost: float = 1,
    ) -> tuple[str, KeyIdentity]: ...
    async def authenticate(self, raw: str) -> KeyIdentity: ...
    async def revoke(self, key_id: str) -> None: ...
    async def list_keys(self) -> list[dict[str, object]]: ...


class KeyStore:
    def __init__(self, path: str) -> None:
        self.path = path

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tenants (
                  id TEXT PRIMARY KEY, monthly_budget INTEGER NOT NULL CHECK(monthly_budget > 0));
                CREATE TABLE IF NOT EXISTS api_keys (
                  id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE,
                  tenant TEXT NOT NULL REFERENCES tenants(id), models TEXT NOT NULL,
                  permissions TEXT NOT NULL, rpm INTEGER NOT NULL, tpm INTEGER NOT NULL,
                  max_cost REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            """)
            await db.commit()

    async def put_tenant(self, tenant: str, budget: int) -> None:
        if not tenant or budget <= 0:
            raise ValueError("tenant and positive budget required")
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO tenants VALUES (?, ?) ON CONFLICT(id) "
                "DO UPDATE SET monthly_budget=excluded.monthly_budget",
                (tenant, budget),
            )
            await db.commit()

    async def create(
        self,
        tenant: str,
        models: list[str],
        permissions: list[str],
        rpm: int,
        tpm: int,
        max_cost: float = 1,
    ) -> tuple[str, KeyIdentity]:
        raw = "gw_" + secrets.token_urlsafe(32)
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT monthly_budget FROM tenants WHERE id=?", (tenant,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise ValueError("tenant does not exist")
            identity = KeyIdentity(
                id=uuid4().hex,
                tenant=tenant,
                allowed_models=models,
                permissions=permissions,
                rpm=rpm,
                tpm=tpm,
                monthly_budget=row[0],
                max_cost=max_cost,
            )
            await db.execute(
                "INSERT INTO api_keys VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    identity.id,
                    hashlib.sha256(raw.encode()).hexdigest(),
                    tenant,
                    json.dumps(models),
                    json.dumps(permissions),
                    rpm,
                    tpm,
                    max_cost,
                ),
            )
            await db.commit()
        return raw, identity

    async def authenticate(self, raw: str) -> KeyIdentity:
        digest = hashlib.sha256(raw.encode()).hexdigest()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT k.*, t.monthly_budget FROM api_keys k JOIN tenants t ON k.tenant=t.id "
                "WHERE digest=? AND revoked=0",
                (digest,),
            ) as cur:
                row = await cur.fetchone()
        if row is None or not hmac.compare_digest(row["digest"], digest):
            raise GatewayError(
                401, "invalid_api_key", "Invalid or revoked API key", {"WWW-Authenticate": "Bearer"}
            )
        return KeyIdentity(
            id=row["id"],
            tenant=row["tenant"],
            allowed_models=json.loads(row["models"]),
            permissions=json.loads(row["permissions"]),
            rpm=row["rpm"],
            tpm=row["tpm"],
            monthly_budget=row["monthly_budget"],
            max_cost=row["max_cost"],
        )

    async def revoke(self, key_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (key_id,))
            if cur.rowcount == 0:
                raise ValueError("key not found")
            await db.commit()

    async def list_keys(self) -> list[dict[str, object]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM api_keys") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def close(self) -> None:
        return None
