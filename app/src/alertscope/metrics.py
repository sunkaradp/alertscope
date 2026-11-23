from prometheus_client import Counter, Histogram

ALERTS = Counter(
    "alertscope_alerts_received_total", "Alerts received from Alertmanager", ["status"]
)
SKIPPED = Counter("alertscope_alerts_skipped_total", "Alerts not analysed", ["reason"])
ANALYSES = Counter("alertscope_analyses_total", "Finished analyses", ["result", "confidence"])
DURATION = Histogram(
    "alertscope_analysis_seconds",
    "End-to-end time per alert",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120),
)
LLM_LATENCY = Histogram(
    "alertscope_llm_seconds", "LLM call latency", ["provider"], buckets=(0.5, 1, 2, 5, 10, 20, 40)
)
LLM_TOKENS = Counter("alertscope_llm_tokens_total", "Tokens used", ["provider", "direction"])
COLLECTOR_ERRORS = Counter("alertscope_collector_errors_total", "Collector failures", ["collector"])
