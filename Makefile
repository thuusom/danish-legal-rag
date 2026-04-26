VERSION  := $(shell cat VERSION)
REGISTRY := ghcr.io/thuusom

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

# =============================================================================
# Makefile additions for multi-agent setup
# Append these targets to your existing Makefile. The top of your existing
# Makefile (up and phony declarations) stays as-is.
# =============================================================================

.PHONY: contract contract-verify client frontend-dev frontend-test report

# Dump the live API's OpenAPI spec to contracts/openapi.yaml
# Assumes `make up` and ingestion have completed.
contract:
	@bash scripts/gen-contract.sh

# Verify the committed contract matches the live API — fails if drift detected.
# Intended for CI and pre-merge checks.
contract-verify: contract
	@echo "Contract is in sync."

# Generate the TypeScript client in frontend/src/lib/api/ from the OpenAPI spec.
client:
	@bash scripts/gen-api-client.sh

# Frontend dev workflow (once frontend is scaffolded)
frontend-dev:
	cd frontend && npm run dev

frontend-test:
	cd frontend && npm run check && npm run test && npm run test:e2e

# Ask the PM agent to write today's report (invoked manually)
# Example: claude -p "write today's report" --agent pm
report:
	@echo "Run: claude -p 'Write reports/$$(date +%Y-%m-%d).md covering commits, PRs, and open issues.' --agent pm"

# =============================================================================
# Production targets (GHCR images, docker-compose.prod.yml)
# =============================================================================

.PHONY: prod-build prod-push prod-up prod-down

prod-build:
	docker build -t $(REGISTRY)/danish-legal-rag-api:$(VERSION) -f api/Dockerfile .
	docker build -t $(REGISTRY)/danish-legal-rag-ingest:$(VERSION) -f ingest/Dockerfile .
	docker build -t $(REGISTRY)/danish-legal-rag-frontend:$(VERSION) -f frontend/Dockerfile frontend/

prod-push:
	docker push $(REGISTRY)/danish-legal-rag-api:$(VERSION)
	docker push $(REGISTRY)/danish-legal-rag-ingest:$(VERSION)
	docker push $(REGISTRY)/danish-legal-rag-frontend:$(VERSION)

prod-up:
	IMAGE_TAG=$(VERSION) docker compose -f docker-compose.prod.yml up -d

prod-down:
	docker compose -f docker-compose.prod.yml down
