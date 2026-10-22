import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'incidents.db')
    monkeypatch.setenv('OPERATOR_API_KEY', 'test-secret')
    from app.main import app
    with TestClient(app) as c:
        c.headers.update({'X-Operator-Key': 'test-secret'})
        yield c


def seed(client):
    incident = client.post('/incidents', json={'service': 'demo', 'url': 'https://example.com/', 'symptom': 'http_5xx'}).json()
    import app.database as db
    with db.connection() as conn:
        conn.execute("""INSERT INTO investigations
        (id,incident_id,created_at,model,diagnostic_ids_json,diagnosis,confidence,evidence_json,limitations_json,next_diagnostics_json,recommended_response,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ('INV-TEST',incident['id'],'2026-01-01T00:00:00Z','mock','[]','Unknown',0.2,'[]','[]','[]','Review','recommendation_only'))
    return incident['id']


def auth():
    return {'X-Operator-Key': 'test-secret'}


def request(client, incident_id, action_type='capture_evidence_snapshot', headers=None):
    return client.post(f'/incidents/{incident_id}/actions', headers=headers or auth(), json={
        'investigation_id':'INV-TEST','action_type':action_type,'parameters':{}})


def test_auth_and_registry(client):
    incident_id=seed(client)
    assert request(client,incident_id,headers={'X-Operator-Key':'wrong'}).status_code == 401
    assert request(client,incident_id,'restart_server').status_code == 422
    assert 'capture_evidence_snapshot' in client.get('/actions/allowed').json()['actions']


def test_approval_and_execute_once(client):
    incident_id=seed(client)
    created=request(client,incident_id)
    assert created.status_code == 201
    action_id=created.json()['id']
    assert client.post(f'/actions/{action_id}/execute',headers=auth()).status_code == 409
    approved=client.post(f'/actions/{action_id}/decision',headers=auth(),json={'approver':'operator','decision':'approved'})
    assert approved.json()['status']=='approved'
    result=client.post(f'/actions/{action_id}/execute',headers=auth())
    assert result.status_code == 200
    assert result.json()['status']=='succeeded'
    assert result.json()['result']['operation']=='capture_evidence_snapshot'
    assert result.json()['verification']['remote_service_recovery_verified'] is False
    assert client.post(f'/actions/{action_id}/execute',headers=auth()).status_code == 409
    assert client.get(f'/incidents/{incident_id}/actions',headers=auth()).json()[0]['result'] == result.json()['result']


def test_rejection(client):
    incident_id=seed(client)
    action_id=request(client,incident_id).json()['id']
    response=client.post(f'/actions/{action_id}/decision',headers=auth(),json={'approver':'operator','decision':'rejected'})
    assert response.json()['status']=='rejected'
    assert client.post(f'/actions/{action_id}/execute',headers=auth()).status_code == 409
    assert client.post(f'/actions/{action_id}/decision',headers=auth(),json={'approver':'operator','decision':'approved'}).status_code == 409


def test_wrong_investigation(client):
    incident_id=seed(client)
    response=client.post(f'/incidents/{incident_id}/actions',headers=auth(),json={
        'investigation_id':'INV-OTHER','action_type':'capture_evidence_snapshot','parameters':{}})
    assert response.status_code == 409
