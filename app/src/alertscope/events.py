"""One JSON line per finished analysis on stdout.

The log collector ships it to Loki, and the Grafana dashboard reads it with
{container="alertscope"} | json | event="analysis". Plain JSON with no prefix so
Loki's json parser works on it. Lists are also written joined, because Loki's
json parser skips arrays.
"""

import json
import sys

from .models import Analysis


def to_event(a: Analysis) -> dict:
    return {
        "event": "analysis",
        "ts": a.created_at.isoformat(),
        "alert": a.alert,
        "severity": a.severity,
        "namespace": a.labels.get("namespace", ""),
        "pod": a.labels.get("pod", ""),
        "likely_cause": a.likely_cause,
        "confidence": a.confidence,
        "summary": a.summary,
        "evidence": a.evidence,
        "next_steps": a.next_steps,
        "evidence_text": " | ".join(a.evidence),
        "next_steps_text": " | ".join(a.next_steps),
        "provider": a.provider,
        "duration_s": round(a.duration_s, 2),
    }


def emit(a: Analysis) -> None:
    print(json.dumps(to_event(a), ensure_ascii=False), file=sys.stdout, flush=True)
