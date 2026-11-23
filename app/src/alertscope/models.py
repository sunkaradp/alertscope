from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field


class Alert(BaseModel):
    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = ""
    fingerprint: str = ""

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "unknown")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "none")

    def key(self) -> str:
        if self.fingerprint:
            return self.fingerprint
        return "|".join(f"{k}={v}" for k, v in sorted(self.labels.items()))

    def expr(self) -> str | None:
        """PromQL expression of the rule, taken from the Prometheus generator URL."""
        if not self.generatorURL:
            return None
        qs = parse_qs(urlparse(self.generatorURL).query)
        for key in ("g0.expr", "expr"):
            if qs.get(key):
                return qs[key][0]
        return None


class AlertmanagerPayload(BaseModel):
    version: str = "4"
    status: str
    receiver: str = ""
    groupKey: str = ""
    alerts: list[Alert]
    commonLabels: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""


class Evidence(BaseModel):
    source: str
    title: str
    body: str


class Analysis(BaseModel):
    alert: str
    severity: str
    labels: dict[str, str]
    summary: str
    likely_cause: str
    confidence: str = "low"
    evidence: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    provider: str = ""
    duration_s: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
