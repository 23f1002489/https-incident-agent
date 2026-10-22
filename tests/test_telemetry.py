from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'incidents.db')
    monkeypatch.setenv('OPERATOR_API_KEY', 'test-secret')
    monkeypatch.setenv('ALLOWED_HTTPS_HOSTS', 'example.com')
    from app.main import app
    with TestClient(app) as c:
        c.headers.update({'X-Operator-Key': 'test-secret'})
        yield c

def prepare(client):
    from app.database import connection
    incident = client.post('/incidents', json={'service':'demo','url':'https://example.com/','symptom':'http_5xx'}).json()
    id = incident['id']
    with connection() as conn:
        conn.execute('''INSERT INTO diagnostics (id,incident_id,started_at,completed_at,url,http_status,latency_ms,classification,error_type,error_message,remote_ip) VALUES (?,?,?,?,?,?,?,?,?,?,?)''', ('DIAG-PRE',id,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00','https://example.com/',503,500.0,'http_5xx',None,None,None))
        conn.execute('''INSERT INTO investigations (id,incident_id,created_at,model,diagnostic_ids_json,diagnosis,confidence,evidence_json,limitations_json,next_diagnostics_json,recommended_response,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', ('INV-TEST',id,'2026-01-01T00:00:02+00:00','mock','["DIAG-PRE"]','unknown',0.2,'[]','[]','[]','review','recommendation_only'))
    h={'X-Operator-Key':'test-secret'}
    a=client.post(f'/incidents/{id}/actions',headers=h,json={'investigation_id':'INV-TEST','action_type':'capture_evidence_snapshot','parameters':{}}).json()['id']
    client.post(f'/actions/{a}/decision',headers=h,json={'approver':'operator','decision':'approved'})
    assert client.post(f'/actions/{a}/execute',headers=h).status_code==200
    return id,a,h

def test_real_evidence_correlation_persistence(client, monkeypatch):
    import app.main as main
    incident,action,h=prepare(client)
    monkeypatch.setattr(main,'probe_https',AsyncMock(return_value={'http_status':200,'latency_ms':120.0,'classification':'healthy','error_type':None,'error_message':None,'remote_ip':'93.184.215.14'}))
    r=client.post(f'/actions/{action}/verify',headers=h)
    assert r.status_code==201,r.text
    payload=r.json()
    assert payload['verification']['outcome']=='observed_recovery'
    assert payload['verification']['caused_by_action'] is False
    assert payload['verification']['latency_delta_ms']==-380.0
    assert payload['telemetry'][0]['diagnostic_id']=='DIAG-PRE'
    assert payload['telemetry'][1]['http_status']==200
    assert len(client.get(f'/actions/{action}/telemetry',headers=h).json())==2
    assert len(client.get(f'/incidents/{incident}/telemetry',headers=h).json())==2
    assert client.post(f'/actions/{action}/verify',headers=h).status_code==409
    assert client.get(f'/incidents/{incident}/actions',headers=h).json()[0]['verification']['outcome']=='observed_recovery'

def test_auth_and_missing_action(client):
    assert client.get('/actions/MISSING/telemetry',headers={'X-Operator-Key':'wrong'}).status_code==401
    assert client.get('/actions/MISSING/telemetry',headers={'X-Operator-Key':'test-secret'}).status_code==404

def test_pre_action_required(client,monkeypatch):
    import app.main as main
    incident,action,h=prepare(client)
    from app.database import connection
    with connection() as conn:
        conn.execute("DELETE FROM diagnostics WHERE id='DIAG-PRE'")
    mock=AsyncMock()
    monkeypatch.setattr(main,'probe_https',mock)
    assert client.post(f'/actions/{action}/verify',headers=h).status_code==409
    mock.assert_not_awaited()
