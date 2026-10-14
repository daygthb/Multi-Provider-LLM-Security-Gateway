# Verification record

## Portfolio presentation verification

The README was shortened for SWE/AI-infrastructure portfolio review, while its complete technical content was preserved in [reference.md](reference.md). [demo.md](demo.md) provides a two-minute walkthrough and startup/troubleshooting instructions; [career.md](career.md) provides accurate résumé templates, architecture questions and explicit AI-assistance/model-training limitations. Repository visibility remains private; no public hosting or paid service was added.

The documented existing-stack startup succeeded. Its HTTP smoke passed JSON 200, SSE 200, policy 403, missing bearer 401 and metrics 200. The PowerShell walkthrough was executed against the running Compose API: the allowed request returned `Mock response: Hello [REDACTED:email]`, without the supplied synthetic email, and the rule-triggering request returned 403. The draft's 32-token limit clipped the mock's displayed marker; the example was corrected to 64 and rechecked before delivery. Real Redis atomic budget/refund/rate/revocation checks passed again, and actual local `qwen2.5-coder:7b` gateway calls returned JSON 200/SSE 200.

The independent Python/browser smoke also passed with sanitized audit output. Browser plugin was not available, so existing Playwright 1.63/Edge were used: page identity and meaningful content, authenticated Refresh metrics interaction, populated provider health and metrics, no app console errors, and no horizontal overflow at 1280x900 and 390x844. Actual desktop/mobile screenshots were visually inspected. Portfolio assets contain a real dashboard screenshot with the key input cleared and a short silent dashboard clip (not a full narrated API demo); no prompt bodies or raw bearer values are shown. No new browser dependency or application behavior was introduced. The Compose stack is left running for the user to present.

## Local operations rehearsal

`python -m scripts.verify_operations` passed against independent Redis 7.4 containers/volumes. A blank target rejected the generated key before transfer. A completed RDB snapshot was copied to a different volume and the original fixture source container/volume was removed before restore. The replacement key's identity, model/permission scope and 100-token tenant budget survived; the old key remained revoked. Consumed 40 plus pending 20 tokens restored as 60, so a 41-token request was rejected. Finalizing the known pending reservation at 10 twice left 50 consumed, not 40. AOF was bootstrapped from that restored dataset, rewrite completion was checked, and the target was recreated with AOF enabled; identity/revocation and 50 tokens persisted and a 51-token request was rejected.

Through an in-process ASGI HTTP client, the actual gateway used this real Redis fixture: pause produced readiness/chat 503; unpause recovered both to 200. Simulated upstream HTTP 503 opened the circuit, and a healthy completion after the actual cooldown returned 200 and reset failures. Returned errors did not include the test bearer or private upstream detail. This did not deploy a new gateway process/network, call a real upstream provider, or verify production TLS/failover.

A separate fault-injection run deliberately skipped snapshot copying. Restore then failed with invalid_api_key as expected, rather than reporting success. Docker inventory after both runs showed no remaining operations fixture containers or volumes. All bearer values stayed in memory and no backup/key file was written into Git or the host workspace. The running demo was not paused or modified. These results are point-in-time local evidence, not a production RPO/RTO or security approval. [Operations and recovery](operations.md) includes the required post-snapshot usage/revocation reconciliation gate.

