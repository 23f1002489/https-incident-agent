from dotenv import load_dotenv
load_dotenv()

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status, Header, Depends, Request
import os
import secrets

from app.database import connection, initialize_database, initialize_diagnostics_table, initialize_investigations_table, initialize_actions_table, initialize_telemetry_table
from app.actions import ActionRequest, ApprovalRequest, ACTION_REGISTRY, validate_action, execute_demo_action
from app.diagnostics import TargetRejected, check_target, probe_https
from app.schemas import Incident, IncidentCreate
from app.investigation import analyze_with_aipipe, InvestigationError


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    initialize_diagnostics_table()
    initialize_investigations_table()
    initialize_actions_table()
    initialize_telemetry_table()
    yield


app = FastAPI(title='HTTPS Incident Agent', version='0.6.0', lifespan=lifespan)

# Protect all incident, action, and documentation routes, including reads.
# /health remains public for Render health checks.
@app.middleware('http')
async def require_api_auth(request: Request, call_next):
    from fastapi.responses import JSONResponse
    path = request.url.path
    if path in ('/health', '/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc'):
        return await call_next(request)
    expected = os.getenv('OPERATOR_API_KEY', '')
    supplied = request.headers.get('X-Operator-Key', '')
    if not expected or not secrets.compare_digest(supplied, expected):
        return JSONResponse({'detail': 'Valid X-Operator-Key required'}, status_code=401)
    print(
    "AUTH DEBUG:",
    "configured=", bool(os.getenv("OPERATOR_API_KEY")),
    "expected_length=", len(os.getenv("OPERATOR_API_KEY", "")),
    "received_length=", len(request.headers.get('X-Operator-Key', '')),
    flush=True
)
    return await call_next(request)



def from_row(row):
    return Incident.model_validate(dict(row))


@app.get('/health')
def health():
    return {'status': 'ok', 'phase': 6}


@app.post('/incidents', response_model=Incident, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate):
    incident = Incident(
        id=f'INC-{uuid4().hex[:12].upper()}',
        status='open',
        created_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )
    with connection() as conn:
        conn.execute(
            'INSERT INTO incidents (id, service, url, symptom, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (incident.id, incident.service, str(incident.url), incident.symptom.value,
             incident.description, incident.status, incident.created_at.isoformat()),
        )
    return incident


@app.get('/incidents', response_model=list[Incident])
def list_incidents():
    with connection() as conn:
        rows = conn.execute('SELECT * FROM incidents ORDER BY created_at DESC').fetchall()
    return [from_row(row) for row in rows]


