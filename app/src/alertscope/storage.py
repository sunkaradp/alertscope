import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import Alert, Analysis


class IncidentStore:
    """SQLite incident ledger; mount its parent directory for persistence."""

    def __init__(self, path: str):
        self.path = path
        self._memory_connection = sqlite3.connect(":memory:") if path == ":memory:" else None
        if self._memory_connection is None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._session() as db:
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
            db.execute("""
                CREATE TABLE IF NOT EXISTS incident_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS incidents_last_seen ON incidents(last_seen)")
            db.execute(
                "CREATE INDEX IF NOT EXISTS incident_events_timeline "
                "ON incident_events(incident_id, occurred_at)"
            )

    def _connect(self):
        db = self._memory_connection or sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        if self._memory_connection is None:
            db.execute("PRAGMA journal_mode=WAL")
        return db

    @contextmanager
    def _session(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if db is not self._memory_connection:
                db.close()

    def record_analysis(self, alert: Alert, analysis: Analysis) -> None:
        incident_id = alert.key()
        first_seen = alert.startsAt.isoformat()
        now = analysis.created_at.isoformat()
        details = json.dumps({
            "provider": analysis.provider,
            "confidence": analysis.confidence,
            "likely_cause": analysis.likely_cause,
        })
        with self._session() as db:
            previous = db.execute(
                "SELECT status FROM incidents WHERE incident_id=?", (incident_id,)
            ).fetchone()
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
            """, (
                incident_id, alert.name, alert.severity, first_seen, now,
                analysis.model_dump_json(),
            ))
            event_type = "reopened" if previous and previous["status"] == "resolved" else "analysis_recorded"
            db.execute("""
                INSERT INTO incident_events (incident_id, event_type, occurred_at, details)
                VALUES (?, ?, ?, ?)
            """, (incident_id, event_type, now, details))

    def list_incidents(self, limit: int = 100) -> list[dict]:
        with self._session() as db:
            rows = db.execute(
                "SELECT * FROM incidents ORDER BY last_seen DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def get_incident(self, incident_id: str) -> dict | None:
        with self._session() as db:
            row = db.execute(
                "SELECT * FROM incidents WHERE incident_id=?", (incident_id,)
            ).fetchone()
            if row is None:
                return None
            item = self._serialize(row)
            events = db.execute(
                "SELECT event_type, occurred_at, details FROM incident_events "
                "WHERE incident_id=? ORDER BY event_id",
                (incident_id,),
            ).fetchall()
        item["events"] = [
            {
                "event_type": event["event_type"],
                "occurred_at": event["occurred_at"],
                "details": json.loads(event["details"]),
            }
            for event in events
        ]
        return item

    def acknowledge(self, incident_id: str) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self._session() as db:
            updated = db.execute("""
                UPDATE incidents SET status='acknowledged', acknowledged_at=?
                WHERE incident_id=? AND status='open'
            """, (now, incident_id))
            if updated.rowcount:
                db.execute("""
                    INSERT INTO incident_events (incident_id, event_type, occurred_at)
                    VALUES (?, 'acknowledged', ?)
                """, (incident_id, now))
        return self.get_incident(incident_id)

    def resolve(self, incident_id: str) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self._session() as db:
            updated = db.execute("""
                UPDATE incidents SET status='resolved', resolved_at=?
                WHERE incident_id=? AND status!='resolved'
            """, (now, incident_id))
            if updated.rowcount:
                db.execute("""
                    INSERT INTO incident_events (incident_id, event_type, occurred_at)
                    VALUES (?, 'resolved', ?)
                """, (incident_id, now))
        return self.get_incident(incident_id)

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["latest_analysis"] = (
            json.loads(item["latest_analysis"]) if item["latest_analysis"] else None
        )
        return item
