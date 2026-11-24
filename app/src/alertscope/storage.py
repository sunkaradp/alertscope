import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import Alert, Analysis


class IncidentStore:
    """SQLite-backed incident ledger; mount its parent directory for persistence."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    alert TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    acknowledged_at TEXT,
                    resolved_at TEXT,
                    latest_analysis TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS incidents_last_seen ON incidents(last_seen)")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def record_analysis(self, alert: Alert, analysis: Analysis) -> None:
        first_seen = alert.startsAt.isoformat()
        first_seen = alert.startsAt.isoformat()
        now = analysis.created_at.isoformat()
        with self._connect() as db:
            db.execute("""
                INSERT INTO incidents
                    (incident_id, alert, severity, status, first_seen, last_seen, latest_analysis)
                VALUES (?, ?, ?, 'open', ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    alert=excluded.alert,
                    severity=excluded.severity,
                    last_seen=excluded.last_seen,
                    latest_analysis=excluded.latest_analysis,
                    status=CASE WHEN incidents.status='resolved' THEN 'open' ELSE incidents.status END,
                    resolved_at=NULL
            """, (alert.key(), alert.name, alert.severity, first_seen, now,
                  analysis.model_dump_json()))

    def list_incidents(self, limit: int = 100) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM incidents ORDER BY last_seen DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def get_incident(self, incident_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM incidents WHERE incident_id=?", (incident_id,)
            ).fetchone()
        return self._serialize(row) if row else None

    def acknowledge(self, incident_id: str) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("""
                UPDATE incidents SET status='acknowledged', acknowledged_at=?
                WHERE incident_id=? AND status='open'
            """, (now, incident_id))
        return self.get_incident(incident_id)

    def resolve(self, incident_id: str) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("""
                UPDATE incidents SET status='resolved', resolved_at=?
                WHERE incident_id=? AND status!='resolved'
            """, (now, incident_id))
        return self.get_incident(incident_id)

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["latest_analysis"] = (
            json.loads(item["latest_analysis"]) if item["latest_analysis"] else None
        )
        return item
