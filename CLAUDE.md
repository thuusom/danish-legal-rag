# Danish Legal RAG — Agent House Rules

This file is read by every Claude Code agent on startup. It defines the
coordination model. Do not violate these rules without the user's explicit
instruction in chat.

## Project summary

A Danish-language Retrieval-Augmented Generation system for Danish tax and
accounting law (currently Afskrivningsloven and Årsregnskabsloven, extensible).
A chat web frontend talks to a FastAPI backend. The backend retrieves legal
provisions from Qdrant and generates grounded answers via a configurable LLM
provider (Anthropic, OpenAI, Ollama, or mock).

The project started as an API-only service with MCP and httpyac as its clients.
The current phase adds a SvelteKit chat frontend and extends retrieval quality.

## Architecture (as-is + planned)

```
┌──────────────────┐      HTTP/JSON (streamed)
│   Frontend       │──────────────────────────────┐
│   SvelteKit      │                              │
│   chat app       │◄─────────────────────────────┤
│   (planned)      │                              │
└──────────────────┘                              ▼
                                        ┌───────────────────┐
┌──────────────────┐   MCP stdio        │   Backend API     │
│ Claude Desktop   │───────────────────►│   FastAPI         │
└──────────────────┘                    │                   │
                                        │   /ask /search    │
┌──────────────────┐   curl / httpyac   │   /laws /health   │
│ CLI / scripts    │───────────────────►│                   │
└──────────────────┘                    └────────┬──────────┘
                                                 │
                        ┌────────────────────────┼────────────────────────┐
                        ▼                        ▼                        ▼
                ┌───────────────┐      ┌──────────────────┐     ┌────────────────┐
                │ Qdrant        │      │ LLM provider     │     │ Embedding model│
                │ vector store  │      │ Anthropic/OpenAI/│     │ sentence-      │
                │ (+ sparse —   │      │ Ollama/mock      │     │ transformers   │
                │  planned)     │      │                  │     │ multilingual   │
                └───────────────┘      └──────────────────┘     └────────────────┘
```

## Architecture decisions

Significant decisions are recorded as ADRs in `docs/decisions/`. Read them
before proposing changes to: third-party data sources, ingestion strategy,
re-ingestion semantics, the retrieval pipeline, or session storage.

Index: [`docs/decisions/README.md`](docs/decisions/README.md).

If you are about to argue against an existing ADR, write a new ADR that
supersedes it rather than silently changing behaviour.

## Directory ownership (STRICT)

| Path              | Owned by         | Others may                   |
|-------------------|------------------|------------------------------|
| `api/**`          | backend agent    | read only                    |
| `ingest/**`       | backend agent    | read only                    |
| `mcp/**`          | backend agent    | read only                    |
| `shared/**`       | backend agent    | read only                    |
| `tests/**`        | backend agent    | read only                    |
| `contracts/**`    | backend agent    | frontend reads               |
| `frontend/**`     | frontend agent   | read only                    |
| `tickets/**`      | pm agent         | all read                     |
| `reports/**`      | pm agent         | all read                     |
| `docs/**`         | pm agent         | all read; backend may draft  |
| `scripts/**`      | backend or pm    | —                            |
| `Makefile`        | pm agent         | backend/frontend propose via ticket |
| `docker-compose.yml` | pm agent      | backend/frontend propose via ticket |
| `.github/**`      | pm agent         | —                            |

An agent must NEVER write outside its owned paths. If a change crosses
boundaries (e.g. a backend change requires a Makefile target), the agent
doing the work writes a short note in its PR description and the PM agent
makes the cross-cutting edit.

## The contract (critical)

`contracts/openapi.yaml` is the **source of truth** for the HTTP API between
frontend and backend.

- The backend agent OWNS this file. It is generated from FastAPI on demand
  (`make contract`) and also hand-curated for descriptions and examples.
- The frontend agent READS this file and generates a TypeScript client from it
  (`make client`) into `frontend/src/lib/api/`.
