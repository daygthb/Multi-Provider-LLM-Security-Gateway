import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import uvicorn
from redis.asyncio import Redis

from gateway.auth import IdentityStore, KeyStore
from gateway.redis_auth import RedisKeyStore
from gateway.settings import Settings


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="LLM security gateway operator tools")
    root.add_argument("--database", default=None)
    commands = root.add_subparsers(dest="command", required=True)
    tenant = commands.add_parser("tenant", help="Create/update a tenant budget")
    tenant.add_argument("name")
    tenant.add_argument("--budget", type=int, required=True)
    create = commands.add_parser("create-key", help="Print a new high-entropy key once")
    create.add_argument("tenant")
    create.add_argument("--models", nargs="+", default=["mock-model"])
    create.add_argument("--permissions", nargs="+", choices=["chat", "operator"], default=["chat"])
    create.add_argument("--rpm", type=int, default=60)
    create.add_argument("--tpm", type=int, default=100000)
    create.add_argument("--max-cost", type=float, default=1)
    revoke = commands.add_parser("revoke-key")
    revoke.add_argument("id")
    commands.add_parser("list-keys", help="List key metadata and hashes, never bearer values")
    demo = commands.add_parser(
        "seed-demo", help="Generate demo and operator keys into ignored data/"
    )
    demo.add_argument("--directory", default="data")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--demo", action="store_true", help="Explicit volatile quota mode")
    mock = commands.add_parser("mock")
    mock.add_argument("--host", default="127.0.0.1")
    mock.add_argument("--port", type=int, default=8001)
    return root


async def manage(args: argparse.Namespace, settings: Settings) -> None:
    store: IdentityStore = (
        KeyStore(args.database or settings.database)
        if args.database or settings.identity_backend == "sqlite"
        else RedisKeyStore(
            Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        )
    )
    await store.initialize()
    if args.command == "tenant":
        await store.put_tenant(args.name, args.budget)
    elif args.command == "create-key":
        raw, identity = await store.create(
            args.tenant, args.models, args.permissions, args.rpm, args.tpm, args.max_cost
        )
        print(json.dumps({"api_key": raw, "key_id": identity.id, "tenant": identity.tenant}))
    elif args.command == "revoke-key":
        await store.revoke(args.id)
    elif args.command == "list-keys":
        print(json.dumps(await store.list_keys()))
    elif args.command == "seed-demo":
        directory = Path(args.directory)
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        # Refuse overwriting credentials. Repeated seeds must not silently orphan keys.
        if any((directory / name).exists() for name in ["demo.key", "operator.key"]):
            raise ValueError("demo key files already exist; revoke old keys before reseeding")
        await store.put_tenant("demo", 1000000)
        for filename, models, permissions in [
            ("demo.key", ["mock-model"], ["chat"]),
            ("operator.key", [], ["operator"]),
        ]:
            raw, identity = await store.create("demo", models, permissions, 60, 100000)
            target = directory / filename
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(raw)
            print(json.dumps({"key_id": identity.id, "key_file": str(target)}))
    await store.close()


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "serve" and args.database:
        os.environ["GATEWAY_DATABASE"] = args.database
        os.environ["GATEWAY_IDENTITY_BACKEND"] = "sqlite"
    if args.command == "serve" and args.demo:
        os.environ["GATEWAY_ENVIRONMENT"] = "demo"
        os.environ["GATEWAY_QUOTA_BACKEND"] = "memory"
        os.environ["GATEWAY_IDENTITY_BACKEND"] = "sqlite"
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command in {"serve", "mock"}:
        target = "gateway.app:create_app" if args.command == "serve" else "gateway.mock:app"
        uvicorn.run(
            target,
            factory=args.command == "serve",
            host=args.host,
            port=args.port,
            access_log=False,
            limit_concurrency=128,
        )
    else:
        try:
            asyncio.run(manage(args, settings))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
