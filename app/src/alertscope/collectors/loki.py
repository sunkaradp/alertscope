import logging
import re
from datetime import datetime, timedelta

import httpx

from ..models import Alert, Evidence

log = logging.getLogger(__name__)

ERROR_PATTERN = "(?i)(error|exception|fatal|panic|fail|oom|killed|timeout|refused)"


def build_selector(labels: dict[str, str], keys: list[str]) -> str | None:
    parts = [f'{k}="{_escape(labels[k])}"' for k in keys if labels.get(k)]
    if not parts:
        return None
    return "{" + ", ".join(parts) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


_ts_noise = re.compile(r"^\S+T\S+Z\s+")


def _clean(line: str, limit: int = 400) -> str:
    line = _ts_noise.sub("", line.strip())
    return line if len(line) <= limit else line[:limit] + " ..."


class LokiCollector:
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient,
        lookback: timedelta,
        label_keys: list[str],
        max_lines: int,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.lookback = lookback
        self.label_keys = label_keys
        self.max_lines = max_lines

    async def _query(self, logql: str, start: datetime, end: datetime, limit: int) -> list[str]:
        resp = await self.client.get(
            f"{self.base_url}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": int(start.timestamp() * 1e9),
                "end": int(end.timestamp() * 1e9),
                "limit": limit,
                "direction": "backward",
            },
        )
        resp.raise_for_status()
        entries: list[tuple[str, str]] = []
        for stream in resp.json()["data"]["result"]:
            entries.extend((ts, line) for ts, line in stream["values"])
        entries.sort(key=lambda e: e[0])
        return [_clean(line) for _, line in entries]

    async def collect(self, alert: Alert, now: datetime) -> list[Evidence]:
        selector = build_selector(alert.labels, self.label_keys)
        if not selector:
            return []
        start = alert.startsAt - self.lookback
        evidence = []
        try:
            errors = await self._query(
                f'{selector} |~ "{ERROR_PATTERN}"', start, now, self.max_lines
            )
            if errors:
                evidence.append(
                    Evidence(
                        source="loki",
                        title=f"error-looking lines {selector}",
                        body="\n".join(_dedupe(errors)),
                    )
                )
            # Always include the most recent lines too; the cause is often just before the error.
            recent = await self._query(selector, start, now, 20)
            if recent:
                evidence.append(
                    Evidence(
                        source="loki", title=f"latest lines {selector}", body="\n".join(recent)
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("loki query failed for %s: %s", selector, exc)
        return evidence


def _dedupe(lines: list[str]) -> list[str]:
    """Collapse repeated lines so a crash loop doesn't eat the whole prompt."""
    first: dict[str, str] = {}
    counts: dict[str, int] = {}
    for line in lines:
        key = _digits.sub("N", line)
        if key not in first:
            first[key] = line
        counts[key] = counts.get(key, 0) + 1
    return [line if counts[k] == 1 else f"{line}  [x{counts[k]}]" for k, line in first.items()]


_digits = re.compile(r"\d+")