- **Rule:** When the backend changes or adds an endpoint, it updates
  `contracts/openapi.yaml` FIRST in the same PR. A PR that changes API
  behaviour without updating the contract does not merge.

This is the mechanism that lets frontend and backend work in parallel without
synchronous coordination: as soon as the contract lands, the frontend can
start against the updated types even before the backend implementation is
finished.

## Coordination model

1. **Ticket intake.** A human (Thomas) or the PM agent files a GitHub Issue
   using the templates in `.github/ISSUE_TEMPLATE/`. The Issue includes:
   a user story, acceptance criteria, the API contract stub (if relevant),
   and which agent(s) own it.
2. **Contract first.** For any ticket that touches the API surface, the
   backend agent's first commit is the updated `contracts/openapi.yaml`.
   The frontend agent can start as soon as that commit lands.
3. **One PR per ticket.** Each agent opens a PR against the feature branch.
   The PR description references the Issue number. Tests must pass before
   merge.
4. **Integration check.** For cross-cutting features, the PM agent opens a
   tracking Issue and only closes it when an end-to-end test passes — not
   when backend and frontend individually merge.
5. **Reporting.** The PM agent writes daily reports to `reports/YYYY-MM-DD.md`
   summarising git activity, open PRs, ticket status, and blockers.

## Standards

### Backend
- Python 3.11, FastAPI, pydantic v2
- Embedding and LLM provider pattern (abstract base + provider classes) is
  established — new providers follow the same shape
- All new endpoints: add tests to `tests/test_integration.py` AND update
  `contracts/openapi.yaml`
- Keep ingestion idempotent: every new ingestible source type must use stable
  IDs and content hashes, like the existing law ingestion
- Do not break the MCP server when adding API endpoints (it's a real client)

### Frontend
- SvelteKit with TypeScript, Tailwind, strict type checking
- Never hand-write types that exist in `contracts/openapi.yaml` — always
  import from the generated client
- Never read backend Python source to infer API behaviour. If the contract
  is ambiguous, open an Issue requesting the backend agent clarify the
  OpenAPI description
- Streaming: use Server-Sent Events (backend will expose `/ask/stream`
  as a text/event-stream endpoint)
- Language: UI copy in Danish (target user), code comments in English

### Testing
- Backend: pytest, both unit (`test_embeddings.py`) and integration
  (`test_integration.py`) styles exist; match them
- Frontend: vitest for unit, Playwright for E2E. E2E tests hit a running
  stack via docker compose
- Every PR must include or update a test; no PR merges on "looks fine"

## Issue tracking (mandatory)

Every feature, bug fix, or corpus change MUST have a GitHub Issue filed
BEFORE work begins. This is non-negotiable — work without a tracking issue
is invisible and uncoordinated.

- **Before starting work:** File or confirm a GitHub Issue exists using
  `gh issue create`. Include: user story, owner (which agent), acceptance
  criteria, and dependencies.
- **During work:** Reference the Issue number in all commit messages
  (e.g., `#12`).
- **On completion:** Close the Issue via commit message or `gh issue close`.
- **For multi-step features:** File a parent Issue and break into sub-issues.
  The PM agent tracks the parent; agents work the sub-issues.
- **Agents must never pick up work that has no Issue.** If asked to do
  something ad-hoc, file the Issue first, then implement.

## Non-goals

- Do not replace Qdrant with OpenSearch. Qdrant 1.10+ supports sparse vectors,
  which is enough for hybrid search.
- Do not add a Streamlit UI. The SvelteKit frontend is the primary UI.
- Do not touch the MCP server contract without a dedicated ticket — it is a
  working integration with Claude Desktop.

## When in doubt

Check `docs/decisions/` first — many recurring questions (why Qdrant,
why retsinformation-api.dk, why update-only fetcher, why per-law
delete-then-insert) are already answered there. If the ADRs don't cover
it, ask Thomas in the chat. Don't guess on architecture questions.
Specifically, don't guess about: database choices beyond Qdrant,
authentication strategy, deployment targets, or whether to add a new law
to the ingestion set.
