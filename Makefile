.PHONY: api worker dashboard generate docker stop dev

PYTHON := $(CURDIR)/.venv/bin/python

api:
	"$(PYTHON)" -m api.main

worker:
	"$(PYTHON)" -m pipeline.worker

dashboard:
	cd dashboard && npm run dev

generate:
	"$(PYTHON)" -m ingest.generator

docker:
	docker compose up --build

stop:
	docker compose down

dev:
	@echo "Starting api, worker, dashboard — Ctrl+C to stop all"
	@trap 'kill 0' EXIT INT TERM; \
	"$(PYTHON)" -m api.main & \
	"$(PYTHON)" -m pipeline.worker & \
	(cd dashboard && npm run dev) & \
	wait
