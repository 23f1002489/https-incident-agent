# Phase 4 — Approval-gated demo actions

This project builds on Phase 3. No real infrastructure changes occur in Phase 4.

## Setup (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and supply AI_PIPE_TOKEN and a long random OPERATOR_API_KEY
python -m uvicorn app.main:app --reload
python -m pytest -v
```

To generate a random operator key:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

For Swagger UI, use the `X-Operator-Key` header on protected requests. Swagger may expose this as an endpoint header input. Avoid sending secrets to external services.

## Flow

1. POST /incidents to create incident.
2. POST /incidents/{id}/diagnose to capture real HTTPS diagnostic.
3. POST /incidents/{id}/investigate to create AI Pipe investigation.
4. POST /incidents/{id}/actions with `{ "investigation_id": "INV-...", "action_type": "capture_evidence_snapshot", "parameters": {} }` and X-Operator-Key header.
5. POST /actions/{action_id}/decision with `{ "approver": "local-operator", "decision": "approved" }` and X-Operator-Key.
6. POST /actions/{action_id}/execute with X-Operator-Key.
7. GET /incidents/{id}/actions with X-Operator-Key to inspect persisted results.

Available actions: `capture_evidence_snapshot` and `record_manual_escalation`. Both are local-only. An escalation record is not an email/page. Execution results are recorded from actual local functions; no simulated remote remediation success is claimed.

Approval requires a shared operator key and a supplied approver label. This is NOT identity verification or separation of duties. Production needs authenticated identities, independent approval authorization, complete audit events, idempotency/recovery, and secured Phase 1-3 endpoints. Do not deploy publicly as-is.

Existing SQLite DB can be copied into `data/incidents.db` before startup; the actions table is added automatically. Back it up first.
