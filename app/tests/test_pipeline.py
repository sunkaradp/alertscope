from datetime import timedelta

import httpx
import pytest
import respx

from alertscope.collectors import LokiCollector, PrometheusCollector
from alertscope.llm.base import LLMResult
from alertscope.llm.stub import StubProvider
from alertscope.models import Evidence
from alertscope.pipeline import Pipeline


class FakeCollector:
    def __init__(self, evidence=None, fail=False):
        self.evidence = evidence or []
        self.fail = fail

    async def collect(self, alert, now):
        if self.fail:
            raise RuntimeError("boom")
        return self.evidence


class BrokenLLM:
    name = "broken"

    async def complete(self, system, prompt):
        raise TimeoutError()


def make(collectors, llm=None):
    sent = []

    async def notify(a):
        sent.append(a)

    p = Pipeline(collectors, llm or StubProvider(), notify, timedelta(minutes=30), 2, 10)
    return p, sent


async def test_analysis_survives_a_failing_collector(alert):
    ev = Evidence(source="kubernetes", title="pod", body="app: terminated (OOMKilled, exit 137)")
    p, sent = make({"good": FakeCollector([ev]), "bad": FakeCollector(fail=True)})
    a = await p.analyse(alert)
    assert "memory" in a.likely_cause
    assert sent == [a]
    assert p.history[0] is a


async def test_llm_failure_still_notifies(alert):
    p, sent = make({}, BrokenLLM())
    a = await p.analyse(alert)
    assert "LLM call failed" in a.summary
    assert len(sent) == 1


def test_cooldown_and_resolved(alert):
    p, _ = make({})
    assert p.accept(alert) is True
    assert p.accept(alert) is False  # same fingerprint inside the window
    resolved = alert.model_copy(update={"status": "resolved", "fingerprint": "other"})
    assert p.accept(resolved) is False


@respx.mock
async def test_collectors_against_fake_backends(alert):
    respx.get("http://prom/api/v1/query_range").respond(
        json={
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [{"metric": {"container": "app"}, "values": [[1, "0"], [2, "3"]]}],
            },
        }
    )
    respx.get("http://prom/api/v1/query").respond(
        json={
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {"container": "app"}, "value": [2, "254.5"]}],
            },
        }
    )
    respx.get("http://loki/loki/api/v1/query_range").respond(
        json={
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"pod": "x"},
                        "values": [["2", "java.lang.OutOfMemoryError"], ["1", "starting"]],
                    }
                ],
            },
        }
    )
    async with httpx.AsyncClient() as http:
        prom = PrometheusCollector("http://prom", http, timedelta(minutes=5))
        loki = LokiCollector("http://loki", http, timedelta(minutes=5), ["namespace", "pod"], 50)
        p, _ = make({"prometheus": prom, "loki": loki})
        evidence = await p.gather(alert, alert.startsAt + timedelta(minutes=3))

    sources = [e.source for e in evidence]
    assert sources.count("prometheus") >= 2
    assert any("OutOfMemoryError" in e.body for e in evidence)


@pytest.mark.parametrize(
    "reply,cause",
    [
        ('{"summary":"s","likely_cause":"disk full","confidence":"medium"}', "disk full"),
    ],
)
async def test_tokens_and_provider_recorded(alert, reply, cause):
    class OneShot:
        name = "fake"

        async def complete(self, system, prompt):
            return LLMResult(reply, 100, 20)

    p, _ = make({}, OneShot())
    a = await p.analyse(alert)
    assert a.likely_cause == cause
    assert a.provider == "fake"


async def test_analysis_is_logged_as_one_json_line(alert, capsys):
    import json

    p, _ = make({})
    await p.analyse(alert)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    event = json.loads(lines[-1])
    assert event["event"] == "analysis"
    assert event["pod"] == "checkout-7d9f8-abcde"
    assert isinstance(event["next_steps_text"], str)
