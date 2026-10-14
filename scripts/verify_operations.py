"""Isolated Redis backup/restore, key rotation and gateway outage rehearsals.

Never accepts a live Redis URL, container name or volume as a cleanup target.
Only synthetic identities are used; bearer keys never leave process memory.
"""

import argparse
import asyncio
import json
from uuid import uuid4

import httpx

from gateway.app import create_app
from gateway.errors import GatewayError
from gateway.providers import ProviderConfig
from gateway.quota import RedisQuota
from gateway.redis_auth import RedisKeyStore
from gateway.settings import Settings
from scripts.verify_redis_recovery import command, redis_client, wait_ready


async def rejected(operation, code):
    try:
        await operation
    except GatewayError as error:
        assert error.code == code
    else:
        raise AssertionError(f"expected rejection: {code}")


async def persistence_ready(client, kind):
    async with asyncio.timeout(15):
        while True:
            info = await client.info("persistence")
            if kind == "rdb" and not info["rdb_bgsave_in_progress"]:
                assert info["rdb_last_bgsave_status"] == "ok"
                return
            if (
                kind == "aof"
                and info["aof_enabled"]
                and not info["aof_rewrite_in_progress"]
                and not info["aof_rewrite_scheduled"]
            ):
                assert info["aof_last_bgrewrite_status"] == "ok"
                return
            await asyncio.sleep(0.05)


