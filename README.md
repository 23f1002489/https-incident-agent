# HTTPS Incident Agent — Phase 1

FastAPI incident intake and SQLite persistence. No external diagnostics or remediation are performed in Phase 1.

## Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs and use POST /incidents with:

```json
{"service":"demo-api","url":"https://example.com/api","symptom":"http_5xx","description":"Demo: 503 Service Unavailable"}
```

Run tests in a separate terminal:

```powershell
python -m pytest -q
```

## Render (future phase)

SQLite on an ephemeral cloud filesystem is **not durable**. Switch to managed PostgreSQL before production deployment. Phase 1 is local-first; it does not execute remediation or collect external telemetry.

## Security

The URL is stored, never fetched in this phase. Before adding network diagnostics, implement target allowlisting and protections against SSRF, including private IP and redirect checks. Add authentication before exposing incident data publicly.


## Phase 3
See [PHASE3.md](PHASE3.md) for AI Pipe configuration, investigation endpoints and tests.


See [PHASE4.md](PHASE4.md) for the approval-gated demo action workflow.


Phase 5: See [PHASE5.md](PHASE5.md) for telemetry and verification endpoints.
