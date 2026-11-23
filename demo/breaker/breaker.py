"""A small service that misbehaves on request, used to demo alertscope.

Modes (env MODE or POST /mode?m=<mode>):
  healthy  - normal
  errors   - ~30% of requests return 500 and log a stack trace
  slow     - requests take 1.5-3s, logs upstream timeouts
  leak     - keeps allocating memory until the container gets OOM killed
  crash    - exits with code 1 after a few seconds (crash loop under k8s)

It generates its own traffic so there's something to alert on without a load tester.
"""

import logging
import os
import random
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("PORT", "8000"))
MODES = {"healthy", "errors", "slow", "leak", "crash"}

logging.basicConfig(
    level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("breaker")

state = {"mode": os.environ.get("MODE", "healthy")}
lock = threading.Lock()
requests_total: dict[str, int] = {}
latency_sum = 0.0
latency_count = 0
hoard: list[bytes] = []


def record(code: int, took: float) -> None:
    global latency_sum, latency_count
    with lock:
        requests_total[str(code)] = requests_total.get(str(code), 0) + 1
        latency_sum += took
        latency_count += 1


def render_metrics() -> str:
    with lock:
        lines = ["# TYPE breaker_http_requests_total counter"]
        for code, n in sorted(requests_total.items()):
            lines.append(f'breaker_http_requests_total{{code="{code}"}} {n}')
        lines += [
            "# TYPE breaker_request_seconds summary",
            f"breaker_request_seconds_sum {latency_sum}",
            f"breaker_request_seconds_count {latency_count}",
            "# TYPE breaker_hoard_bytes gauge",
            f"breaker_hoard_bytes {sum(len(b) for b in hoard)}",
            "# TYPE breaker_mode gauge",
        ]
        lines += [f'breaker_mode{{mode="{m}"}} {int(m == state["mode"])}' for m in sorted(MODES)]
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default access log
        pass

    def _send(self, code: int, body: str, ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/metrics":
            return self._send(200, render_metrics(), "text/plain; version=0.0.4")
        if path == "/healthz":
            return self._send(200, "ok")
        if path == "/api/order":
            return self.order()
        self._send(404, "not found")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/mode":
            return self._send(404, "not found")
        mode = parse_qs(u.query).get("m", [""])[0]
        if mode not in MODES:
            return self._send(400, f"mode must be one of {sorted(MODES)}")
        state["mode"] = mode
        log.warning("mode switched to %s", mode)
        self._send(200, mode)

    def order(self):
        t0 = time.monotonic()
        mode = state["mode"]
        order_id = random.randint(10000, 99999)
        if mode == "slow":
            time.sleep(random.uniform(1.5, 3.0))
            if random.random() < 0.4:
                log.error("order %s: upstream payments-api timed out after 2000ms", order_id)
                record(504, time.monotonic() - t0)
                return self._send(504, "upstream timeout")
        if mode == "errors" and random.random() < 0.3:
            log.error(
                "order %s failed: psycopg.OperationalError: connection to server at "
                "\"orders-db\" (10.0.3.14), port 5432 failed: Connection refused",
                order_id,
            )
            record(500, time.monotonic() - t0)
            return self._send(500, "internal error")
        record(200, time.monotonic() - t0)
        self._send(200, f"order {order_id} ok")


def background():
    started = time.monotonic()
    while True:
        mode = state["mode"]
        if mode == "leak":
            hoard.append(b"x" * 8 * 1024 * 1024)
            size = sum(len(b) for b in hoard) // (1024 * 1024)
            log.info("cache warmup: %d MiB cached", size)
        if mode == "crash" and time.monotonic() - started > 8:
            log.critical("config error: required env ORDERS_DB_URL is not set, exiting")
            os._exit(1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/order", timeout=5).read()
        except Exception:  # noqa: BLE001 - errors are the point here
            pass
        time.sleep(0.5)


if __name__ == "__main__":
    log.info("breaker starting on :%d in mode %s", PORT, state["mode"])
    threading.Thread(target=background, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
