.PHONY: seed api worker dashboard generate docker stop

seed:
	python -m ingest.knowledge_base

api:
	python -m api.main

worker:
	python -m pipeline.worker

dashboard:
	cd dashboard && npm run dev

generate:
	python -m ingest.generator

docker:
	docker compose up --build

stop:
	docker compose down
