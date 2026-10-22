import pytest
from fastapi.testclient import TestClient
from app.diagnostics import TargetRejected, check_target

@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.db')
    monkeypatch.setenv('ALLOWED_HTTPS_HOSTS', 'example.com')
    monkeypatch.setenv('OPERATOR_API_KEY', 'test-secret')
    from app.main import app
    with TestClient(app) as c:
        c.headers.update({'X-Operator-Key': 'test-secret'})
        yield c

def create(client, url='https://example.com/status'):
    r = client.post('/incidents', json={'service':'demo','url':url,'symptom':'http_5xx'})
    assert r.status_code == 201
    return r.json()['id']

def test_reject_private_and_unapproved(monkeypatch):
    monkeypatch.setenv('ALLOWED_HTTPS_HOSTS','example.com')
    for url in ['https://127.0.0.1/', 'https://localhost/', 'https://example.com:8443/', 'http://example.com/', 'https://other.com/']:
        with pytest.raises(TargetRejected):
            check_target(url)

def test_saved_diagnostics(client, monkeypatch):
    import app.main as main
    async def fake_probe(url):
        return {'http_status':503,'latency_ms':41.5,'classification':'http_5xx',
                'error_type':None,'error_message':None,'remote_ip':'93.184.215.14'}
    monkeypatch.setattr(main, 'probe_https', fake_probe)
    iid = create(client)
    r = client.post(f'/incidents/{iid}/diagnose')
    assert r.status_code == 201, r.text
    assert r.json()['http_status'] == 503
    rows = client.get(f'/incidents/{iid}/diagnostics').json()
    assert len(rows) == 1 and rows[0]['id'] == r.json()['id']

def test_denied_host_not_probed(client):
    iid = create(client,'https://unapproved.example.org/')
    assert client.post(f'/incidents/{iid}/diagnose').status_code == 403
    assert client.get(f'/incidents/{iid}/diagnostics').json() == []

def test_missing_incident(client):
    assert client.post('/incidents/MISSING/diagnose').status_code == 404
    assert client.get('/incidents/MISSING/diagnostics').status_code == 404
