# Run locally

Run commands from the repository root. For first-time setup, including Python-only and macOS/Linux options, see the [technical reference](reference.md#local-setup-python-312).

## Start Docker Compose

Start Docker Desktop, then run in PowerShell:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
docker compose build
docker compose up -d --wait redis mock-provider
docker compose --profile setup run --rm seed
docker compose up -d --build --wait
```

The seed command creates local API keys on first setup. If you already have keys, skip it when restarting the stack. On Linux, follow the [Compose setup](reference.md#docker-compose) for data-directory permissions.

The stack includes the gateway, Redis, a mock provider, Prometheus and Grafana. No paid API key is required. With the Python environment from the README installed, check the running app:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_demo.py --existing
```

Expected results:

- `json: 200` and `sse: 200`: chat requests succeeded and the example email was redacted.
- `policy_block: 403`: a request matched a blocking rule.
- `unauthenticated: 401`: a request without a key was rejected.
- `metrics: 200`: an authorized operator could read monitoring data.

## Open the dashboard

Open [localhost:8000/dashboard](http://localhost:8000/dashboard). Copy the generated operator key:

```powershell
Get-Content .\data\operator.key -Raw | Set-Clipboard
```

Paste it into **Operator API key** and click **Refresh metrics**. The dashboard shows request counts, policy blocks and provider health. Chat requests use the API.

Counters reset when the API process restarts. A dash means data has not loaded. Keep the key private and clear your clipboard after use.

[Dashboard preview](assets/dashboard-preview.webm)

## Use Ollama

With Ollama running and `qwen2.5-coder:7b` installed:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d --build --wait
```

Check Redis accounting and JSON/SSE responses from the local model:

```powershell
docker compose run --rm --no-deps -v ./scripts:/app/scripts:ro -v ./data:/app/data api python scripts/verify_live_backends.py --ollama
```

## Troubleshooting

- Localhost addresses work on the computer running the app.
- If Docker is unavailable, use the [Python-only setup](reference.md#local-setup-python-312).
- If authentication fails, check the [identity instructions](reference.md#api-and-identity-operations) before reseeding keys or changing data.
- For configuration and API request examples, see the [technical reference](reference.md).

## Stop the stack

```powershell
docker compose down
```
