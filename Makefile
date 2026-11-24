COMPOSE = docker compose -f deploy/local/docker-compose.yml
TOKEN ?=
AUTH_HEADER = -H "Authorization: Bearer $(TOKEN)"

.PHONY: dev test lint up down clean logs break fix fire analyses

dev:
	cd app && python -m venv .venv && .venv/bin/pip install -e '.[dev,all]'

test:
	cd app && pytest -q

lint:
	cd app && ruff check . && ruff format --check .

up:
	$(COMPOSE) up -d --build
	@echo "AlertScope console http://localhost:8080"
	@echo "Grafana http://localhost:3000/d/alertscope (admin / local-alertscope-password)"

down:
	$(COMPOSE) down

# Explicitly remove persisted incident and trace data.
clean:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f alertscope

# make break MODE=errors|slow|leak|crash
MODE ?= errors
break:
	curl -s -XPOST "localhost:8000/mode?m=$(MODE)"; echo

fix:
	curl -s -XPOST "localhost:8000/mode?m=healthy"; echo

# Skip the wait for Prometheus/Alertmanager and send a labelled demo alert.
fire:
	sed -e "s/STARTS_AT/$$(date -u +%Y-%m-%dT%H:%M:%SZ)/" -e "s/FINGERPRINT/$$(date +%s)/" \
		scripts/sample-alert.json | curl -s -XPOST localhost:8080/webhook/alertmanager \
		-H 'content-type: application/json' $(AUTH_HEADER) -d @-; echo

analyses:
	curl -s localhost:8080/analyses $(AUTH_HEADER) | python3 -m json.tool
