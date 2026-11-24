import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import partial

import httpx
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import make_asgi_app

from . import __version__, slack
from .collectors import LokiCollector, PrometheusCollector
from .config import Settings, get_settings
from .llm import build_provider
from .models import AlertmanagerPayload, Analysis
from .pipeline import Pipeline
from .storage import IncidentStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("alertscope")


def build_pipeline(settings: Settings, http: httpx.AsyncClient, store=None) -> Pipeline:
    lookback = timedelta(minutes=settings.lookback_minutes)
    collectors = {
        "prometheus": PrometheusCollector(settings.prometheus_url, http, lookback),
        "loki": LokiCollector(
            settings.loki_url, http, lookback, settings.loki_labels, settings.loki_max_lines
        ),
    }
    if settings.kube_enabled:
        from .collectors import KubeCollector

        collectors["kubernetes"] = KubeCollector()

    return Pipeline(
        collectors=collectors,
        llm=build_provider(settings),
        notify=partial(slack.post, http, settings.slack_webhook_url),
        cooldown=timedelta(minutes=settings.cooldown_minutes),
        max_concurrent=settings.max_concurrent,
        history_size=settings.history_size,
        analyse_resolved=settings.analyse_resolved,
        store=store,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as http:
        app.state.store = IncidentStore(settings.database_path)
        app.state.pipeline = build_pipeline(settings, http, app.state.store)
        app.state.settings = settings
        app.state.tasks = set()
        log.info("alertscope %s started, llm=%s", __version__, settings.llm_provider)
        yield
        if app.state.tasks:
            await asyncio.wait(app.state.tasks, timeout=30)


app = FastAPI(title="alertscope", version=__version__, lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz(request: Request):
    if not getattr(request.app.state, "pipeline", None):
        raise HTTPException(status_code=503, detail="service is not initialized")
    return {"ready": True}


@app.post("/webhook/alertmanager", status_code=202)
async def alertmanager(payload: AlertmanagerPayload, request: Request):
    # Alertmanager times out after 10s by default, so answer straight away and
    # do the work in the background.
    settings: Settings = request.app.state.settings
    if settings.webhook_token:
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {settings.webhook_token}"
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid webhook credentials")

    pipeline: Pipeline = request.app.state.pipeline
    tasks = request.app.state.tasks
    if len(tasks) + len(payload.alerts) > settings.max_pending_tasks:
        raise HTTPException(status_code=503, detail="analysis queue is full; retry later")
    queued = 0
    for alert in payload.alerts:
        if not pipeline.accept(alert):
            continue
        task = asyncio.create_task(pipeline.analyse(alert))
        request.app.state.tasks.add(task)
        task.add_done_callback(request.app.state.tasks.discard)
        queued += 1
    return {"received": len(payload.alerts), "queued": queued}


@app.get("/incidents")
async def incidents(request: Request, limit: int = 100):
    return request.app.state.store.list_incidents(limit)

@app.get("/incidents/{incident_id}")
async def incident_detail(incident_id: str, request: Request):
    incident = request.app.state.store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident

@app.post("/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(incident_id: str, request: Request):
    incident = request.app.state.store.acknowledge(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident

@app.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str, request: Request):
    incident = request.app.state.store.resolve(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident

@app.get("/analyses", response_model=list[Analysis])
async def analyses(request: Request, limit: int = 20):
    return list(request.app.state.pipeline.history)[:limit]


def run() -> None:
    import uvicorn

    uvicorn.run("alertscope.main:app", host="0.0.0.0", port=8080, access_log=False)
