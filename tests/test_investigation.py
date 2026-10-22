import json
import pytest
from fastapi.testclient import TestClient
from app.investigation import InvestigationError, InvestigationResult

@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'incident.db')
    monkeypatch.setenv('OPERATOR_API_KEY', 'test-secret')
    from app.main import app
    with TestClient(app) as c:
        c.headers.update({'X-Operator-Key': 'test-secret'})
        yield c


def create(client):
    response = client.post('/incidents', json={
        'service': 'demo', 'url': 'https://example.com/', 'symptom': 'http_5xx'
    })
    assert response.status_code == 201
    return response.json()['id']


def seed(client, incident_id):
    from app.database import connection
    with connection() as conn:
        conn.execute("""INSERT INTO diagnostics         (id, incident_id, started_at, completed_at, url, http_status, latency_ms,
         classification, error_type, error_message, remote_ip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ('DIAG-TEST1', incident_id, '2026-10-22T00:00:00Z', '2026-10-22T00:00:01Z',
         'https://example.com/', 503, 200, 'http_5xx', None, None, '93.184.215.14'))


def test_requires_diagnostics(client):
    incident_id = create(client)
    assert client.post(f'/incidents/{incident_id}/investigate').status_code == 409


def test_investigation_persists_and_links_evidence(client, monkeypatch):
    incident_id = create(client)
    seed(client, incident_id)
    async def fake(incident, diagnostics):
        assert diagnostics[0]['id'] == 'DIAG-TEST1'
        return InvestigationResult(diagnosis='Observed 503; root cause unknown', confidence=.3,
            evidence_ids=['DIAG-TEST1'], limitations=['No server logs'],
            next_diagnostics=['Inspect server logs'], recommended_response='Escalate for human review'), 'test-model'
    monkeypatch.setattr('app.main.analyze_with_aipipe', fake)
    response = client.post(f'/incidents/{incident_id}/investigate')
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'recommendation_only'
    assert response.json()['evidence'] == ['DIAG-TEST1']
    history = client.get(f'/incidents/{incident_id}/investigations').json()
    assert len(history) == 1 and history[0]['id'] == response.json()['id']


def test_provider_failure_does_not_save(client, monkeypatch):
    incident_id = create(client)
    seed(client, incident_id)
    async def broken(*args):
        raise InvestigationError('upstream unavailable')
    monkeypatch.setattr('app.main.analyze_with_aipipe', broken)
    assert client.post(f'/incidents/{incident_id}/investigate').status_code == 502
    assert client.get(f'/incidents/{incident_id}/investigations').json() == []


def test_unknown_incident(client):
    assert client.post('/incidents/INC-MISSING/investigate').status_code == 404
    assert client.get('/incidents/INC-MISSING/investigations').status_code == 404


def test_model_schema_rejects_bad_confidence():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        InvestigationResult(diagnosis='Unknown', confidence=1.7, evidence_ids=[],
                            limitations=[], next_diagnostics=[], recommended_response='Review')


@pytest.mark.asyncio
async def test_aipipe_rejects_hallucinated_evidence(monkeypatch):
    import app.investigation as investigation
    import httpx
    monkeypatch.setenv('AI_PIPE_TOKEN', 'test-only')
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return {'choices': [{'message': {'content': json.dumps({
                'diagnosis': 'Unknown', 'confidence': .1, 'evidence_ids': ['DIAG-FAKE'],
                'limitations': [], 'next_diagnostics': [], 'recommended_response': 'Review'
            })}}]}
    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return FakeResponse()
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    with pytest.raises(InvestigationError, match='unknown'):
        await investigation.analyze_with_aipipe({'id':'INC-X'}, [{'id':'DIAG-REAL'}])
