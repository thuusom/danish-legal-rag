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

.PHONY: fetch-laws fetch-laws-dry fetch-laws-force

fetch-laws:
	docker compose run --rm ingest python -m ingest.law_fetcher

fetch-laws-dry:
	docker compose run --rm ingest python -m ingest.law_fetcher --dry-run

fetch-laws-force:
	docker compose run --rm ingest python -m ingest.law_fetcher --force

test-integration:
	docker compose exec api python -m pytest /app/tests/test_integration.py -v

test-embeddings:
	docker compose exec api python -m pytest /app/tests/test_embeddings.py -v

# Run the full backend test suite with coverage reporting.
# Coverage is informational for now (no thresholds, no CI gating) — see
# docs/test-strategy.md for the current baseline and policy.
# Artifacts (coverage.xml, .coverage) are written inside the api container
# at /app and are not bind-mounted to the host.
coverage:
	docker compose exec api python -m pytest /app/tests/ \
		--cov=api --cov=ingest --cov=shared --cov=mcp \
		--cov-report=term --cov-report=xml

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

# =============================================================================
# Release targets — bump VERSION, update compose + CHANGELOG, commit.
# Never tag, never push. The human runs `git push origin vX.Y.Z` after merge.
# =============================================================================

.PHONY: release-major release-minor release-patch release-rc release-dry release-notes

release-major:
	@./scripts/release.sh major

release-minor:
	@./scripts/release.sh minor

release-patch:
	@./scripts/release.sh patch

# Bump to next release candidate. From a final X.Y.Z this defaults to a
# minor pre-release (X.(Y+1).0-rc.1); override with RC_LEVEL=major|patch.
# From X.Y.Z-rc.N, bumps to X.Y.Z-rc.(N+1).
release-rc:
	@./scripts/release.sh rc

# Dry-run preview. Default level is patch; override with LEVEL=major|minor|rc.
# Example: make release-dry LEVEL=rc
release-dry:
	@./scripts/release.sh dry $(LEVEL)

# Markdown bullet list of commits since the last tag — used to fill CHANGELOG
# `[Unreleased]` before running release-{major,minor,patch}.
release-notes:
	@git log $$(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --pretty=format:"- %s" --no-merges

# =============================================================================
# Test environment deploy targets — SSH to the test host, deploy a pre-release.
# Requires TEST_HOST and IMAGE_TAG env vars; reads .env.test from repo root.
# See scripts/deploy-test.sh for full behavior.
# =============================================================================

.PHONY: deploy-test deploy-test-down deploy-test-reset

deploy-test:
	@./scripts/deploy-test.sh up

deploy-test-down:
	@./scripts/deploy-test.sh down

deploy-test-reset:
	@./scripts/deploy-test.sh reset
