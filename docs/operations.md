# Operations and recovery

## Safe local rehearsal

From the source checkout with the virtualenv and Docker active:

```powershell
. .\scripts\activate-tools.ps1
make operations-test
# Equivalent:
python -m scripts.verify_operations
```

This creates random, isolated Redis containers and volumes with loopback-only ports. It does not accept a live Redis URL or a caller-supplied cleanup target. Only synthetic identities are used; raw bearer values remain in memory. No running Compose/Kubernetes service, demo identity, real provider or paid account is targeted. It removes its own test containers, volumes and snapshot afterward, including on a verification failure. A cleanup failure makes the command fail, not report success.

The rehearsal verifies a blank destination rejects the key; then it copies a completed RDB snapshot to a separate volume, removes the fixture source container/volume, and restores into the destination. It checks replacement-key identity/model/permission metadata, the old key's revocation, consumed budget and an outstanding reservation as of the snapshot. A known pending reservation is finalized twice to check idempotency. It then bootstraps AOF from the restored dataset, waits for rewrite completion, and restarts with AOF enabled to verify subsequent accounting survives.

The same fixture exercises the gateway through an in-process ASGI HTTP client with real Redis sockets. Pausing Redis produces readiness/chat503; unpausing restores200. A simulated upstream HTTP503 opens the circuit; a healthy completion after cooldown restores200 and closes it. This is not WAN/TLS, managed-provider, Sentinel/Cluster failover or production rollout evidence. The gateway process and upstream network are not deployed by this fixture. CI runs the command after its Compose/recovery checks.

## Production recovery requirements

The following is an operator checklist, not an automatic production restore command. Apply it only to an approved environment under its incident/change process.

1. Stop admission of new traffic before recovery. Preserve the damaged dataset and relevant content-free audit/billing records; do not overwrite the only surviving copy.
2. Select a trusted, integrity-verified backup and a fresh destination with a compatible Redis version, restricted access, encryption and enough capacity. Verify the destination cannot accidentally serve public traffic or join an existing cluster.
3. Follow the selected Redis distribution's documented restore procedure. For an RDB bootstrap, ensure old AOF files cannot supersede the snapshot; enable AOF only after the intended snapshot is loaded, wait for rewrite completion, and verify restart behavior. Do not toggle persistence on a live production source as a shortcut.
4. Reconcile all post-snapshot usage, tenant changes and revocations from independently durable records before reopening admission. A snapshot can roll budgets and revocations backward. If current key validity cannot be established, keep traffic closed and rotate/reissue affected keys through the secret manager. Retained reservations should remain conservatively charged until actual usage is known; the local harness's known-reservation finalization is not automatic recovery of lost in-flight requests.
5. Verify identities, revoked-key rejection, model/operator permissions, shared budgets, quota rejection, persistence and sanitized outage behavior through the actual gateway. Restore tests must not reset tenant budgets merely to make requests succeed.
6. Check audit/metrics/alerts, record actual restore/data-loss times against agreed RTO/RPO, obtain release approval, and reopen traffic gradually. Keep an explicit rollback destination and incident owner.

Backups require a chosen schedule, off-host storage, encryption/key ownership, integrity checks, retention/deletion policy and regular restoration drills. None of those production services are installed by the local rehearsal. [Redis persistence documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) explains point-in-time RDB snapshots and AOF startup behavior.

## Tenant key rotation

Create a replacement key with the same intended tenant/model/permission scope and deliver it through the approved secret manager. Verify it works before switching the consumer, revoke the old key by its ID, and confirm old-key rejection and new-key success. A key change must not reset the tenant's shared monthly consumption. Record only key IDs and tenant metadata, never bearer values, in tickets or logs. Production rotation additionally needs consumer coordination, credential delivery and rollback ownership; the fixture verifies the identity/quota mechanics only.
