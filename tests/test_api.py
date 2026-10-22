import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'incidents.db')
    from app.main import app
    monkeypatch.setenv('OPERATOR_API_KEY', 'test-secret')
    with TestClient(app) as test_client:
        test_client.headers.update({'X-Operator-Key': 'test-secret'})
        yield test_client


def test_health(client):
    assert client.get('/health').json()['status'] == 'ok'


def test_create_and_retrieve(client):
    payload = {'service': 'demo-api', 'url': 'https://example.com/api', 'symptom': 'http_5xx', 'description': 'HTTP 503'}
    created = client.post('/incidents', json=payload)
    assert created.status_code == 201
    incident = created.json()
    assert incident['status'] == 'open'
    assert client.get('/incidents/' + incident['id']).json() == incident
    assert len(client.get('/incidents').json()) == 1


def test_validation(client):
    response = client.post('/incidents', json={'service': 'demo', 'url': 'not-a-url', 'symptom': 'http_5xx'})
    assert response.status_code == 422


def test_missing(client):
    assert client.get('/incidents/INC-NOTFOUND').status_code == 404
