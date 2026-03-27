.PHONY: up down build logs ingest test

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ingest:
	docker compose run --rm ingest

test-integration:
	docker compose exec api python -m pytest /app/tests/test_integration.py -v

test-embeddings:
	docker compose exec api python -m pytest /app/tests/test_embeddings.py -v

curl-test:
	curl -s -X POST http://localhost:8000/ask \
		-H "Content-Type: application/json" \
		-d '{"question": "Hvordan afskrives immaterielle aktiver såsom software skattemæssigt?"}' \
		| python3 -m json.tool
