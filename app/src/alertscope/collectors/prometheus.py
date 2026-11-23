import logging
from datetime import datetime, timedelta

import httpx

from ..models import Alert, Evidence

log = logging.getLogger(__name__)

MAX_SERIES = 5

# Extra queries that are worth running when the alert points at a pod.
POD_QUERIES = {
    "container restarts": "sum by (container) (kube_pod_container_status_restarts_total{%s})",
    "last terminated reason": "kube_pod_container_status_last_terminated_reason{%s} == 1",
    "memory working set (MiB)": (
        'sum by (container) (container_memory_working_set_bytes{%s, container!=""}) / 1048576'
    ),
    "memory limit (MiB)": (
        'sum by (container) (kube_pod_container_resource_limits{%s, resource="memory"}) / 1048576'
    ),
    "cpu cores": (
        'sum by (container) (rate(container_cpu_usage_seconds_total{%s, container!=""}[5m]))'
    ),
}


def _fmt(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:.2f}"
    return f"{v:.4g}"


def summarise_matrix(result: list[dict]) -> str:
    """Reduce a range-query result to one line per series: min / max / last and direction."""
    if not result:
        return "no data"
    lines = []
    for series in result[:MAX_SERIES]:
        metric = {k: v for k, v in series.get("metric", {}).items() if k != "__name__"}
        values = [float(v) for _, v in series.get("values", []) if v not in ("NaN", "+Inf", "-Inf")]
        name = ", ".join(f"{k}={v}" for k, v in sorted(metric.items())) or "value"
        if not values:
            lines.append(f"{name}: no numeric samples")
            continue
        first, last = values[0], values[-1]
        if last > first * 1.1:
            trend = "rising"
        elif last < first * 0.9:
            trend = "falling"
        else:
            trend = "flat"
        lines.append(
            f"{name}: min {_fmt(min(values))}, max {_fmt(max(values))}, "
            f"last {_fmt(last)} ({trend}, {len(values)} samples)"
        )
    if len(result) > MAX_SERIES:
        lines.append(f"... {len(result) - MAX_SERIES} more series not shown")
    return "\n".join(lines)


def summarise_vector(result: list[dict]) -> str:
    if not result:
        return "no data"
    lines = []
    for series in result[:MAX_SERIES]:
        metric = {k: v for k, v in series.get("metric", {}).items() if k != "__name__"}
        name = ", ".join(f"{k}={v}" for k, v in sorted(metric.items())) or "value"
        lines.append(f"{name}: {_fmt(float(series['value'][1]))}")
    return "\n".join(lines)


class PrometheusCollector:
    def __init__(self, base_url: str, client: httpx.AsyncClient, lookback: timedelta):
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.lookback = lookback

    async def _get(self, path: str, params: dict) -> list[dict]:
        resp = await self.client.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(body.get("error", "query failed"))
        return body["data"]["result"]

    async def query_range(self, query: str, start: datetime, end: datetime) -> list[dict]:
        span = max((end - start).total_seconds(), 60)
        step = max(int(span // 60), 15)
        return await self._get(
            "/api/v1/query_range",
            {"query": query, "start": start.timestamp(), "end": end.timestamp(), "step": step},
        )

    async def query(self, query: str, at: datetime) -> list[dict]:
        return await self._get("/api/v1/query", {"query": query, "time": at.timestamp()})

    async def collect(self, alert: Alert, now: datetime) -> list[Evidence]:
        start = alert.startsAt - self.lookback
        evidence: list[Evidence] = []

        expr = alert.expr()
        if expr:
            try:
                result = await self.query_range(expr, start, now)
                evidence.append(
                    Evidence(
                        source="prometheus",
                        title=f"alert expression: {expr}",
                        body=summarise_matrix(result),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad query shouldn't stop the rest
                log.warning("alert expr query failed: %s", exc)

        ns, pod = alert.labels.get("namespace"), alert.labels.get("pod")
        if ns and pod:
            for title, tmpl in POD_QUERIES.items():
                q = tmpl % f'namespace="{ns}", pod="{pod}"'
                try:
                    result = await self.query(q, now)
                except Exception as exc:  # noqa: BLE001
                    log.debug("pod query %r failed: %s", title, exc)
                    continue
                if result:
                    evidence.append(
                        Evidence(source="prometheus", title=title, body=summarise_vector(result))
                    )
        return evidence
