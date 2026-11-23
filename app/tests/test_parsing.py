import json

from alertscope.collectors.loki import _dedupe, build_selector
from alertscope.collectors.prometheus import summarise_matrix
from alertscope.prompt import build_prompt, parse_reply


def test_expr_from_generator_url(alert):
    assert alert.expr() == "increase(kube_pod_container_status_restarts_total[5m]) > 0"


def test_selector_uses_known_labels_in_order(alert):
    sel = build_selector(alert.labels, ["namespace", "pod", "job"])
    assert sel == '{namespace="shop", pod="checkout-7d9f8-abcde"}'
    assert build_selector({"foo": "bar"}, ["namespace"]) is None


def test_selector_escapes_quotes():
    assert build_selector({"app": 'a"b'}, ["app"]) == '{app="a\\"b"}'


def test_dedupe_collapses_lines_that_differ_only_in_numbers():
    lines = ["retry 1 failed", "retry 2 failed", "retry 3 failed", "giving up"]
    assert _dedupe(lines) == ["retry 1 failed  [x3]", "giving up"]


def test_summarise_matrix_trend():
    result = [
        {"metric": {"__name__": "x", "pod": "a"}, "values": [[0, "100"], [1, "150"], [2, "240"]]}
    ]
    out = summarise_matrix(result)
    assert "pod=a" in out and "max 240" in out and "rising" in out
    assert summarise_matrix([]) == "no data"


def test_parse_reply_handles_fences_and_preamble(alert):
    body = {
        "summary": "OOM",
        "likely_cause": "memory limit too low",
        "confidence": "High",
        "evidence": ["limit 256Mi"],
        "next_steps": ["raise limit"],
    }
    text = "Here you go:\n```json\n" + json.dumps(body) + "\n```"
    a = parse_reply(text, alert)
    assert a.likely_cause == "memory limit too low"
    assert a.confidence == "high"
    assert a.next_steps == ["raise limit"]


def test_parse_reply_falls_back_to_raw_text(alert):
    a = parse_reply("the pod is fine i think", alert)
    assert a.summary == "the pod is fine i think"
    assert a.likely_cause == "unparsed model reply"


def test_prompt_truncates_large_sections(alert):
    from alertscope.models import Evidence

    ev = [Evidence(source="loki", title="lines", body="x" * 10_000)]
    p = build_prompt(alert, ev)
    assert "[truncated]" in p
    assert len(p) < 5000