@app.get('/incidents/{incident_id}', response_model=Incident)
def get_incident(incident_id: str):
    with connection() as conn:
        row = conn.execute('SELECT * FROM incidents WHERE id = ?', (incident_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Incident not found')
    return from_row(row)


@app.post('/incidents/{incident_id}/diagnose', status_code=201)
async def diagnose_incident(incident_id: str):
    with connection() as conn:
        incident = conn.execute('SELECT * FROM incidents WHERE id = ?', (incident_id,)).fetchone()
    if incident is None:
        raise HTTPException(status_code=404, detail='Incident not found')
    url = incident['url']
    try:
        check_target(url)
    except TargetRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    started_at = datetime.now(timezone.utc).isoformat()
    result = await probe_https(url)
    completed_at = datetime.now(timezone.utc).isoformat()
    record = {'id': f'DIAG-{uuid4().hex[:12].upper()}', 'incident_id': incident_id,
              'started_at': started_at, 'completed_at': completed_at, 'url': url, **result}
    with connection() as conn:
        conn.execute('''INSERT INTO diagnostics
            (id, incident_id, started_at, completed_at, url, http_status, latency_ms,
             classification, error_type, error_message, remote_ip)
            VALUES (:id, :incident_id, :started_at, :completed_at, :url, :http_status,
                    :latency_ms, :classification, :error_type, :error_message, :remote_ip)''', record)
    return record


@app.get('/incidents/{incident_id}/diagnostics')
def get_diagnostics(incident_id: str):
    with connection() as conn:
        incident = conn.execute('SELECT id FROM incidents WHERE id = ?', (incident_id,)).fetchone()
        if incident is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        rows = conn.execute('SELECT * FROM diagnostics WHERE incident_id = ? ORDER BY started_at DESC',
                            (incident_id,)).fetchall()
    return [dict(row) for row in rows]


def investigation_from_row(row):
    record = dict(row)
    for key in ('diagnostic_ids', 'evidence', 'limitations', 'next_diagnostics'):
        record[key] = json.loads(record.pop(key + '_json'))
    return record


@app.post('/incidents/{incident_id}/investigate', status_code=201)
async def investigate_incident(incident_id: str):
    with connection() as conn:
        incident = conn.execute('SELECT * FROM incidents WHERE id = ?', (incident_id,)).fetchone()
        if incident is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        rows = conn.execute('SELECT * FROM diagnostics WHERE incident_id = ? ORDER BY started_at DESC LIMIT 10',
                            (incident_id,)).fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail='Run HTTPS diagnostics before investigation')
    diagnostics = [dict(row) for row in rows]
    # Only stored probe evidence is passed to the model. No shell access or tool execution.
    try:
        analysis, model = await analyze_with_aipipe(dict(incident), diagnostics)
    except InvestigationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record = {
        'id': f'INV-{uuid4().hex[:12].upper()}',
        'incident_id': incident_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'model': model,
        'diagnostic_ids_json': json.dumps([d['id'] for d in diagnostics]),
        'diagnosis': analysis.diagnosis,
        'confidence': analysis.confidence,
        'evidence_json': json.dumps(analysis.evidence_ids),
        'limitations_json': json.dumps(analysis.limitations),
        'next_diagnostics_json': json.dumps(analysis.next_diagnostics),
        'recommended_response': analysis.recommended_response,
        'status': 'recommendation_only',
    }
    with connection() as conn:
        conn.execute("""INSERT INTO investigations             (id, incident_id, created_at, model, diagnostic_ids_json, diagnosis, confidence,
             evidence_json, limitations_json, next_diagnostics_json, recommended_response, status)
            VALUES (:id, :incident_id, :created_at, :model, :diagnostic_ids_json, :diagnosis,
                    :confidence, :evidence_json, :limitations_json, :next_diagnostics_json,
                    :recommended_response, :status)""", record)
    return investigation_from_row(record)


@app.get('/incidents/{incident_id}/investigations')
def list_investigations(incident_id: str):
    with connection() as conn:
        if conn.execute('SELECT id FROM incidents WHERE id = ?', (incident_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        rows = conn.execute('SELECT * FROM investigations WHERE incident_id = ? ORDER BY created_at DESC',
                            (incident_id,)).fetchall()
    return [investigation_from_row(row) for row in rows]


# This API key is required for all Phase 4 state-changing endpoints.
# Never expose the service publicly without protecting the earlier Phase 1-3 routes too.
def require_operator_key(x_operator_key: str | None = Header(default=None)):
    expected = os.getenv('OPERATOR_API_KEY', '')
    if not expected or not x_operator_key or not secrets.compare_digest(x_operator_key, expected):
        raise HTTPException(status_code=401, detail='Valid X-Operator-Key required')


def action_from_row(row):
    data = dict(row)
    data['parameters'] = json.loads(data.pop('parameters_json'))
    data['result'] = json.loads(data.pop('result_json')) if data.get('result_json') else None
    data['verification'] = json.loads(data.pop('verification_json')) if data.get('verification_json') else None
    return data


@app.get('/actions/allowed')
def allowed_actions():
    return {'actions': list(ACTION_REGISTRY), 'mode': 'approval_required_demo_only'}


@app.post('/incidents/{incident_id}/actions', status_code=201, dependencies=[Depends(require_operator_key)])
def request_action(incident_id: str, payload: ActionRequest):
    try:
        validate_action(payload.action_type, payload.parameters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with connection() as conn:
        if conn.execute('SELECT id FROM incidents WHERE id=?', (incident_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        inv = conn.execute('SELECT id FROM investigations WHERE id=? AND incident_id=?',
                           (payload.investigation_id, incident_id)).fetchone()
        if inv is None:
            raise HTTPException(status_code=409, detail='Investigation must belong to this incident')
        record = {'id': f'ACT-{uuid4().hex[:12].upper()}', 'incident_id': incident_id,
                  'investigation_id': payload.investigation_id, 'action_type': payload.action_type,
                  'parameters_json': json.dumps(payload.parameters), 'status': 'pending_approval',
                  'requested_at': datetime.now(timezone.utc).isoformat()}
        conn.execute("""INSERT INTO actions
            (id, incident_id, investigation_id, action_type, parameters_json, status, requested_at)
            VALUES (:id,:incident_id,:investigation_id,:action_type,:parameters_json,:status,:requested_at)""", record)
        row = conn.execute('SELECT * FROM actions WHERE id=?', (record['id'],)).fetchone()
    return action_from_row(row)


@app.post('/actions/{action_id}/decision', dependencies=[Depends(require_operator_key)])
def decide_action(action_id: str, payload: ApprovalRequest):
    if payload.decision not in ('approved', 'rejected'):
        raise HTTPException(status_code=422, detail='decision must be approved or rejected')
    with connection() as conn:
        cursor = conn.execute("""UPDATE actions SET status=?, approved_at=?, approved_by=?
            WHERE id=? AND status='pending_approval' """,
            (payload.decision, datetime.now(timezone.utc).isoformat(), payload.approver, action_id))
        if cursor.rowcount != 1:
            exists = conn.execute('SELECT 1 FROM actions WHERE id=?', (action_id,)).fetchone()
            raise HTTPException(status_code=409 if exists else 404,
                                detail='Action already decided' if exists else 'Action not found')
        row = conn.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
    return action_from_row(row)


@app.post('/actions/{action_id}/execute', dependencies=[Depends(require_operator_key)])
async def execute_action(action_id: str):
    # Atomic state transition prevents repeated/concurrent execution.
    with connection() as conn:
        cursor = conn.execute("UPDATE actions SET status='executing' WHERE id=? AND status='approved'", (action_id,))
        if cursor.rowcount != 1:
            exists = conn.execute('SELECT 1 FROM actions WHERE id=?', (action_id,)).fetchone()
            raise HTTPException(status_code=409 if exists else 404,
                                detail='Action is not approved or was already executed' if exists else 'Action not found')
        row = conn.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
        action = dict(row)
        diagnostics = [dict(d) for d in conn.execute(
            'SELECT * FROM diagnostics WHERE incident_id=? ORDER BY started_at DESC LIMIT 10',
            (action['incident_id'],)).fetchall()]
    try:
        validate_action(action['action_type'], json.loads(action['parameters_json']))
        result = await execute_demo_action(action['action_type'], action['incident_id'], diagnostics)
        state = 'succeeded' if result['success'] else 'failed'
    except Exception as exc:
        state = 'failed'
        result = {'success': False, 'error_type': type(exc).__name__, 'message': 'Demo action failed'}
    verification = {'type': 'local_execution_only', 'verified': state == 'succeeded',
                    'remote_service_recovery_verified': False,
                    'note': 'Phase 5 will correlate post-action HTTPS telemetry'}
    with connection() as conn:
        conn.execute("""UPDATE actions SET status=?, executed_at=?, result_json=?, verification_json=? WHERE id=?""",
                     (state, datetime.now(timezone.utc).isoformat(), json.dumps(result), json.dumps(verification), action_id))
        row = conn.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
    return action_from_row(row)


@app.get('/incidents/{incident_id}/actions', dependencies=[Depends(require_operator_key)])
def list_actions(incident_id: str):
    with connection() as conn:
        if conn.execute('SELECT 1 FROM incidents WHERE id=?', (incident_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        rows = conn.execute('SELECT * FROM actions WHERE incident_id=? ORDER BY requested_at DESC',
                            (incident_id,)).fetchall()
    return [action_from_row(row) for row in rows]


# Phase 5: independent read-only verification. No remediation is performed.
# An observation is linked to the action and to the exact diagnostic row used.
def telemetry_from_row(row):
    return dict(row)


@app.post('/actions/{action_id}/verify', dependencies=[Depends(require_operator_key)], status_code=201)
async def verify_action(action_id: str):
    with connection() as conn:
        row = conn.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='Action not found')
        action = dict(row)
        if action['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail='Only succeeded actions can be verified')
        if conn.execute("SELECT 1 FROM action_telemetry WHERE action_id=? AND phase='after'", (action_id,)).fetchone():
            raise HTTPException(status_code=409, detail='Action already verified')
        incident = conn.execute('SELECT * FROM incidents WHERE id=?', (action['incident_id'],)).fetchone()
        # Match only diagnostics completed before action execution, not future measurements.
        before = conn.execute('''SELECT * FROM diagnostics WHERE incident_id=?
            AND completed_at <= ? ORDER BY completed_at DESC LIMIT 1''',
            (action['incident_id'], action['executed_at'])).fetchone()
    if before is None:
        raise HTTPException(status_code=409, detail='No pre-action diagnostic available')
    url = incident['url']
    try:
        check_target(url)
    except TargetRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    started_at = datetime.now(timezone.utc).isoformat()
    result = await probe_https(url)
    completed_at = datetime.now(timezone.utc).isoformat()
    after = {'id': f'DIAG-{uuid4().hex[:12].upper()}', 'incident_id': action['incident_id'],
             'started_at': started_at, 'completed_at': completed_at, 'url': url, **result}
    now = datetime.now(timezone.utc).isoformat()
    before = dict(before)
    def measurement(d, phase):
        return {'id': f'TEL-{uuid4().hex[:12].upper()}', 'action_id': action_id,
                'incident_id': action['incident_id'], 'diagnostic_id': d['id'],
                'phase': phase, 'observed_at': d['completed_at'], 'http_status': d['http_status'],
                'latency_ms': d['latency_ms'], 'classification': d['classification'],
                'recorded_at': now}
    pre = measurement(before, 'before')
    post = measurement(after, 'after')
    # Comparison is observational: local-only demo actions do not remediate remote services.
    was_healthy = before['classification'] == 'healthy'
    is_healthy = after['classification'] == 'healthy'
    outcome = ('healthy_before_and_after' if was_healthy and is_healthy else
               'observed_recovery' if not was_healthy and is_healthy else
               'observed_regression' if was_healthy and not is_healthy else
               'not_recovered')
    verification = {'type': 'https_before_after', 'outcome': outcome,
                    'remote_service_recovery_verified': outcome == 'observed_recovery',
                    'caused_by_action': False, 'before_diagnostic_id': before['id'],
                    'after_diagnostic_id': after['id'],
                    'latency_delta_ms': (round(after['latency_ms'] - before['latency_ms'], 2)
                                         if after['latency_ms'] is not None and before['latency_ms'] is not None else None),
                    'note': 'Single-point observations do not establish causality; demo actions cannot repair remote HTTPS services.'}
    with connection() as conn:
        # Atomic insert of the new diagnostic, both telemetry links and verification.
        # UNIQUE constraint prevents duplicate verification even for racing requests.
        try:
            conn.execute('''INSERT INTO diagnostics
                (id, incident_id, started_at, completed_at, url, http_status, latency_ms,
                 classification, error_type, error_message, remote_ip)
                VALUES (:id,:incident_id,:started_at,:completed_at,:url,:http_status,:latency_ms,
                        :classification,:error_type,:error_message,:remote_ip)''', after)
            for item in (pre, post):
                conn.execute('''INSERT INTO action_telemetry
                    (id,action_id,incident_id,diagnostic_id,phase,observed_at,http_status,latency_ms,classification,recorded_at)
                    VALUES (:id,:action_id,:incident_id,:diagnostic_id,:phase,:observed_at,:http_status,:latency_ms,:classification,:recorded_at)''', item)
            conn.execute('UPDATE actions SET verification_json=? WHERE id=?', (json.dumps(verification), action_id))
        except ( __import__('sqlite3').IntegrityError, __import__('psycopg').IntegrityError) as exc:
            raise HTTPException(status_code=409, detail='Concurrent verification conflict') from exc
    return {'action_id': action_id, 'verification': verification, 'telemetry': [pre, post]}


@app.get('/actions/{action_id}/telemetry', dependencies=[Depends(require_operator_key)])
def get_action_telemetry(action_id: str):
    with connection() as conn:
        if conn.execute('SELECT 1 FROM actions WHERE id=?', (action_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail='Action not found')
        rows = conn.execute('SELECT * FROM action_telemetry WHERE action_id=? ORDER BY observed_at, phase', (action_id,)).fetchall()
    return [telemetry_from_row(r) for r in rows]


@app.get('/incidents/{incident_id}/telemetry', dependencies=[Depends(require_operator_key)])
def get_incident_telemetry(incident_id: str):
    with connection() as conn:
        if conn.execute('SELECT 1 FROM incidents WHERE id=?', (incident_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        rows = conn.execute('SELECT * FROM action_telemetry WHERE incident_id=? ORDER BY recorded_at, phase', (incident_id,)).fetchall()
    return [telemetry_from_row(r) for r in rows]
