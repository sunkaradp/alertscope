import logging
import os

log = logging.getLogger(__name__)


def configure_tracing(app) -> bool:
    """Enable OTLP tracing only when an endpoint is explicitly configured."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint:
        log.info("OpenTelemetry tracing disabled: no OTLP endpoint configured")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        traces_endpoint = endpoint.rstrip("/")
        if not traces_endpoint.endswith("/v1/traces"):
            traces_endpoint += "/v1/traces"
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": os.getenv("OTEL_SERVICE_NAME", "alertscope")}
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        log.info("OpenTelemetry OTLP tracing enabled: %s", traces_endpoint)
        return True
    except ImportError:
        log.warning(
            "OTLP endpoint configured but tracing extras are missing; "
            "install alertscope[otel]"
        )
        return False
