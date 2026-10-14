# Easy demo: run, show, explain

Use this on your configured Windows computer. You do not need paid API keys, a domain or Kubernetes for the presentation.

## 1. Run this one block

Start Docker Desktop and wait until its engine is running. Open PowerShell, then copy and paste:

```powershell
cd 'C:\Projects\Multi Provider LLM Security Gateway'
. .\scripts\activate-tools.ps1
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d --wait
python scripts/smoke_demo.py --existing
```

The last command makes real requests, checks the results and leaves the app running. It reads the local demo keys privately; you do not need to type a key into the terminal.

## 2. Show these results

- **`json: 200`, `sse: 200`:** valid requests worked; the script also verified that the example email was redacted.
- **`policy_block: 403`, `unauthenticated: 401`:** the example attack was blocked and a request without a key was rejected.
- **`metrics: 200`:** an authorized operator could read monitoring data.

Open **[localhost:8000/dashboard](http://localhost:8000/dashboard)**. Copy your operator key without printing it:

```powershell
Get-Content .\data\operator.key -Raw | Set-Clipboard
```

Paste it into **Operator API key** and click **Refresh metrics**. Point out request counts, blocked requests and provider health. Do not show the key file or clipboard in a recording; clear the clipboard afterward. The dashboard is for monitoring, not typing chat prompts.

## 3. Say this in your own words

“This gateway gives an application one API for different LLM providers. It checks API keys and permissions, filters requests and responses, and uses Redis to share rate limits and token budgets. The demo uses a repeatable mock; Ollama can run a real model locally. I also tested failures and recovery and automated checks in GitHub Actions.”

Then explain one tradeoff:

“The gateway scans the whole response before sending SSE chunks. That helps inspect text spanning multiple chunks, but adds latency. Pattern-based filtering is not complete protection against prompt injection.”

Aim for two minutes: **30 seconds explaining the problem, 30 showing the checks, 30 showing the dashboard, 30 explaining a tradeoff.** Describe your own contributions and any AI assistance honestly.

## Optional: show the real AI model

With Ollama running and `qwen2.5-coder:7b` installed:

```powershell
docker compose run --rm --no-deps -v ./scripts:/app/scripts:ro -v ./data:/app/data api python scripts/verify_live_backends.py --ollama
```

This prints real Redis quota/refund/revocation checks and gateway JSON/SSE results from the local model. Warm up the model before presenting; the mock is the dependable default.

## Remember

- This is a **local demo**. Show it on your laptop or screen-share; someone else's computer cannot open your `localhost`.
- If Docker is unavailable, use the [Python-only setup](reference.md#local-setup-python-312). For another computer or first-time Compose setup, use the [technical reference](reference.md#docker-compose).
- If authentication fails, do not delete data or rerun seeding over existing keys. Check the [identity instructions](reference.md#api-and-identity-operations).
- [Silent dashboard preview](assets/dashboard-preview.webm) · [Résumé and interview notes](career.md). The clip shows only the console, not the full narrated demonstration.
