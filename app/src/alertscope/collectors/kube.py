import asyncio
import logging

from ..models import Alert, Evidence

log = logging.getLogger(__name__)


class KubeCollector:
    """Pod status and recent events, read with the in-cluster service account."""

    def __init__(self) -> None:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.core = client.CoreV1Api()

    def _pod_status(self, ns: str, pod: str) -> str:
        p = self.core.read_namespaced_pod(pod, ns)
        lines = [f"phase: {p.status.phase}, node: {p.spec.node_name}"]
        for cs in p.status.container_statuses or []:
            state = "running"
            if cs.state.waiting:
                state = f"waiting ({cs.state.waiting.reason})"
            elif cs.state.terminated:
                term = cs.state.terminated
                state = f"terminated ({term.reason}, exit {term.exit_code})"
            last = ""
            if cs.last_state and cs.last_state.terminated:
                t = cs.last_state.terminated
                last = f", last exit: {t.reason} code {t.exit_code}"
            lines.append(f"{cs.name}: {state}, restarts {cs.restart_count}{last}")
        for c in p.spec.containers:
            res = c.resources
            lines.append(
                f"{c.name} resources: requests={res.requests or {}} limits={res.limits or {}}"
            )
        return "\n".join(lines)

    def _events(self, ns: str, pod: str) -> str:
        evs = self.core.list_namespaced_event(ns, field_selector=f"involvedObject.name={pod}").items
        evs.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp)
        lines = [f"{e.type} {e.reason}: {e.message} (x{e.count or 1})" for e in evs[-15:]]
        return "\n".join(lines)

    async def collect(self, alert: Alert, now=None) -> list[Evidence]:
        ns, pod = alert.labels.get("namespace"), alert.labels.get("pod")
        if not (ns and pod):
            return []
        out = []
        try:
            status = await asyncio.to_thread(self._pod_status, ns, pod)
            out.append(Evidence(source="kubernetes", title=f"pod {ns}/{pod}", body=status))
            events = await asyncio.to_thread(self._events, ns, pod)
            if events:
                out.append(Evidence(source="kubernetes", title="events", body=events))
        except Exception as exc:  # noqa: BLE001 - pod may already be gone
            log.info("kube lookup for %s/%s failed: %s", ns, pod, exc)
        return out