async def gateway_outages(docker, name, client):
    store = RedisKeyStore(client)
    await store.put_tenant("outage-fixture", 10000)
    raw, _ = await store.create("outage-fixture", ["mock-model"], ["chat"], 1000, 100000)
    failing = False

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if failing:
            return httpx.Response(503, text="private upstream detail")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    config = ProviderConfig(
        name="fixture", kind="mock", base_url="http://fixture", models={"mock-model": "mock"}
    )
    settings = Settings(
        environment="test",
        retries=0,
        circuit_threshold=1,
        circuit_reset=0.2,
        health_interval=300,
        request_timeout=10,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(
            settings, store=store, quota=RedisQuota(client), client=upstream, configs=[config]
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://gateway"
            ) as http:
                body = {
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 8,
                }

                async def chat():
                    response = await http.post(
                        "/v1/chat/completions",
                        headers={"Authorization": "Bearer " + raw},
                        json=body,
                    )
                    assert (
                        raw not in response.text and "private upstream detail" not in response.text
                    )
                    return response

                assert (await chat()).status_code == 200
                await command(docker, "pause", name)
                try:
                    assert (await http.get("/health/ready")).status_code == 503
                    assert (await chat()).status_code == 503
                finally:
                    await command(docker, "unpause", name)
                await wait_ready(client)
                assert (await http.get("/health/ready")).status_code == 200
                assert (await chat()).status_code == 200
                failing = True
                assert (await chat()).status_code == 503
                assert app.state.services.router.states["fixture"].failures == 1
                failing = False
                async with asyncio.timeout(5):
                    # The circuit exposes a clock predicate, not a notification event.
                    while not app.state.services.router.available():  # noqa: ASYNC110
                        await asyncio.sleep(0.02)
                assert (await chat()).status_code == 200
                assert app.state.services.router.states["fixture"].failures == 0
    return {"redis_gateway_outage": "503_then_200", "provider_gateway_outage": "503_then_200"}


async def verify(docker):
    prefix = "llm-gateway-operations-" + uuid4().hex
    source, target, copier = prefix + "-source", prefix + "-target", prefix + "-copy"
    source_volume, target_volume = source + "-data", target + "-data"
    containers, volumes, clients = set(), set(), []

    async def start(name, volume, aof):
        containers.add(name)
        await command(
            docker,
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::6379",
            "--mount",
            f"type=volume,src={volume},dst=/data",
            "redis:7.4-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "yes" if aof else "no",
            "--appendfsync",
            "always",
            "--maxmemory-policy",
            "noeviction",
        )
        ports = json.loads(
            await command(docker, "inspect", "--format", "{{json .NetworkSettings.Ports}}", name)
        )
        connection = redis_client(int(ports["6379/tcp"][0]["HostPort"]))
        clients.append(connection)
        await wait_ready(connection)
        return connection

    try:
        for volume in (source_volume, target_volume):
            await command(docker, "volume", "create", volume)
            volumes.add(volume)
        client = await start(source, source_volume, True)
        store, quota = RedisKeyStore(client), RedisQuota(client)
        await store.put_tenant("restore-fixture", 100)
        old_raw, old = await store.create("restore-fixture", ["mock-model"], ["chat"], 1000, 10000)
        charged = await quota.reserve(old, 60)
        await quota.finalize(charged, 40)
        new_raw, new = await store.create("restore-fixture", ["mock-model"], ["chat"], 1000, 10000)
        assert (await store.authenticate(old_raw)).id == old.id
        assert (await store.authenticate(new_raw)).id == new.id
        await store.revoke(old.id)
        await rejected(store.authenticate(old_raw), "invalid_api_key")
        pending = await quota.reserve(new, 20)
        budget_path = quota.names(new, pending.month, pending.id)[1]
        assert int(await client.get(budget_path)) == 60

        # Negative control: the unrelated blank target cannot authenticate this key.
        blank = await start(target, target_volume, False)
        assert await blank.dbsize() == 0
        await rejected(RedisKeyStore(blank).authenticate(new_raw), "invalid_api_key")
        await blank.aclose()
        await command(docker, "rm", "--force", target)
        await client.bgsave()
        await persistence_ready(client, "rdb")
        containers.add(copier)
        await command(
            docker,
            "run",
            "--rm",
            "--name",
            copier,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "redis",
            "--mount",
            f"type=volume,src={source_volume},dst=/backup,readonly",
            "--mount",
            f"type=volume,src={target_volume},dst=/data",
            "redis:7.4-alpine",
            "sh",
            "-c",
            "umask 077; cp /backup/dump.rdb /data/dump.rdb",
        )
        # Destroy only our fixture's source, proving restore no longer depends on it.
        await client.aclose()
        await command(docker, "rm", "--force", source)
        await command(docker, "volume", "rm", source_volume)
        volumes.remove(source_volume)
        restored = await start(target, target_volume, False)
        store, quota = RedisKeyStore(restored), RedisQuota(restored)
        restored_key = await store.authenticate(new_raw)
        assert restored_key.id == new.id
        assert restored_key.monthly_budget == 100
        assert restored_key.allowed_models == ["mock-model"]
        assert restored_key.permissions == ["chat"]
        await rejected(store.authenticate(old_raw), "invalid_api_key")
        assert int(await restored.get(budget_path)) == 60
        await rejected(quota.reserve(restored_key, 41), "budget_exceeded")
        await quota.finalize(pending, 10)
        await quota.finalize(pending, 10)
        assert int(await restored.get(budget_path)) == 50

        # Bootstrap AOF from the restored dataset before enabling it on startup.
        await restored.config_set("appendonly", "yes")
        await persistence_ready(restored, "aof")
        await restored.aclose()
        await command(docker, "stop", "--time", "5", target)
        await command(docker, "rm", target)
        restored = await start(target, target_volume, True)
        store, quota = RedisKeyStore(restored), RedisQuota(restored)
        restored_key = await store.authenticate(new_raw)
        assert restored_key.id == new.id and restored_key.monthly_budget == 100
        await rejected(store.authenticate(old_raw), "invalid_api_key")
        assert int(await restored.get(budget_path)) == 50
        await rejected(quota.reserve(restored_key, 51), "budget_exceeded")
        outcomes = await gateway_outages(docker, target, restored)
        return {
            "redis_snapshot_restore": "passed",
            "blank_target_rejected_key": True,
            "source_volume_removed_before_restore": True,
            "rotation_and_revocation": "passed",
            "restored_consumed_and_pending_tokens": 60,
            "idempotent_pending_finalize_tokens": 50,
            "restored_aof_restart": "passed",
            **outcomes,
            "isolated_resources": "removed after verification",
        }
    finally:
        errors = []
        for connection in clients:
            try:
                await connection.aclose()
            except Exception as error:
                errors.append(error)
        for name in containers:
            try:
                found = await command(
                    docker, "ps", "-a", "--format", "{{.Names}}", "--filter", f"name=^/{name}$"
                )
                if name in found.splitlines():
                    await command(docker, "rm", "--force", name)
            except Exception as error:
                errors.append(error)
        for volume in volumes:
            try:
                await command(docker, "volume", "rm", volume)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("isolated operations cleanup failed", errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.docker))))


if __name__ == "__main__":
    main()
