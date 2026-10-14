# Verification notes

These results were recorded locally on October 13, 2026, using Windows, PowerShell and Python 3.12.10. They describe local checks, not production capacity or a security guarantee. Current automated results are available in [GitHub Actions](https://github.com/daygthb/Multi-Provider-LLM-Security-Gateway/actions).

## Automated checks

- 48 Python tests passed with 94.42% combined statement/branch coverage.
- Ruff lint and formatting, strict mypy, dependency checks and manifest validation passed.
- The Python wheel built successfully and included the dashboard assets.
- Docker Compose configuration, Kubernetes schemas and the GitHub Actions workflow passed validation.

Run `make verify` to repeat the main local checks. See the [technical reference](reference.md) for setup and individual commands.

## Local integration checks

- The mock gateway returned JSON and SSE responses, redacted an example email, blocked a policy-matching request and rejected missing credentials.
- Docker Compose and Docker Desktop Kubernetes were exercised locally.
- Ollama with `qwen2.5-coder:7b` returned JSON and SSE responses through the gateway.
- Redis checks covered shared quotas, refunds, key revocation, crash recovery and backup restoration.
- Isolated recovery checks preserved identities, revoked keys, consumed budgets and pending reservations. Redis unavailability returned 503; requests recovered after Redis became available.
- Simulated upstream failures opened a circuit; a successful probe after cooldown restored routing.

Run `python scripts/smoke_demo.py` for the temporary local HTTP check and `make operations-test` for isolated recovery checks. Recovery procedures and their limits are described in [operations.md](operations.md).

## Dashboard checks

Authenticated refresh, provider health, empty/loading/error states and credential reset were checked using Playwright and Edge. Desktop, tablet and mobile layouts were inspected, with no horizontal overflow or app console errors observed. The screenshot and preview clip show the real local dashboard with the API-key field cleared.

## Limitations

Paid OpenAI calls and public production hosting have not been verified. Short local load checks used the mock provider and do not establish sustained throughput. Pattern-based filtering can miss attacks and produce false positives. SSE responses are buffered and scanned before delivery, adding latency.

Production deployment requires environment-specific configuration and further validation. See [production considerations](production-readiness.md).
