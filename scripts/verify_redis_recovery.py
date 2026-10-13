"""Verify abrupt Redis recovery using an isolated container/volume, never the running stack."""

import argparse
import asyncio
import json
import subprocess
from uuid import uuid4

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from gateway.errors import GatewayError
from gateway.quota import RedisQuota
from gateway.redis_auth import RedisKeyStore


async def command(docker: str, *args: str) -> str:
    result = await asyncio.to_thread(
        subprocess.run, [docker, *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


async def wait_ready(client: Redis) -> None:
    for _ in range(50):
        try:
            await client.ping()
            return
        except RedisError:
            await asyncio.sleep(0.1)
    raise RuntimeError("isolated Redis did not become ready")


def redis_client(port: int) -> Redis:
    return Redis(
        host="127.0.0.1",
        port=port,
        socket_connect_timeout=0.2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
    )


async def verify(docker: str) -> dict[str, object]:
    # Names are generated here and never accepted as caller-supplied cleanup targets.
    name = "llm-gateway-recovery-" + uuid4().hex
    volume_created = False
    container_created = False
    client = None
    try:
        await command(docker, "volume", "create", name)
        volume_created = True
        await command(
            docker,
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::6379",
            "--mount",
            f"type=volume,src={name},dst=/data",
            "redis:7.4-alpine",
            "redis-server",
            "--appendonly",
            "yes",
            "--appendfsync",
            "always",
            "--maxmemory-policy",
            "noeviction",
        )
        container_created = True
        bindings = json.loads(
            await command(docker, "inspect", "--format", "{{json .NetworkSettings.Ports}}", name)
        )
        port = int(bindings["6379/tcp"][0]["HostPort"])
        client = redis_client(port)
        await wait_ready(client)
        store, quota = RedisKeyStore(client), RedisQuota(client)
        await store.put_tenant("recovery-verification", 100)
        raw, key = await store.create("recovery-verification", ["mock-model"], ["chat"], 60, 1000)
        reservation = await quota.reserve(key, 60)
        await quota.finalize(reservation, 40)
        budget_path = quota.names(key, reservation.month, reservation.id)[1]
        assert int(await client.get(budget_path)) == 40
        await command(docker, "kill", "--signal", "KILL", name)
        await command(docker, "start", name)
        restarted_bindings = json.loads(
            await command(docker, "inspect", "--format", "{{json .NetworkSettings.Ports}}", name)
        )
        restarted_port = int(restarted_bindings["6379/tcp"][0]["HostPort"])
        # Docker can assign a different ephemeral host port on container restart.
        # Discover the new transport endpoint; retain the same persisted data.
        await client.aclose()
        client = redis_client(restarted_port)
        store, quota = RedisKeyStore(client), RedisQuota(client)
        await wait_ready(client)
        assert (await store.authenticate(raw)).id == key.id
        assert int(await client.get(budget_path)) == 40
        try:
            await quota.reserve(key, 61)
        except GatewayError as error:
            assert error.code == "budget_exceeded"
        else:
            raise AssertionError("persisted monthly budget was lost")
        return {
            "redis_sigkill_recovery": "passed",
            "identity_recovered": True,
            "monthly_tokens_recovered": 40,
            "over_budget_request": "rejected",
            "host_port_reassigned": restarted_port != port,
            "isolated_resources": "removed after verification",
        }
    finally:
        if client is not None:
            await client.aclose()
        if container_created:
            await command(docker, "rm", "--force", name)
        if volume_created:
            await command(docker, "volume", "rm", name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.docker))))


if __name__ == "__main__":
    main()
