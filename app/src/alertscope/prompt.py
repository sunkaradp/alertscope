import json
import re

from .models import Alert, Analysis, Evidence

SYSTEM = """You are the first responder for a production Kubernetes platform.
You get one firing alert plus metrics, logs and cluster state collected around it.

Work only from the evidence given. If it doesn't support a conclusion, say so and
set confidence to "low" instead of guessing. Prefer the most specific explanation
the evidence supports (e.g. "memory limit 256Mi, working set hit 255Mi, last exit
OOMKilled" beats "resource issue").

Reply with JSON only, no markdown fences:
{
  "summary": "one or two sentences an on-call engineer can read on a phone",
  "likely_cause": "short phrase",
  "confidence": "low | medium | high",
  "evidence": ["the 2-5 facts from the input that support the cause, quoted or paraphrased"],
  "next_steps": ["concrete checks or commands, most useful first, max 4"]
}"""

MAX_SECTION_CHARS = 3500


def build_prompt(alert: Alert, evidence: list[Evidence]) -> str:
    parts = [
        f"ALERT: {alert.name} (severity {alert.severity}, status {alert.status})",
        f"started: {alert.startsAt.isoformat()}",
        "labels: " + ", ".join(f"{k}={v}" for k, v in sorted(alert.labels.items())),
    ]
    for key in ("summary", "description", "runbook_url"):
        if alert.annotations.get(key):
            parts.append(f"{key}: {alert.annotations[key]}")

    if not evidence:
        parts.append("\nNo metrics, logs or cluster state could be collected.")
    for ev in evidence:
        body = ev.body
        if len(body) > MAX_SECTION_CHARS:
            body = body[:MAX_SECTION_CHARS] + "\n[truncated]"
        parts.append(f"\n### {ev.source}: {ev.title}\n{body}")
    return "\n".join(parts)


_fence = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_reply(text: str, alert: Alert) -> Analysis:
    base = {"alert": alert.name, "severity": alert.severity, "labels": alert.labels}
    cleaned = _fence.sub("", text.strip())
    # Models sometimes add a sentence before the JSON; take the outermost object.
    start, end = cleaned.find("{"), cleaned.rfind("}")
    try:
        data = json.loads(cleaned[start : end + 1])
        return Analysis(
            **base,
            summary=str(data.get("summary", "")).strip() or "No summary returned.",
            likely_cause=str(data.get("likely_cause", "unknown")),
            confidence=str(data.get("confidence", "low")).lower(),
            evidence=[str(x) for x in data.get("evidence", [])][:6],
            next_steps=[str(x) for x in data.get("next_steps", [])][:5],
        )
    except (ValueError, TypeError):
        return Analysis(
            **base,
            summary=text.strip()[:1500] or "Empty reply.",
            likely_cause="unparsed model reply",
        )
