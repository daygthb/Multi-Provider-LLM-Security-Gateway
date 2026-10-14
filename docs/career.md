# Résumé and interview notes

## Positioning

**Multi Provider LLM Security Gateway — Python, FastAPI, Redis, Docker, Kubernetes**

For general SWE internships, lead with API design, shared state, testing and reliability. For AI/ML internships, describe inference integration and LLM application infrastructure. This project does not train or fine-tune a model.

The bullets below are templates, not proof of personal authorship. Use only claims you can explain and demonstrate. Adapt them to what you actually specified, implemented, reviewed, tested or changed. Be honest about AI-assisted work; do not claim independent implementation, production users, measured business impact or model accuracy that you do not have.

## General SWE résumé version

- Built a typed FastAPI gateway with API-key authentication, tenant/model permissions, configurable request/response policies and provider fallback.
- Enforced shared rate limits and tenant token budgets using atomic Redis Lua scripts; verified key revocation, idempotent accounting and backup/restore behavior.
- Validated the service with 48 tests and 94% combined statement/branch coverage; automated lint, typing, dependency audits and Docker integration checks in GitHub Actions.

## AI-infrastructure résumé version

- Integrated local Ollama inference and an OpenAI-compatible chat API behind a common gateway supporting JSON and SSE responses.
- Added configurable PII redaction and request/response filtering, with content-free audit logs and explicit limitations of pattern-based detection.
- Containerized the API, Redis, mock provider and monitoring stack; verified local Kubernetes deployment, provider recovery and quota persistence.

Use two or three bullets, not both full versions. Link the repository only if the recipient can access it. It is currently private; making it public requires a deliberate visibility change after a privacy review. An ordinary résumé link does not grant access.

## Thirty-second introduction

“This is a backend gateway for LLM applications. It gives clients one chat API while enforcing authentication, model permissions, security rules and shared usage budgets. I can demonstrate it without paid APIs using a deterministic mock, or run real inference through local Ollama. The interesting engineering parts are atomic Redis accounting, safe failure handling and the latency tradeoff of scanning a complete response before streaming it.”

Adjust “I built” or descriptions of ownership to match your actual work. Prepare one concrete example of a decision you made and one change you can implement yourself.

## Questions to prepare

**What happens to a request?** Authentication and model/permission checks, request policy, quota reservation, provider routing, response scan, quota finalization and sanitized audit. Trace [app.py](../gateway/app.py).

**Why Redis instead of a Python dictionary?** Multiple API replicas need one shared budget and rate-limit state. Lua keeps the admission changes atomic. The explicit memory demo is single-process and loses quotas on restart. Read [quota.py](../gateway/quota.py).

**How do you avoid overspending during retries?** Reserve conservatively for possible attempts, then refund known unused capacity. Ambiguous failures retain a maximum charge. This favors budget safety over precise utilization; it is not authoritative provider billing.

**Why buffer SSE?** A secret may span multiple chunks. Scan the complete bounded response before sending it. The tradeoff is memory and time-to-first-token, so do not call this live token streaming. Read [providers.py](../gateway/providers.py).

**How do fallback and circuit breakers differ?** Fallback tries another eligible provider; an open circuit temporarily avoids a repeatedly failing provider. A probe after cooldown can restore it. Read [routing.py](../gateway/routing.py).

**Why hash API keys?** These are randomly generated, high-entropy tokens, not user passwords. The store keeps SHA-256 digests rather than raw bearer values; authentication uses safe comparisons. Keys have scoped permissions and can be revoked. Read [redis_auth.py](../gateway/redis_auth.py).

**Does this stop all prompt injection?** No. Configurable patterns catch some cases and can redact selected PII, but semantic attacks, false positives and missed cases remain. Read the [threat model](reference.md#threat-model-and-limitations).

**What did you actually measure?** Tests/coverage, HTTP outcomes, local Ollama calls and isolated operational checks are documented. Short local mock bursts are not sustained production throughput. Paid OpenAI and public production hosting are unverified. See [evidence](verification.md).

**What would you improve?** Choose one: broader behavioral tests, clearer provider compatibility, policy evaluation on a labeled held-out dataset, or realistic workload measurements. Explain the question, baseline and success criteria before adding technology.

## Before an interview

- Run the [demo](demo.md) yourself, without relying on copied explanations.
- Trace one request through the code and explain one failing test.
- Make a small change yourself, such as adding a policy rule and a regression test.
- Explain your own contributions and AI assistance accurately.
- Keep personal data, credentials and unverified production claims out of the recording and résumé.