The preceding CI-hardening commit `2c52185` also passed [hosted run 38488951801](https://github.com/daygthb/Multi-Provider-LLM-Security-Gateway/actions/runs/38488951801) in 1m53s with zero check annotations, resolving its earlier pending status below. Hosted execution of the new operations stage will be recorded by its own Actions run.

## Repository rename, CI maintenance and bounded local load check

The private repository is now [daygthb/Multi-Provider-LLM-Security-Gateway](https://github.com/daygthb/Multi-Provider-LLM-Security-Gateway), matching the requested project name with URL-safe hyphens. The local `origin` remote was updated and privacy verified. Existing Compose project/volume names and Kubernetes resources were deliberately not renamed, preserving local data and running services.

CI now pins [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) and [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0) to the full commit SHAs verified through GitHub's official tag API. Both official action manifests use Node24. Checkout persistence is disabled, the runner is fixed to `ubuntu-24.04`, and the job has a 15-minute bound. This addresses the runtime/image migration warnings from the first runs below; hosted verification of the updated workflow is required before claiming it passes. Local actionlint and the full `make verify` gate passed after these configuration changes: 48 tests, 94.42% coverage, clean lint/format/mypy, dependency audit and manifests.

A one-off bounded load check used the already-running single Compose API instance, its real Redis (`appendfsync=always`) and mock upstream. The client ran inside the API container against loopback HTTP, with five warmup requests and three bursts of 200 authenticated JSON requests using `max_tokens=32`, a small benign prompt, connection reuse, and concurrency 1, 4 and 16. A random model-restricted tenant/key had deliberately high test quotas; every request returned HTTP200 with nonempty completion content. No paid endpoint was called.

- Concurrency 1: 200 requests in 1.306s, observed 153.18 requests/s; latency p50=6.15ms, p95=8.83ms, p99=10.20ms.
- Concurrency 4: 200 requests in 0.810s, observed 246.99 requests/s; latency p50=13.05ms, p95=17.92ms, p99=161.60ms.
- Concurrency 16: 200 requests in 0.462s, observed 432.61 requests/s; latency p50=34.42ms, p95=47.65ms, p99=73.59ms.

These are single short local bursts, not sustained throughput, saturation, WAN/TLS, SSE, long-prompt, real model inference or production measurements. Latency starts after admission to the client concurrency semaphore and excludes its queue wait. Percentiles use nearest rank over each burst. The harness was executed from standard input without creating source/key files; all identity and tenant-hash quota keys belonging to its random temporary tenant were removed, and absence of those quota keys was checked afterward. Existing demo identities and budgets were untouched. Production capacity and SLOs remain unverified.

Verified locally on 2026-10-13 using Windows, PowerShell and Python 3.12.10. The binding scope is the original attachment summarized in `specification.md`; the implementation plan is `superpowers/plans/2026-10-13-gateway.md`.

## Actual results

- `python -m pytest --cov=gateway --cov-report=term-missing -q`: **48 passed**, **94.42% combined statement/branch coverage**, above the configured 85% minimum. No tests skipped.
- `ruff check .`: passed. Latest `ruff format --check .`: 34 files already formatted.
- `mypy gateway`: passed strict typing across 15 source files.
- `python -m pip_audit --skip-editable`: no known vulnerabilities found in installed dependencies, including optional browser tooling. The local editable project is skipped by the dependency scanner and is covered by source review/tests instead.
- `python -m pip check`: no broken requirements.
- `python -m pip wheel --no-deps --wheel-dir <temporary-directory> .`: built `multi_provider_llm_security_gateway-0.1.0-py3-none-any.whl`; archive inspection confirmed HTML/CSS/JavaScript dashboard assets are included.
- `python scripts/verify_manifests.py`: passed; 6 Compose services, 15 Kubernetes documents, 5 Grafana panels. This checks required resources, probes, limits, secret references, localhost ports, policy ConfigMap drift and the CI command contract.
- `kubeconform -strict -summary -ignore-missing-schemas deploy/kubernetes`: **14 valid, 0 invalid, 0 errors, 1 skipped**. The skipped document is Kustomization, which is not a Kubernetes API resource.
- `actionlint .github/workflows/ci.yml`: exit 0.
- Docker Compose CLI v5.6.0 `config --quiet`: exit 0.

Commands used the project virtualenv (`.venv/Scripts/python`, Ruff and mypy). External validator binaries were downloaded to the system temporary directory, not committed.

## Real HTTP and browser evidence

`python scripts/smoke_demo.py --browser --browser-executable <installed Edge executable>` started the real mock and gateway Uvicorn servers on temporary loopback ports. It generated temporary high-entropy credentials, configured an unavailable primary and a healthy fallback, and verified:

- JSON chat: HTTP 200; forwarded email was redacted and absent from the returned response.
- Protected SSE: HTTP 200 with chat completion chunks and `[DONE]`.
- Prompt injection: HTTP 403 before dispatch.
- Missing bearer: HTTP 401.
- Operator metrics: HTTP 200.
- Content-free audit: email and generated bearer values absent; correlation/audit events and fallback provider present.
- Dashboard: correct page identity, meaningful content, authenticated Refresh metrics interaction populated counts and provider health; rate rejection counters appear even at zero.
- Headless Edge viewports: **1280×900 and 390×844**, no application console errors, no horizontal overflow. Screenshots saved under the system temporary directory `gateway-dashboard-qa/` and visually inspected. Playwright was used because the Browser plugin/skill was not available.

All subprocesses owned by the smoke test are stopped. A transient Windows log-handle cleanup failure found during browser verification was addressed with bounded cleanup retries; the complete browser/HTTP command subsequently exited successfully.

## Requirement-by-requirement evidence

1. **Gateway and adapters:** `app.py`, `models.py`, `providers.py`, `routing.py` and `mock.py` implement the endpoint and provider protocols. `test_providers.py` covers OpenAI JSON/SSE, Ollama JSON/NDJSON translation, missing usage, invalid responses, retries/fallback/cost selection. `test_mock.py` exercises the actual deterministic mock application through the adapter. The real HTTP smoke covers gateway-to-mock networking and selection after primary health failure.

2. **Authentication and authorization:** `auth.py` provides SQLite demo identities; `redis_auth.py` shares production identities across replicas. Keys are generated with 256 random bits; only SHA-256 hashes are stored and hashes are compared with `hmac.compare_digest`. Parameterized identity tests exercise both stores, hashes, tenant budgets, wrong/revoked keys and missing tenants. `test_app.py` verifies permissions, exact model restrictions, operator isolation and revocation. `test_cli.py` verifies tenant management, creation, listing without bearer values, revocation, safe seeding and server selection of the requested SQLite path.

3. **Distributed rate limits and budgets:** `quota.py` uses Redis Lua to atomically reserve key RPM/TPM and shared tenant monthly usage. Tenant hash tags co-locate quota keys. Redis server time and month-boundary guards prevent a stale month observation from charging the wrong month. `test_quota.py` executes the Lua using fakeredis/lupa, tests concurrent reservations across keys, separate tenants, RPM/TPM rejection, idempotent refunds, refill, month rollover and fail-closed network errors. HTTP tests verify rate headers/429 errors. Integration regressions verify zero-dispatch refunds, charges only for dispatched failed attempts, and conservative accounting on deadlines.

4. **Request policy and PII:** versioned `config/policy.yaml` drives all pattern rules/actions/scores. `policy.py` scans plaintext and a decoding layer. `test_auth_policy.py` covers injection, jailbreaks, extraction, role markers, encodings, risk bounds, allow/warn/block/redact, invalid config and all four required PII classes. API tests prove redacted text reaches the upstream. Regression tests cover mixed direct/encoded PII, candidates beyond the original decoding limit and unsafe cross-message redaction failing closed. The README explicitly states that heuristic detection does not guarantee security.

5. **Response protection:** response rules cover private keys, provider/access/gateway bearer tokens, secret assignments and blocked phrases. Tests cover blocking and configurable redaction; integration regressions prove response redaction in both JSON and SSE, including a match split across upstream chunks. Full bounded buffering occurs before any content is released. Compressed upstream responses are rejected before body consumption to prevent decompression bypass of the byte cap. Audit tests and real smoke logs omit bodies and credentials.

6. **Reliability and errors:** settings bound overall/upstream deadlines, attempts, exponential backoff, sizes and concurrency. Periodic health checks, per-process circuits, half-open recovery and provider fallback are implemented in `routing.py`. Tests verify retries, timeout sanitization, unavailable/oversized/malformed responses, circuit opening/recovery, readiness after cooldown, and that exhausted cost limits cannot mutate an undispatched provider's circuit. Every HTTP request gets a new correlation ID; middleware and handlers provide sanitized error envelopes, including validation and total deadlines.

7. **Auditing and observability:** `observability.py` explicitly allowlists SIEM JSON fields: timestamp, correlation, tenant/model/provider, latency, tokens/charges/cost, policy rules/action and risk/status. Body content and exception strings are omitted. Prometheus exports requests, policy blocks, quota rejections, provider attempt latency, fallback and estimated cost. Tests inspect logs, metric output and protected operator APIs; live browser checks verify the content-free dashboard. Grafana datasource/panels and authenticated Prometheus scrape configuration are versioned under `deploy/`.

8. **Deployment:** the multistage Dockerfile builds an installed runtime package and runs as UID 10001. Compose configures API, persistent no-eviction Redis, mock, one-time seed, Prometheus and Grafana. Prometheus and the container smoke run use the credential-owning UID; keys remain mode 0600 on Linux. Kubernetes includes ConfigMaps, external Secret references, liveness/readiness/startup probes, resource requests/limits, HPA, PDB, persisted Redis and default-deny network policies. Schema, workflow and Compose configuration checks pass; runtime limits are stated below.

9. **Engineering and tests:** typed module boundaries, Pydantic settings/schema validation, dependency injection, strict mypy/Ruff/pytest configuration, constraints and Make targets are present. GitHub Actions includes lint/format/type/test/coverage/dependency audit, semantic/schema checks, Docker image build and a real Compose smoke stage. The 48-test suite covers every specifically requested test category; coverage is 94.42%.

10. **Documentation and demo:** README includes architecture/Mermaid, threat model, settings/provider/policy reference, reproducible Windows and POSIX setup/curl examples, key lifecycle, tests, Compose/Kubernetes instructions and limitations. The generated seed is usable without paid credentials and refuses overwriting existing private key files. The network smoke proves the local demo works. Repository source inspection found only policy regexes, placeholder environment references and deterministic synthetic test values; no real credentials. Source was committed and published to the private GitHub repository; generated keys, databases and environment files remain excluded.

## Review and remaining runtime boundaries

An independent read-only whole-project review covered source, tests, configuration, dashboard, deployment, CI and documentation. Its concrete findings were addressed and regression-tested: encoded leaks, gateway key detection, circuit readiness, failure accounting, decompression bounds, cost-exhausted circuit mutation, cross-message redaction and Linux seed ownership. The minor ignored server database option was also corrected. There are no known unresolved findings from that review.

Initial verification preceded installation/activation of local services. At that point Docker/kubectl were absent from the session PATH, the Docker engine pipe was missing and WSL enumeration failed. The follow-up below supersedes those runtime limitations; it uses discovered per-user executable paths and the now-running services.

**Still not verified:** paid OpenAI calls, production Redis failover/disk-loss recovery, application-throughput capacity, production ingress/TLS, or every NetworkPolicy rule/destination. The SIGKILL recovery and bounded synthetic CPU scaling checks below are narrower than those production guarantees. No throughput, production latency, scalability, high-availability or adversarial-security guarantees were measured or claimed.

Intentional tradeoffs remain documented: buffered SSE latency, conservative token/cost reservations, one decoding layer, heuristic false positives/negatives, trusted reviewed regexes, per-process circuits/metrics, explicit volatile demo quotas, and a reference single-instance Redis deployment requiring environment-specific operational hardening.

## Live-service follow-up after installations

The user requested checking the installed tools and continuing runtime verification. Installed and responding tools were discovered outside this session's stale PATH:

- Docker Desktop **4.95.0**, Docker Engine **29.8.2**, Compose **5.6.0**, Linux engine context `desktop-linux`.
- kubectl **1.36.1**, Docker Desktop Kubernetes **1.36.1**, local context `docker-desktop` after the user enabled Kubernetes.
- Ollama **0.40.3** with the downloaded **qwen2.5-coder:7b** model.
- WSL **3.0.3.0**, Linux kernel **6.18.54.1-1**.
- GNU Make **3.81**. `make lint typecheck test` actually ran successfully using the project virtualenv: **48 passed, 94.42% coverage**, Ruff formatting/lint clean and strict mypy clean.

`scripts/activate-tools.ps1` refreshes only the current process PATH, including per-user tool locations and GNU Make. No persistent system PATH changes were made.

### Docker, Redis, monitoring and Ollama

`docker compose -p llm-security-gateway build` successfully built the non-root multistage API, mock and seed images on Linux. The Compose project now defaults to this name to avoid differing project names between examples. Redis/mock were started and became healthy, the one-time seed generated private ignored key files, and API/Prometheus/Grafana started successfully. All five services remain running on localhost/internal networks.

The container smoke command returned JSON=200, SSE=200, policy block=403, missing bearer=401 and operator metrics=200. `scripts/verify_live_backends.py` executed the actual Lua/identity code against **Redis 7.4**: concurrent tenant reservations admitted two/rejected two, shared monthly budget rejection worked, repeated refunds were idempotent, RPM/TPM limits rejected correctly and revoked identities were rejected. The test used a random isolated tenant and removed only its exact generated Redis keys. CI now also runs this real Redis check after Compose startup.

Redis reports `appendonly=yes`, `appendfsync=always`, `maxmemory-policy=noeviction`. After a graceful Compose Redis restart, the API smoke still authenticated with the original generated keys and passed. This verifies retained identity state across that restart, not hard-crash durability or failover.

Prometheus `/api/v1/targets` returned HTTP 200 with the gateway target **up** and no scrape error. Grafana `/api/health` returned HTTP 200 and database **ok**.

The optional `docker-compose.ollama.yml` plus `config/providers-ollama.yaml` adds the installed local model without changing default mock routes. Host-to-Ollama adapter checks passed JSON and streaming (35 prompt tokens/3 completion tokens in those specific requests). Container-to-host Ollama `/api/tags` returned HTTP 200. Most importantly, **requests through the running authenticated gateway** for `qwen2.5-coder:7b` returned JSON=200 and SSE=200. The live script created `data/ollama.key` without printing the bearer value and successfully reused it after the Redis restart. This key is model-restricted; the existing mock demo key cannot use the Ollama model.

### Kubernetes

Server-side dry-run of `deploy/kubernetes` succeeded against the local cluster. The gateway image was tagged `llm-gateway:0.1.0`; random Redis credentials were generated and applied directly to a Kubernetes Secret without writing them into repository manifests or tool output. The actual resources were applied in namespace `llm-gateway`.

Observed rollout state:

- Gateway deployment **2/2 ready**, mock deployment **1/1 ready**, Redis StatefulSet **1/1 ready**.
- Redis PVC **Bound**, 1Gi, ReadWriteOnce, `standard` StorageClass.
- The API initially restarted while its Redis dependency was being provisioned, then became ready; subsequent observations remained ready.
- Through a temporary loopback port-forward, the Kubernetes deployment's own generated credentials passed JSON=200, SSE=200, policy=403, missing bearer=401, metrics=200. Compose and Kubernetes use separate Redis instances and separate credential files.
- An unapproved temporary pod could not establish a TCP connection to the Redis Service IP (3-second timeout). The gateway pod could connect to the same IP. This is concrete allow/deny evidence for that network path, not a test of every policy rule. The probe pods and temporary allow policy were removed; the four authored policies remain.

With explicit user approval, **Metrics Server v0.9.0** was installed as a cluster-wide add-on. Its first scrape failed because the local kind node's certificate had no IP SAN. The development-only patch `deploy/local/metrics-server-kind-patch.json` added `--kubelet-insecure-tls`; it is excluded from production manifests. Afterward Metrics Server rolled out, `kubectl top nodes` returned CPU/memory readings, and the gateway HPA reported a real **0%/70% CPU target with 2 replicas**, replacing the previous unknown metrics. The later bounded scaling exercise is recorded below. [Metrics Server requirements](https://github.com/kubernetes-sigs/metrics-server#requirements) describe the kubelet certificate prerequisite.

The Compose stack, Kubernetes namespace and approved Metrics Server installation are left available for the user. Only temporary verification processes/resources are cleaned up. Real generated key files are under Git-ignored `data/`; `git check-ignore` confirmed all five demo/operator/Ollama/Kubernetes key paths are ignored. Source is now committed and published privately; credentials remain uncommitted and unpublished.

## Linux checks, isolated crash recovery and scaling exercise

Publication preparation reran the full Windows `make verify` and Linux `make linux-verify` gates: both passed all 48 tests at 94.42% coverage, lint/format, strict typing, dependency audit and manifest checks. Linux real HTTP smoke also passed. An intermittent Windows test-only race was reproduced: a 20ms request deadline sometimes expired before dispatch. The test now reschedules the real middleware timeout at the provider-dispatch boundary, retaining cancellation, quota and audit assertions without a host-speed assumption. No production gateway code changed for this correction.

After the user signed in through official GitHub CLI 2.102.0, private repository [daygthb/llm-security-gateway](https://github.com/daygthb/llm-security-gateway) was created and source commit `0f315025be62bf3c03314748bacac76c51b4a002` was pushed to default branch `main`. Repository privacy and remote commit were verified. No cloud account, public domain or paid OpenAI credential has been configured. Local Kubernetes remains development/staging, not a production hosting claim.

The [first hosted GitHub Actions run](https://github.com/daygthb/llm-security-gateway/actions/runs/38485047467) completed successfully in 1m28s on 2026-10-13. Its actual logs show 48 tests passed with 94.42% coverage, clean Ruff/mypy, no known dependency vulnerabilities, semantic/schema validation, Docker image build, Compose HTTP smoke, real Redis quota/refund/revocation checks and isolated SIGKILL recovery. Recovery retained the identity and 40 consumed tokens and rejected an over-budget request; generated test resources were removed. All job steps, including Compose cleanup, succeeded. Non-blocking runner annotations warn that checkout@v4/setup-python@v5 target deprecated Node20 and are forced onto Node24, and that ubuntu-latest will migrate to Ubuntu26. These warnings did not fail this run and remain maintenance follow-ups, not evidence of compatibility with every future runner image.

`make linux-verify` passed inside the built non-root Linux API image with the current source mounted read-only. Python **3.12.15** ran the same 48 tests with **94.42%** combined coverage, strict mypy across 15 files, Ruff lint/format, dependency audit, manifest contract checks and the real HTTP mock demo. Audit reported no known vulnerabilities in published dependencies; the unpublished project distribution was explicitly skipped by PyPI audit and remains covered by source review and tests. Linux-only uvloop **0.23.0** is now pinned in the constraints, matching the verified image.

The Linux runner uses temporary package/cache locations instead of writing into the source or runtime environment. Its audit cache initially tried the non-existent unprivileged home directory; an explicit `/tmp/gateway-audit` cache fixed that harness assumption, and the complete Make target then exited 0. This was a verification-tool filesystem issue, not a gateway execution failure.

`make recovery-test` passed against a separate Redis container and newly generated volume. The check created an identity, reserved 60 tokens, finalized consumption at **40**, killed that test Redis with **SIGKILL**, restarted it with AOF, authenticated the original in-memory bearer, observed **40** consumed tokens still stored, and rejected a request reserving 61 more against the 100-token budget. Docker changed its random host port on restart; diagnostics confirmed that endpoint change, and the harness now rediscovers it rather than polling a stale port. The test container/volume were removed, confirmed by Docker inventory. The application's Redis was not stopped by this test. CI now includes this isolated recovery check.

The provisioned Grafana dashboard API returned HTTP 200, title **LLM Security Gateway**, and **5 panels**. Its Prometheus datasource proxy returned HTTP 200 with a successful query and populated request-counter series; this supplements the earlier health/scrape checks.

A **60-second synthetic CPU loop** in one gateway pod caused actual HPA rescale events from **2 to 4 to 5** replicas. Five gateway pods became ready and CPU readings dropped after the bounded process exited. No HPA settings were patched to force scaling. The controller then reported `ScaleDownStabilized` while preserving its normal safety window. Afterward, actual rescale events recorded **5 to 4 to 2**, the deployment returned to its two-replica baseline and rollout checks passed. The [Kubernetes HPA API reference](https://kubernetes.io/docs/reference/kubernetes-api/autoscaling/horizontal-pod-autoscaler-v2/) documents the default 300-second downscale stabilization. This is a scaling-control exercise, not a request-throughput benchmark.
