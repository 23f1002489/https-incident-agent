# Phase 5: HTTPS action telemetry and verification

This extends Phase 4 without changing existing database tables. Startup creates `action_telemetry` automatically.

## Setup (PowerShell)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env to add AI_PIPE_TOKEN and OPERATOR_API_KEY
python -m uvicorn app.main:app --reload
python -m pytest -v
```

Back up `data/incidents.db` from Phase 4 and copy it into this project's `data` directory before starting. Keep `ALLOWED_HTTPS_HOSTS=example.com` for the demo. For operator-protected requests, include `X-Operator-Key` in Swagger UI or use curl.

## Workflow
1. POST `/incidents` with service, https URL and symptom.
2. POST `/incidents/{id}/diagnose` to collect **real** pre-action evidence.
3. POST `/incidents/{id}/investigate` (requires AI Pipe token).
4. POST `/incidents/{id}/actions` with investigation ID and `capture_evidence_snapshot`.
5. POST `/actions/{action_id}/decision` with `{"approver":"local-operator","decision":"approved"}`.
6. POST `/actions/{action_id}/execute`.
7. POST `/actions/{action_id}/verify` to collect one fresh HTTPS observation and persist linked before/after telemetry.
8. GET `/actions/{action_id}/telemetry` or GET `/incidents/{id}/telemetry`.
9. GET `/incidents/{id}/actions` to inspect persisted verification results.

The verification uses the latest diagnostic completed before action execution and one fresh diagnostic taken after execution. It does not attribute recovery to demo actions, and does not prove sustained recovery. The original diagnostics remain unchanged. Verification is single-use per action. No arbitrary command execution or external write actions.

## Deployment warning
This is local-only. Phase 6 must introduce auth on *all* endpoints, PostgreSQL, rate limiting, network egress controls and crash recovery before public Render deployment.
