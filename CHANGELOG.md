# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [1.1.0] - 2026-04-28


### Added

- Live law fetcher service (`ingest/law_fetcher.py`) that pulls structured
  law content from retsinformation-api.dk and detects upstream version
  changes. Update-only model: in-repo JSON files remain the first-boot
  seed (see ADR-003, ADR-004).
- `ingest/sources.yaml` manifest declaring the 12 law sources with their
  retsinformation `(year, number)` coordinates and seed file paths.
- `law_cache` Docker volume backing the live cache.
- Six provenance fields on every chunk: `ingested_at`, `law_version_date`,
  `law_version_number`, `eli`, `retsinformation_law_id`,
  `retsinformation_paragraph_id`.
- Idempotent re-ingestion via per-law `delete_chunks_by_law_code` so
  removed paragraphs disappear from search instead of becoming orphans
  (see ADR-005).
- `/admin/status` and `/admin/check-currency` API endpoints exposing
  corpus state, fetcher rate-limit counters, and ingestion status.
- `/admin` SvelteKit page with status table, rate-limit chips, and
  "Pull updates now" button.
- Daily GitHub Actions workflow (`check-law-currency.yml`) at 06:00 UTC
  that auto-opens `Stale law: ...` issues when upstream drifts and
  auto-closes them when the local cache catches up.
- Release agent persona (`.claude/agents/release.md`) plus tooling:
  `make release-{major,minor,patch,dry,prepare,notes}`,
  `scripts/release.sh`, `CHANGELOG.md`, and tag-triggered
  `.github/workflows/release.yml` that builds and publishes images to
  GHCR (see ADR-006).
- `human.md` documenting the human-AI dialogue model and the explicit
  approval gates agents must request from humans.
- README "How this project is built" section + automation status table
  making the only autonomous component (daily currency check) explicit.
- `docs/github-workflows.md` documenting every workflow.
- `docs/release-process.md` operator runbook.
- ADRs 003 (retsinformation-api.dk as primary source), 004 (update-only
  fetcher with seed), 005 (idempotent re-ingestion), 006 (tag-driven
  release with human-in-the-loop).
- Tier-1 corpus expansion to 12 sources (added the three
  bekendtgørelser) with 398 seed provisions.

### Changed

- `Makefile`: new `fetch-laws`, `fetch-laws-dry`, `fetch-laws-force`
  targets for triggering the live fetcher inside the ingest container,
  plus `release-*` targets owned by the release agent.
- `CLAUDE.md`: adds the release agent role, ownership for VERSION,
  CHANGELOG, release.yml, release-process.md, and `scripts/release.sh`,
  plus the "Where decisions live" three-tier model and the PR
  auto-close syntax requirement.
- README and project docs translated to fully English. UI copy in the
  frontend remains Danish (target user).

### Fixed

- `scripts/release.sh` CHANGELOG promotion no longer strips section
  scaffolding from `[Unreleased]` (Issue #39).

## [1.0.0] - 2026-04-26

First production release of the Danish Legal RAG system: a chat application
for Danish tax and accounting law backed by retrieval-augmented generation.

### Added

- SvelteKit + TypeScript + Tailwind chat frontend with streaming SSE responses
  (token-by-token via `/ask/stream`).
- Session history with `localStorage` persistence and law filter dropdown.
- Markdown rendering with table support and collapsible legal references
  linking out to retsinformation.dk.
- Mobile-responsive layout with safe-area handling.
- Server-side API proxy so the backend is not exposed to the browser.
- FastAPI backend with four LLM providers: Anthropic (Claude), OpenAI, Ollama,
  and mock.
- Dense vector search via sentence-transformers
  (`paraphrase-multilingual-mpnet-base-v2`).
- Hybrid search infrastructure: dense + BM25 sparse via fastembed with RRF
  fusion.
- HTTP endpoints: `/ask`, `/ask/stream`, `/search`, `/laws`, `/health`.
- MCP server for Claude Desktop integration.
- Initial legal corpus of 12 sources / 398 provisions: Afskrivningsloven,
  Årsregnskabsloven, Bogføringsloven, Selskabsskatteloven, Momsloven,
  Ligningsloven, Skattekontrolloven, Revisorloven, Skatteforvaltningsloven,
  Bogføringsbekendtgørelsen, Mindstekravsbekendtgørelsen, and
  Momsbekendtgørelsen.
- GitHub Actions CI: backend unit tests, frontend lint, integration tests.
- Production `docker-compose.prod.yml` using GHCR images with network
  isolation.
- OpenAPI contract (`contracts/openapi.yaml`) as the source of truth between
  frontend and backend.
- Published Docker images:
  `ghcr.io/thuusom/danish-legal-rag-api:1.0.0`,
  `ghcr.io/thuusom/danish-legal-rag-ingest:1.0.0`,
  `ghcr.io/thuusom/danish-legal-rag-frontend:1.0.0`.

[Unreleased]: https://github.com/thuusom/danish-legal-rag/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/thuusom/danish-legal-rag/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/thuusom/danish-legal-rag/releases/tag/v1.0.0
