# Production readiness

Local Docker/Kubernetes, Ollama and CI checks are recorded in [verification.md](verification.md). Public production hosting has not been verified.

## Remaining release gates

- [ ] Choose a hosting account/region, approved recurring budget, domain and service owner. Do not provision paid infrastructure until these are supplied. Docker Desktop remains development/staging.
- [ ] Configure a production registry and immutable image digest, ingress/controller selectors, trusted HTTPS certificate, DNS and gateway authentication. Keep operator endpoints private. Verify unauthenticated rejection and authorized chat over the real TLS endpoint.
- [ ] Supply provider credentials through a secret manager and test the exact paid model/API parameters, JSON and SSE. Set current model prices, tenant token budgets and per-request cost limits before dispatch. A live provider test requires an explicitly approved spending bound; do not put credentials in chat or Git.
- [ ] Configure restricted provider egress through an approved proxy/destination policy. Exercise allowed and denied paths in the actual production CNI; local path checks are not exhaustive.
- [ ] Replace or operationally harden the reference single-instance Redis. Define backup frequency, encryption, retention, recovery-point/recovery-time objectives and ownership. Prove restore into a separate environment, including identities and consumed budgets. Test the chosen failover/disk-loss scenario; local SIGKILL/AOF recovery is narrower.
- [ ] Run sustained, representative load with real prompt lengths, JSON/SSE mixes, model latency, retries and failures. Agree on latency/error/cost targets first. Short local mock bursts do not establish production capacity.
- [ ] Run independent security evaluation against the intended threat model, including adversarial policy bypasses, tenant isolation, credential leakage and operational access. Regex rules are not a complete security boundary.
- [ ] Configure durable audit/metrics collection, alert thresholds, retention/access controls, incident ownership and key revocation. Test alert delivery without retaining prompt bodies or credentials.
- [ ] Rehearse rollout/rollback, key rotation, backup restoration and provider outage handling, then explicitly approve the release against the evidence.

## No-cost next step

Use the current Kubernetes/Ollama setup for local development. Production deployment needs environment-specific credentials, networking and operational choices. The local Metrics Server TLS-skip patch is only for local development.

## Local operational evidence completed

- [x] Independent snapshot restore after removal of the fixture's original Redis volume, including identity permissions, revoked-key rejection, shared consumed budget and a pending reservation.
- [x] Key replacement/revocation mechanics without resetting the shared tenant budget, and idempotent reservation finalization after restore.
- [x] AOF bootstrap/restart of the restored dataset; gateway503 during a real Redis pause and200 after recovery; simulated upstream outage/circuit recovery.

Run `make operations-test` to repeat these isolated checks. [Operations and recovery](operations.md) documents the method, its limits and the production procedure. These local checks do not close the production backup/failover, incident, rollout or release gates above. In particular, post-snapshot usage and revocations must be reconciled before restored data is allowed to admit traffic.
