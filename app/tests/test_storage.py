from datetime import UTC, datetime

from alertscope.models import Alert, Analysis
from alertscope.storage import IncidentStore


def test_incident_lifecycle_persists_and_reopens(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.db"))
    alert = Alert(
        status="firing",
        labels={"alertname": "PodCrashLoop", "severity": "warning"},
        startsAt=datetime.now(UTC),
        fingerprint="incident-123",
    )
    analysis = Analysis(
        alert=alert.name,
        severity=alert.severity,
        labels=alert.labels,
        summary="Container restarted repeatedly.",
        likely_cause="CrashLoopBackOff",
        confidence="medium",
    )

    store.record_analysis(alert, analysis)
    item = store.get_incident("incident-123")
    assert item["status"] == "open"
    assert item["latest_analysis"]["likely_cause"] == "CrashLoopBackOff"

    acknowledged = store.acknowledge("incident-123")
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_at"] is not None

    resolved = store.resolve("incident-123")
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None

    # A new analysis for the same fingerprint reopens the incident.
    later = analysis.model_copy(update={"summary": "The pod restarted again."})
    store.record_analysis(alert, later)
    reopened = store.get_incident("incident-123")
    assert reopened["status"] == "open"
    assert reopened["resolved_at"] is None
    assert reopened["latest_analysis"]["summary"] == "The pod restarted again."


def test_missing_incident_operations_return_none(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.db"))
    assert store.get_incident("missing") is None
    assert store.acknowledge("missing") is None
    assert store.resolve("missing") is None
