import asyncio
import logging
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Protocol

from . import events, metrics, prompt
from .llm import LLMProvider
from .models import Alert, Analysis, Evidence

log = logging.getLogger(__name__)


class Collector(Protocol):
    async def collect(self, alert: Alert, now: datetime) -> list[Evidence]: ...


class Cooldown:
    def __init__(self, window: timedelta):
        self.window = window
        self.seen: dict[str, datetime] = {}

    def allow(self, key: str, now: datetime) -> bool:
        last = self.seen.get(key)
        if last and now - last < self.window:
            return False
        self.seen[key] = now
        # keep the dict from growing forever
        if len(self.seen) > 5000:
            cutoff = now - self.window
            self.seen = {k: v for k, v in self.seen.items() if v > cutoff}
        return True


class Pipeline:
    def __init__(
        self,
        collectors: dict[str, Collector],
        llm: LLMProvider,
        notify,
        cooldown: timedelta,
        max_concurrent: int,
        history_size: int,
        analyse_resolved: bool = False,
    ):
        self.collectors = collectors
        self.llm = llm
        self.notify = notify
        self.cooldown = Cooldown(cooldown)
        self.sem = asyncio.Semaphore(max_concurrent)
        self.history: deque[Analysis] = deque(maxlen=history_size)
        self.analyse_resolved = analyse_resolved

    def accept(self, alert: Alert) -> bool:
        metrics.ALERTS.labels(alert.status).inc()
        if alert.status != "firing" and not self.analyse_resolved:
            metrics.SKIPPED.labels("resolved").inc()
            return False
        if not self.cooldown.allow(alert.key(), datetime.now(UTC)):
            metrics.SKIPPED.labels("cooldown").inc()
            return False
        return True

    async def gather(self, alert: Alert, now: datetime) -> list[Evidence]:
        names = list(self.collectors)
        results = await asyncio.gather(
            *(self.collectors[n].collect(alert, now) for n in names), return_exceptions=True
        )
        evidence: list[Evidence] = []
        for name, res in zip(names, results, strict=True):
            if isinstance(res, BaseException):
                metrics.COLLECTOR_ERRORS.labels(name).inc()
                log.warning("collector %s failed: %s", name, res)
                continue
            evidence.extend(res)
        return evidence

    async def analyse(self, alert: Alert) -> Analysis:
        async with self.sem:
            t0 = time.monotonic()
            now = datetime.now(UTC)
            evidence = await self.gather(alert, now)
            text = prompt.build_prompt(alert, evidence)

            t1 = time.monotonic()
            try:
                result = await self.llm.complete(prompt.SYSTEM, text)
            except Exception as exc:
                metrics.ANALYSES.labels("llm_error", "none").inc()
                log.exception("llm call failed for %s", alert.name)
                analysis = Analysis(
                    alert=alert.name,
                    severity=alert.severity,
                    labels=alert.labels,
                    summary=f"LLM call failed ({type(exc).__name__}). "
                    f"Collected {len(evidence)} evidence blocks.",
                    likely_cause="unknown",
                    provider=self.llm.name,
                )
            else:
                metrics.LLM_LATENCY.labels(self.llm.name).observe(time.monotonic() - t1)
                metrics.LLM_TOKENS.labels(self.llm.name, "input").inc(result.input_tokens)
                metrics.LLM_TOKENS.labels(self.llm.name, "output").inc(result.output_tokens)
                analysis = prompt.parse_reply(result.text, alert)
                analysis.provider = self.llm.name
                metrics.ANALYSES.labels("ok", analysis.confidence).inc()

            analysis.duration_s = time.monotonic() - t0
            metrics.DURATION.observe(analysis.duration_s)
            self.history.appendleft(analysis)
            events.emit(analysis)
            try:
                await self.notify(analysis)
            except Exception:
                log.exception("notify failed")
            return analysis
