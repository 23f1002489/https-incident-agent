# Phase 2 — HTTPS diagnostics

Run from the project root on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ALLOWED_HTTPS_HOSTS = 'example.com'
$env:PROBE_TIMEOUT_SECONDS = '5'
python -m pytest -v
python -m uvicorn app.main:app --reload
```

Use http://127.0.0.1:8000/docs to create an incident with `https://example.com/` and symptom `high_latency`. Copy the returned incident ID. Run `POST /incidents/{incident_id}/diagnose`, then `GET /incidents/{incident_id}/diagnostics`.

The probe performs one real GET, with TLS verification, no redirects, no proxy use, port 443 only, exact host allowlisting, and a DNS resolver that rejects non-public IP addresses. It records status, elapsed time, classification and error metadata, not response bodies. HTTP redirects are classified but not followed.

This is a local development prototype, not a production multi-tenant security boundary. Do not expose the API publicly without authentication, rate limiting, per-user target authorization and stronger network egress controls. SQLite remains local; use PostgreSQL before Render deployment.
