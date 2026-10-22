# Phase 3: AI Pipe evidence-based investigations

## Setup (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python -m uvicorn app.main:app --reload
```

Put your AI Pipe token in `.env` as `AI_PIPE_TOKEN=...`. Do not commit `.env` or share the token. AI Pipe endpoint and model can be configured in `.env`. If the provider uses a different endpoint or model ID, update those settings.

Open http://127.0.0.1:8000/docs

1. POST `/incidents` with `{"service":"demo-api","url":"https://example.com/","symptom":"high_latency"}`.
2. POST `/incidents/{incident_id}/diagnose` (requires `ALLOWED_HTTPS_HOSTS=example.com`).
3. POST `/incidents/{incident_id}/investigate` (calls AI Pipe with up to 10 most recent stored diagnostics).
4. GET `/incidents/{incident_id}/investigations` to verify history; restart server and repeat GET to verify SQLite persistence.

Run `python -m pytest -v` for mocked unit tests (no AI Pipe credit spent).

### What is and is not proven

Evidence IDs are validated against stored diagnostics. The model's reasoning is a hypothesis, not a verified root cause. Recommendations never trigger execution. Only successful model responses are stored; provider errors are returned as 502 and are not saved as investigations. The AI Pipe provider receives incident metadata and diagnostic records: do not include secrets or private customer data in incident descriptions.

### Production caveats

Phase 3 remains a local prototype. Before deploying to Render, add authentication, rate limits, a PostgreSQL database, provider endpoint allowlisting, robust output sanitization and provider-error audit records. No remediation permissions are implemented yet.
