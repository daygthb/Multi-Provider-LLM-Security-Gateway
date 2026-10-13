# Binding project specification

The source is the user-provided attachment `C:\Users\hrida\.codex\attachments\5450ffc0-6690-41b2-ad27-7eabf8c83985\pasted-text-1.txt`, read in full on 2026-10-13.

Build a production-quality FastAPI reverse proxy with one OpenAI-compatible POST `/v1/chat/completions` API, JSON and SSE, OpenAI/Ollama/deterministic mock adapters, routing by model, health, cost and fallback priority. Authenticate high-entropy Bearer keys using only stored SHA-256 hashes and safe comparisons. Associate keys with tenant, models, permissions, RPM/TPM and monthly tenant budgets; provide creation and revocation CLI.

Use Redis token buckets and monthly token consumption, standard rate headers and useful JSON errors. Score risk 0–100 using configurable YAML rules for prompt injection, jailbreaks, prompt extraction, encoded payloads and role manipulation. Detect and optionally redact email, phone, credit card and SSN. Support allow/redact/warn/block. Protect responses against secret/private key/token/blocked phrase leakage. Never claim heuristics guarantee security; omit or hash sensitive content in logs.

Implement bounded retries/backoff/timeouts, health checks, circuits and fallback, correlation IDs and consistent errors. SIEM JSON audit fields include timestamp, correlation ID, tenant, model, provider, latency, usage, decisions and risk. Prometheus covers request/blocked volume, provider latency, rate rejection, fallback and estimated cost. Provide a content-free operator dashboard.

Ship multistage Docker and Compose API/Redis/mock/Prometheus/Grafana, Kubernetes ConfigMaps/Secret references/probes/resources/HPA/NetworkPolicy, no real credentials. Typed Python/Pydantic settings/dependency injection/modules, tests for auth/isolation/quota/policies/PII/SSE/circuits/audit/fallback, >=85% coverage, Ruff/mypy/pytest and CI lint/type/test/dependency-scan/image-build, developer commands. Detailed README with Mermaid architecture, threat model, setup/curl/config/test/deployment/limitations and seeded credential-free demo.

Implement incrementally and verify fully. Local mock demo and all core functions must work; tests/lint/types pass. Compose must start if Docker is available. Validate Kubernetes and CI where local tooling permits. Record actual test results and unavailable tools without invented performance/deployment/security claims.
