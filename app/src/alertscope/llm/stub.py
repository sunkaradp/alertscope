import json
import re

from .base import LLMResult


class StubProvider:
    """No model at all. Picks a few obvious signals out of the evidence so the
    pipeline can be run locally and in tests without cloud credentials."""

    name = "stub"

    RULES = [
        (
            r"OOMKilled|out of memory|oom",
            "Container is running out of memory",
            "Compare memory working set with the limit; check for a leak or raise the limit.",
        ),
        (
            r"CrashLoopBackOff|Back-off restarting",
            "Container is crash looping",
            "Look at the logs of the previous container: kubectl logs --previous.",
        ),
        (
            r"connection refused|timeout|timed out",
            "A dependency is unreachable or slow",
            "Check the downstream service and its endpoints.",
        ),
        (
            r"\b5\d\d\b|error|exception",
            "Application is returning errors",
            "Check the most recent deploy and the error lines below.",
        ),
    ]

    async def complete(self, system: str, prompt: str) -> LLMResult:
        cause, step = "Not enough signal to say", "Look at the dashboards for this service."
        for pattern, c, s in self.RULES:
            if re.search(pattern, prompt, re.IGNORECASE):
                cause, step = c, s
                break
        evidence = [
            ln.strip()
            for ln in prompt.splitlines()
            if re.search(r"error|oom|refused|restarts|max", ln, re.I)
        ][:4]
        body = {
            "summary": f"{cause} (heuristic, no LLM configured).",
            "likely_cause": cause,
            "confidence": "low",
            "evidence": evidence,
            "next_steps": [step],
        }
        return LLMResult(json.dumps(body))
