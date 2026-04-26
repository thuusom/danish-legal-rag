# Plan: Production-Ready Docker Setup

**Date:** 2026-04-26
**Branch:** `feat/tier1-bekendtgoerelser`
**Status:** Draft — awaiting approval before filing sub-issues

---

## Context and motivation

The stack runs via a single `docker-compose.yml` for local dev. It exposes
Qdrant (6333/6334) and the API (8000) directly on the host. There is no Docker
image for the frontend (it runs bare-metal via `npm run dev`), no production
compose, no version-tagged images, and no network isolation.

## Key design decision: adapter-node over adapter-static

The frontend uses `@sveltejs/adapter-static` today. For server-side API
proxying (especially SSE streaming from `/ask/stream`), we need
`@sveltejs/adapter-node`.

| Option | Pros | Cons |
|--------|------|------|
| adapter-static + nginx | Tiny image (~25 MB), simple | Cannot proxy SSE reliably without custom buffering config. No path to SvelteKit server hooks for future auth/middleware. |
| adapter-node | Native Node.js streaming, SvelteKit server routes handle the proxy, single container | Slightly larger image (~180 MB), but API image is already ~1.2 GB |

**Decision:** adapter-node.

---

## Issues

### Issue A — Frontend Dockerfile and adapter-node migration

- **Owner:** frontend
- **Dependencies:** none
- **Labels:** frontend, infra

**Scope:**

- Replace `@sveltejs/adapter-static` with `@sveltejs/adapter-node` in `package.json` and `svelte.config.js`
- Remove `prerender = true` and `ssr = false` from layout (adapter-node handles SSR)
- Create `frontend/Dockerfile`: multi-stage build with `node:22-alpine`, expose port 3000
- Verify build, check, and tests still pass

**Acceptance criteria:**

- [ ] `docker build -f frontend/Dockerfile frontend/` succeeds
- [ ] Image serves the app on port 3000
- [ ] `npm run check` and `npm run test` pass
- [ ] Image under 300 MB

---

### Issue B — Server-side API proxy in SvelteKit

- **Owner:** frontend
- **Dependencies:** Issue A
- **Labels:** frontend

**Scope:**

- Add catch-all route `frontend/src/routes/api/[...path]/+server.ts` that proxies to `http://api:8000/[...path]`
- Must stream responses (SSE cannot be buffered)
- Add `API_INTERNAL_URL` env var for the backend address (default `http://api:8000`)
- Change `BASE_URL` default in `client.ts` and `chat.ts` from `http://localhost:8000` to `/api` (relative path)
- Keep `VITE_API_BASE_URL` override for dev convenience (bare-metal frontend against local API)

**Acceptance criteria:**

- [ ] `/api/health` from browser returns API health response
- [ ] `/api/ask/stream` streams SSE without buffering
- [ ] `openapi-fetch` client works unchanged (just different base URL)
- [ ] No CORS needed in production (same-origin)
- [ ] Direct access to port 8000 not required from browser

---

### Issue C — Update docker-compose.yml (dev)

- **Owner:** pm
- **Dependencies:** Issue A
- **Labels:** infra

**Scope:**

- Add `frontend` service: build from `frontend/Dockerfile`, port 3000→3000, env `API_INTERNAL_URL=http://api:8000`
- Keep API port 8000 and Qdrant port 6333 exposed in dev (useful for debugging, curl, MCP)
- Update Makefile with `make frontend` target
- Update README quick-start

**Acceptance criteria:**

- [ ] `docker compose up` starts full stack including frontend
- [ ] `http://localhost:3000` serves chat UI
- [ ] End-to-end chat works through the proxy
- [ ] API still directly accessible on 8000 in dev
- [ ] MCP server unchanged

---

### Issue D — docker-compose.prod.yml

- **Owner:** pm
- **Dependencies:** A, B, C
- **Labels:** infra

**Scope:**

- `image:` references only, no `build:` — images tagged as `danish-legal-rag-{service}:{version}`
- Network isolation:
  - `frontend` network: only the frontend service, published on port 80
  - `backend` network: api, qdrant, ingest — not exposed to host
  - Frontend joins both networks (talks to API internally)
- Named volumes with explicit paths:
  - `qdrant_data` — Qdrant vector store (must survive image updates)
  - `hf_model_cache` — HuggingFace models (should survive to avoid ~440 MB re-download)
- Config via `.env`, add `IMAGE_TAG` variable to `.env.example`
- No MCP service in prod compose (stdio tool, not a network service)
- Makefile targets: `make prod-build` (tag images), `make prod-up`, `make prod-down`

**Acceptance criteria:**

- [ ] `make prod-build` tags all images with version
- [ ] `make prod-up` starts stack, exposes only port 80
- [ ] `curl http://localhost/api/health` returns 200
- [ ] Ports 8000 and 6333 NOT accessible from host
- [ ] Qdrant data and HF cache survive `docker compose down && docker compose up`
- [ ] Compose config validates (`docker compose -f docker-compose.prod.yml config`)

---

## Dependency graph

```
Issue A (frontend Dockerfile + adapter-node)
  |
  +---> Issue B (server-side API proxy)
  |       |
  +-------+---> Issue C (dev compose update)
                  |
                  +---> Issue D (prod compose)
```

## Impact on existing code

- **CORS** in `api/main.py`: Keep `allow_origins=["*"]` for dev. Lock down in a future ticket.
- **MCP server**: Unchanged — talks to `http://api:8000` internally.
- **contracts/openapi.yaml**: No changes — proxy is transparent.

## Open questions for Thomas

1. **Image registry:** Push to GHCR/Docker Hub, or local build + tag for now?
2. **TLS:** Add Caddy/Traefik in the prod compose, or handle externally?
3. **Hot reload in dev:** The Docker frontend service builds the image (no hot reload). Keep `npm run dev` for active frontend work on bare metal?
4. **Version strategy:** Single `VERSION` file at repo root, or `IMAGE_TAG` in `.env`?
