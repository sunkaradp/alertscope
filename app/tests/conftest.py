from datetime import UTC, datetime, timedelta

import pytest

from alertscope.models import Alert


@pytest.fixture
def alert() -> Alert:
    return Alert(
        status="firing",
        labels={
            "alertname": "PodOOMKilled",
            "severity": "critical",
            "namespace": "shop",
            "pod": "checkout-7d9f8-abcde",
            "container": "app",
        },
        annotations={"summary": "checkout was OOM killed"},
        startsAt=datetime.now(UTC) - timedelta(minutes=3),
        generatorURL="http://prometheus:9090/graph?g0.expr=increase%28kube_pod_container_status_restarts_total%5B5m%5D%29+%3E+0&g0.tab=1",
        fingerprint="abc123",
    )
