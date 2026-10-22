from fastapi.testclient import TestClient
from app.main import app


def test_global_auth(monkeypatch, tmp_path):
    import app.database as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'phase6.db')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('OPERATOR_API_KEY', 'test-secret')
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/incidents').status_code == 401
        assert client.get('/incidents', headers={'X-Operator-Key':'wrong'}).status_code == 401
        assert client.get('/incidents', headers={'X-Operator-Key':'test-secret'}).status_code == 200


def test_postgres_placeholder_adapter():
    from app.database import PgConnection
    class Fake:
        def execute(self, sql, params):
            return sql, params
    adapter = PgConnection(Fake())
    sql, params = adapter.execute('SELECT * FROM incidents WHERE id=?', ('ABC',))
    assert '%s' in sql and params == ('ABC',)
    sql, params = adapter.execute('INSERT INTO incidents (id) VALUES (:id)', {'id':'ABC'})
    assert '%(id)s' in sql and params == {'id':'ABC'}
