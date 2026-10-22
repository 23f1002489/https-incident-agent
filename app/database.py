"""SQLite for local development; PostgreSQL when DATABASE_URL is configured."""
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(os.getenv('DATABASE_PATH', 'data/incidents.db'))

def postgres_enabled():
    return bool(os.getenv('DATABASE_URL'))


class PgConnection:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        # Existing app uses SQLite-style ? and :named placeholders.
        if isinstance(params, dict):
            sql = re.sub(r':([a-zA-Z_][a-zA-Z0-9_]*)', r'%(\1)s', sql)
        else:
            sql = sql.replace('?', '%s')
        return self.conn.execute(sql, params)


@contextmanager
def connection():
    if postgres_enabled():
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as conn:
            yield PgConnection(conn)
    else:
        path = DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=20) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            yield conn


def initialize_database():
    with connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY, service TEXT NOT NULL, url TEXT NOT NULL,
            symptom TEXT NOT NULL, description TEXT, status TEXT NOT NULL,
            created_at TEXT NOT NULL)''')


def initialize_diagnostics_table():
    with connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS diagnostics (
            id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
            started_at TEXT NOT NULL, completed_at TEXT NOT NULL, url TEXT NOT NULL,
            http_status INTEGER, latency_ms DOUBLE PRECISION, classification TEXT NOT NULL,
            error_type TEXT, error_message TEXT, remote_ip TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_diagnostics_incident ON diagnostics(incident_id, started_at)')


def initialize_investigations_table():
    with connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS investigations (
            id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
            created_at TEXT NOT NULL, model TEXT NOT NULL, diagnostic_ids_json TEXT NOT NULL,
            diagnosis TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL,
            evidence_json TEXT NOT NULL, limitations_json TEXT NOT NULL,
            next_diagnostics_json TEXT NOT NULL, recommended_response TEXT NOT NULL,
            status TEXT NOT NULL)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_investigations_incident ON investigations(incident_id, created_at)')


def initialize_actions_table():
    with connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
            investigation_id TEXT NOT NULL REFERENCES investigations(id),
            action_type TEXT NOT NULL, parameters_json TEXT NOT NULL,
            status TEXT NOT NULL, requested_at TEXT NOT NULL,
            approved_at TEXT, approved_by TEXT, executed_at TEXT,
            result_json TEXT, verification_json TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_actions_incident ON actions(incident_id, requested_at)')


def initialize_telemetry_table():
    with connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS action_telemetry (
            id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES actions(id),
            incident_id TEXT NOT NULL REFERENCES incidents(id),
            diagnostic_id TEXT NOT NULL REFERENCES diagnostics(id),
            phase TEXT NOT NULL CHECK(phase IN ('before','after')),
            observed_at TEXT NOT NULL, http_status INTEGER,
            latency_ms DOUBLE PRECISION, classification TEXT NOT NULL,
            recorded_at TEXT NOT NULL, UNIQUE(action_id, phase, diagnostic_id))''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_action_telemetry ON action_telemetry(action_id, phase, observed_at)')
