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

[Unreleased]: https://github.com/thuusom/danish-legal-rag/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/thuusom/danish-legal-rag/releases/tag/v1.0.0
