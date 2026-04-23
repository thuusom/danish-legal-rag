# Plan: CI + Chat Frontend

**Date:** 2026-04-23
**Branch:** `feat/multi-agent-setup`
**Status:** Approved — issues filed 2026-04-23

---

## Context

The backend is functional: 4 API endpoints (`/health`, `/ask`, `/search`, `/laws`), 9 ingested Danish laws (284 provisions), hybrid search infrastructure in place. No CI, no frontend, no streaming endpoint.

This plan adds GitHub Actions CI, a SvelteKit chat webapp, and (later) streaming support.

## Design decisions

**Streaming:** Build the chat UI against `/ask` (non-streaming) first. The backend's `/ask/stream` SSE endpoint doesn't exist yet. Architecting the frontend message store for easy swap-in means streaming is a one-file change later. This avoids blocking frontend on backend work.

**Conversation history:** Backend stays stateless for now. Frontend manages conversation history client-side (localStorage). Multi-turn context will require an optional `history` field on a future `/ask/stream` request type.

**CI strategy:** Two-job GitHub Actions workflow. Job 1 (fast, no Docker): pure unit tests for models and chunker. Job 2 (docker compose): full integration tests with `LLM_PROVIDER=mock`.

---

## Issues

### Issue #3 — Add GitHub Actions CI (unit + integration)

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/3
- **Agent:** backend
- **Depends on:** none
- **Labels:** backend, infra

**Scope:**

- Create `.github/workflows/ci.yml` with two jobs
- **Job 1 (unit, ~30s):** Install Python deps, run `TestLegalChunkModel` and `TestChunker` from `tests/test_embeddings.py`. No Docker, no model download. Add `@pytest.mark.slow` to `TestEmbeddingProvider` and skip in this job.
- **Job 2 (integration, ~3-5min):** `docker compose up -d qdrant api`, `docker compose run --rm ingest`, `make test-integration`. Uses `LLM_PROVIDER=mock` (no API keys needed). Cache Docker layers and `hf_model_cache` volume.
- Trigger: `on: push` to `feat/*` branches + `on: pull_request` to `main`
- Add `make contract-verify` step to catch contract drift
- Add `make client` verification step (generate types, fail if they differ from committed)

**Acceptance criteria:**

- [ ] CI runs on push and PR
- [ ] Unit job catches model/chunker regressions without Docker
- [ ] Integration job catches API and retrieval regressions
- [ ] Contract drift detected automatically
- [ ] No API keys required (mock LLM provider)

---

