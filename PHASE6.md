# Phase 6: Render + PostgreSQL deployment

## Local

Create a Python 3.12 virtual environment and install `requirements.txt`.
Copy `.env.example` to `.env`, set `OPERATOR_API_KEY`, `AI_PIPE_TOKEN`, and an exact host allowlist.
Run `python -m uvicorn app.main:app --reload` and `python -m pytest -v`.

All API routes except `/health` and documentation require `X-Operator-Key`.
Swagger UI is available for schema browsing; requests need the header. PowerShell
`Invoke-RestMethod` or curl.exe are convenient for authenticated requests.

## Render Blueprint

1. Push this directory to a private GitHub repository (do not commit `.env` or SQLite files).
2. In Render, create a new Blueprint from the repository's `render.yaml`.
3. Review the web service and database plans/pricing before approving creation.
4. Set the `AI_PIPE_TOKEN` secret. Render generates `OPERATOR_API_KEY`; retrieve it from your Render service environment and store it privately.
5. Wait for the deployment and verify `https://YOUR-SERVICE.onrender.com/health`.
6. Test authenticated routes with `X-Operator-Key`.
7. Set `ALLOWED_HTTPS_HOSTS` to a narrow list of approved domains; only HTTPS 443 is probed.

The Render PostgreSQL database starts empty. Copying a SQLite file into the service
will NOT migrate it. Use a separate reviewed export/import migration if preserving
old incident history is required.

## PowerShell smoke test

```powershell
$base = 'https://YOUR-SERVICE.onrender.com'
$key = 'YOUR-OPERATOR-KEY'
$headers = @{ 'X-Operator-Key' = $key }
Invoke-RestMethod "$base/health"
$body = @{ service='demo'; url='https://example.com/'; symptom='high_latency'; description='render smoke test' } | ConvertTo-Json
$incident = Invoke-RestMethod -Method Post -Uri "$base/incidents" -Headers $headers -ContentType 'application/json' -Body $body
$incident
Invoke-RestMethod -Method Post -Uri "$base/incidents/$($incident.id)/diagnose" -Headers $headers
Invoke-RestMethod -Uri "$base/incidents/$($incident.id)/diagnostics" -Headers $headers
```

## Security / operational boundaries

- This remains a **demo**, not production-ready remediation. Actions are local-only.
- `OPERATOR_API_KEY` is a shared key, not an identity or separation-of-duties system.
- Docs and OpenAPI schemas are public; disable or protect them if sensitive.
- No per-client rate limiting or queue; add gateway throttling and a durable job queue before broad access.
- DNS filtering is app-level defense in depth, not an egress firewall; enforce network policies before probing sensitive infrastructure.
- Render deploys may run multiple instances; ensure idempotent action transitions and use distributed locks for long-running verification.
- DB schema initialization is automatic for fresh installations, but production schema upgrades require migrations.
- Store secrets only in Render environment settings, never in source code.
- No automated migration from local SQLite data is provided.
