COMPOSE = docker compose -f deploy/local/docker-compose.yml

.PHONY: dev test lint up down logs break fix fire analyses

dev:
	cd app && python -m venv .venv && .venv/bin/pip install -e '.[dev,all]'

test:
	cd app && pytest -q

lint:
	cd app && ruff check . && ruff format --check .

up:
	$(COMPOSE) up -d --build
	@echo "grafana http://localhost:3000/d/alertscope  prometheus http://localhost:9090"

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f alertscope

# make break MODE=errors|slow|leak|crash
MODE ?= errors
break:
	curl -s -XPOST "localhost:8000/mode?m=$(MODE)"; echo

fix:
	curl -s -XPOST "localhost:8000/mode?m=healthy"; echo

# Skip the wait for Prometheus/Alertmanager and send an alert straight to alertscope
fire:
	sed -e "s/STARTS_AT/$$(date -u +%Y-%m-%dT%H:%M:%SZ)/" -e "s/FINGERPRINT/$$(date +%s)/" \
		scripts/sample-alert.json | curl -s -XPOST localhost:8080/webhook/alertmanager \
		-H 'content-type: application/json' -d @-; echo

analyses:
	curl -s localhost:8080/analyses | python3 -m json.tool