### Issue #4 — Scaffold SvelteKit frontend

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/4
- **Agent:** frontend
- **Depends on:** none (parallel with #3)
- **Labels:** frontend

**Scope:**

- `npx sv create frontend` with TypeScript strict + Tailwind
- adapter-static (single-page chat app, no SSR needed)
- Run `make client` to generate `frontend/src/lib/api/schema.d.ts`
- Add `openapi-fetch` dependency for type-safe API calls
- Create `frontend/src/lib/api/client.ts` — configures base URL from env var
- Basic `/` route with placeholder content to prove the stack works
- Propose `frontend` service addition to `docker-compose.yml` (PM applies)

**Acceptance criteria:**

- [ ] `npm run check` passes (TypeScript strict)
- [ ] `npm run dev` serves a page at `localhost:5173`
- [ ] `schema.d.ts` generated and committed
- [ ] API client can reach `localhost:8000/health` from the dev server

---

### Issue #5 — Chat UI with non-streaming `/ask`

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/6
- **Agent:** frontend
- **Depends on:** #4
- **Labels:** frontend

**Scope:**

- Components: `ChatInput`, `MessageList`, `AssistantMessage`, `LegalReference`
- Svelte writable store for current conversation (messages array)
- `POST /ask` on submit with typing indicator during fetch
- Render `answer` text + `references` array on response
- `LegalReference` component: `citation_label` (bold, linked to `source_url`), `law` + `law_code`, truncated `quote` with expand, `score` badge
- Responsive layout: sidebar placeholder (empty for now), main chat area `max-w-prose`
- All UI copy in Danish (placeholder: "Stil et juridisk sporgsmal...")
- Error handling: API down, empty results

**Acceptance criteria:**

- [ ] User can type a question and see an answer with legal references
- [ ] References show law name, section, clickable source link, and quote
- [ ] Typing indicator visible during API call
- [ ] Error state shown when API is unreachable
- [ ] Vitest unit tests for message store logic
- [ ] Playwright E2E: type question, see answer + references

---

### Issue #6 — Session history sidebar

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/7
- **Agent:** frontend
- **Depends on:** #5 (GitHub #6)
- **Labels:** frontend

**Scope:**

- `SessionSidebar` component
- localStorage persistence: `{id, title, messages, timestamp}[]`
- Title derived from first user message (truncated to ~50 chars)
- "Ny samtale" button clears current conversation and starts fresh
- Clicking a past session loads its messages into the chat view
- Visual indicator for active session

**Acceptance criteria:**

- [ ] Sessions persist across page reloads
- [ ] User can create new conversations and switch between them
- [ ] Session list shows title + timestamp
- [ ] Vitest for session store CRUD
- [ ] Playwright: create two sessions, switch between them, verify messages

---

### Issue #7 — Law filter + polish

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/8
- **Agent:** frontend
- **Depends on:** #5 (GitHub #6)
- **Labels:** frontend

**Scope:**

- `GET /laws` call on mount, populate dropdown/select
- Pass `filter_law` to `/ask` when a law is selected
- "Alle love" default option (no filter)
- Loading states for initial law list fetch
- Keyboard accessibility audit (tab order, ARIA labels, focus management on chat)
- Mobile responsive pass (chat usable on 375px viewport)

**Acceptance criteria:**

- [ ] User can filter by specific law before asking
- [ ] Filtered results only contain references from selected law
- [ ] Dropdown populated from live `/laws` endpoint
- [ ] Accessible via keyboard only
- [ ] Usable on mobile viewport
- [ ] Playwright: filter by AFL, ask question, verify references are AFL only

---

### Issue #8 — Add `/ask/stream` SSE endpoint

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/5
- **Agent:** backend
- **Depends on:** none (can run parallel with #5-#7)
- **Labels:** backend, contract

**Scope:**

- New endpoint `POST /ask/stream` returning `text/event-stream`
- SSE event frames: `chunk` (partial answer text), `references` (full array, sent once at end), `done` (signal completion), `error` (on failure)
- Add streaming variants to LLM provider calls:
  - `_call_anthropic`: use `messages.stream()`
  - `_call_openai`: use `stream=True`
  - `_call_ollama`: use `stream=True` on openai client
- `FastAPI StreamingResponse` with proper headers
- Optional `history: [{role: str, content: str}]` field on request for multi-turn context
- Contract update: add `/ask/stream` path + SSE event schemas to `contracts/openapi.yaml` (FIRST COMMIT)

**Acceptance criteria:**

- [ ] `contracts/openapi.yaml` updated with `/ask/stream` path and event schemas
- [ ] SSE stream delivers answer token-by-token
- [ ] References sent as single event after answer completion
- [ ] Error event on LLM failure (not a broken stream)
- [ ] Non-streaming `/ask` unchanged and still works
- [ ] Integration test: consume stream, verify complete answer + references
- [ ] MCP server unaffected

---

### Issue #9 — Frontend streaming support

- **GitHub:** https://github.com/thuusom/danish-legal-rag/issues/9
- **Agent:** frontend
- **Depends on:** #5 (GitHub #6), #8 (GitHub #5)
- **Labels:** frontend

**Scope:**

- Replace fetch-and-wait `/ask` call with SSE consumption of `/ask/stream`
- Token-by-token append to assistant message in the store
- References rendered after `references` event arrives
- Input disabled during active stream
- Typing/streaming indicator with animation
- `done` event re-enables input and finalizes message
- `error` event shows error state, re-enables input
- Graceful fallback: if `/ask/stream` fails, fall back to `/ask`

**Acceptance criteria:**

- [ ] Answer text appears incrementally as tokens arrive
- [ ] References appear after answer is complete
- [ ] Input locked during streaming, unlocked on done/error
- [ ] Error event renders user-visible error message
- [ ] Playwright E2E with live backend streaming

---

## Dependency graph

```
#3 CI ─────────────────────────────────────────────────────►
#4 Scaffold ──► #5 Chat UI ──► #6 Sessions ──► #7 Filter
#8 Streaming ─────────────────────────────────► #9 Stream UI
                                                (needs #5 too)
```

**Critical path to "locally running chat service":** #4 → #5 (2 issues)
**Critical path to "production-quality chat":** #4 → #5 → #6 → #7 + #8 → #9

## Parallel work opportunities

- #3 (CI) and #4 (scaffold) — no dependency, different agents
- #8 (backend streaming) and #5/#6/#7 (frontend work) — different agents
- #6 (sessions) and #8 (streaming) — different agents
