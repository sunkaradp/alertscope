import asyncio

from fastapi.testclient import TestClient

from alertscope.main import app

PAYLOAD = {
    "version": "4",
    "status": "firing",
    "receiver": "alertscope",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighErrorRate", "severity": "warning", "job": "breaker"},
            "annotations": {"summary": "5xx above 5%"},
            "startsAt": "2026-11-20T10:00:00Z",
            "fingerprint": "f1",
        }
    ],
}


def test_webhook_queues_and_dedupes(monkeypatch):
    monkeypatch.setenv("ALERTSCOPE_PROMETHEUS_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALERTSCOPE_LOKI_URL", "http://127.0.0.1:1")
    with TestClient(app) as client:
        r = client.post("/webhook/alertmanager", json=PAYLOAD)
        assert r.status_code == 202
        assert r.json() == {"received": 1, "queued": 1}

        r = client.post("/webhook/alertmanager", json=PAYLOAD)
        assert r.json()["queued"] == 0

        tasks = list(app.state.tasks)
        if tasks:
            client.portal.call(asyncio.wait, tasks)
        history = client.get("/analyses").json()
        assert history and history[0]["alert"] == "HighErrorRate"

        assert client.get("/healthz").json() == {"ok": True}
        assert "alertscope_alerts_received_total" in client.get("/metrics/").text
