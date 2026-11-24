from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALERTSCOPE_", env_file=".env", extra="ignore")

    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"

    # Alert labels that are also Loki stream labels. The first ones found on an
    # alert are used to build the log selector, e.g. {namespace="x", pod="y"}.
    loki_labels: list[str] = Field(default=["namespace", "pod", "container"])
    loki_max_lines: int = 60

    # How far back from the alert start we look for metrics and logs.
    lookback_minutes: int = 15

    kube_enabled: bool = False

    llm_provider: Literal["bedrock", "vertex", "stub"] = "stub"
    llm_max_tokens: int = 1200
    llm_temperature: float = 0.2

    bedrock_model_id: str = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_region: str = "eu-central-1"

    vertex_project: str = ""
    vertex_location: str = "europe-west4"
    vertex_model: str = "gemini-2.5-flash"

    slack_webhook_url: str = ""

    # Optional shared secret for Alertmanager webhook authentication.
    webhook_token: str = ""

    # Upper bound for in-flight background analyses; overload returns HTTP 503.
    max_pending_tasks: int = Field(default=100, ge=1, le=5000)

    # Mount this path on persistent storage in production.
    database_path: str = "/data/alertscope.db"

    # Don't re-analyse the same alert (by fingerprint) inside this window.
    cooldown_minutes: int = 30
    max_concurrent: int = 4
    analyse_resolved: bool = False
    history_size: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
