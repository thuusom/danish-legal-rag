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

## Where decisions live

Architectural decisions made in chat are ephemeral. To survive past one
conversation, they must land in one of four places:

| Tier | Lives in | What goes there |
|------|----------|-----------------|
| **Product intent** | `PRODUCT.md` | What the project is for, who it serves, what is in/out of scope, current capabilities and limitations, version history |
| **Project conventions** | This file (`CLAUDE.md`) | One-line rules every agent must know on every task: ownership, contract-first, issue-first, file boundaries |
| **Technical decisions** | `docs/decisions/ADR-NNN.md` | Substantive technical choices with reasoning and trade-offs: tech selection, strategic patterns, accepted invariants |
| **Task instructions** | The agent prompt or the GitHub Issue | Task-specific detail: which files to edit, which test to write, which commits to reference |

The PM agent owns `PRODUCT.md`. When the user defines or changes a goal,
capability, or non-goal in chat, the PM agent updates `PRODUCT.md`
before any implementation begins. The release agent updates the
"Current capabilities", "Current limitations", and "Versions" sections
as part of release prep.

Rule of thumb when a decision is made in chat:

- Applies to every task → add a line to `CLAUDE.md`
- Substantive choice with trade-offs → file an ADR before any agent acts on it
- Just task-specific detail → it's fine in the prompt or Issue body

The PM agent's standing job: when a decision is made in chat that doesn't yet
live anywhere durable, file it (ADR or `CLAUDE.md` update) before any
implementation agent picks up the work. Same pattern as the "issues before
work" rule below.

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
| `reports/test-runs/**` | tester agent | all read                     |
| `docs/**`         | pm agent         | all read; backend may draft  |
| `docs/test-strategy.md` | tester agent (jointly with backend + frontend on coverage baselines) | all read |
| `docs/test-runbook.md` | tester agent | all read |
| `frontend/tests/e2e/**` | tester agent (frontend writes new specs alongside features; tester maintains the suite) | all read |
| `scripts/**`      | backend or pm    | release agent owns `scripts/release.sh` |
| `Makefile`        | pm agent         | release agent owns `release-*` targets; backend/frontend propose via ticket |
| `docker-compose.yml` | pm agent      | backend/frontend propose via ticket |
| `docker-compose.prod.yml` | pm agent | release agent owns `IMAGE_TAG:-X.Y.Z` defaults; PM owns the rest |
| `.github/**`      | pm agent         | release agent owns `.github/workflows/release.yml` |
| `VERSION`                     | release agent  | —                            |
| `CHANGELOG.md`                | release agent  | —                            |
| `.github/workflows/release.yml` | release agent | —                          |
| `docs/release-process.md`     | release agent  | —                            |
| `scripts/release.sh`          | release agent  | —                            |

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
   The PR description references the Issue number. Unit and integration
   tests must pass before merge. For features that touch the user-visible
   flow, the tester agent's regression suite must pass on the rc before
   the final release is cut.

   **Auto-close syntax (important):** GitHub's auto-close parser requires the
   `Closes` (or `Fixes` / `Resolves`) keyword **repeated for each issue** in the
   PR description. A comma-separated list after a single keyword only closes
   the first one.

   - Wrong: `Closes #18, #19, #20`  (only #18 closes)
   - Right: `Closes #18, closes #19, closes #20`
   - Also right (one per line):

     ```
     Closes #18
     Closes #19
     Closes #20
     ```

   When a PR delivers many sub-issues plus a parent, list every one with its
   own keyword. Otherwise the unclosed issues need manual cleanup after merge.
4. **Integration check.** For cross-cutting features, the PM agent opens a
   tracking Issue and only closes it when an end-to-end test passes — not
   when backend and frontend individually merge.
5. **Reporting.** The PM agent writes daily reports to `reports/YYYY-MM-DD.md`
   summarising git activity, open PRs, ticket status, and blockers.
6. **Final tag push is human-only. rc tag push is automated.**
   - **Final releases** (major/minor/patch): no agent runs `git tag` or
     `git push --tags` for finals. The release agent prepares the commit;
     the human reviews the PR, merges, and runs `git push origin v{X.Y.Z}`.
   - **Release candidates** (rc): the release agent auto-pushes the branch
     and tag via `scripts/release.sh`. Safe because rc images can't reach
     prod (Issue #75), don't update `:latest`, and the consistency check
     still gates them. No PR required for an rc.
   See `docs/release-process.md` and ADR-006 amendment.

## Agent roles

Full persona definitions live in `.claude/agents/`. Short-form summaries
so every agent knows who does what:

- **backend agent** — Owns the FastAPI service, ingestion pipeline, MCP
  server, embedding/LLM providers, tests, and the OpenAPI contract.
- **frontend agent** — Owns the SvelteKit chat app. Consumes the OpenAPI
  contract via the generated TypeScript client.
- **pm agent** — Owns tickets, reports, docs, issue templates, and
  cross-cutting infra files (Makefile, dev compose, `.github/`). Does not
  write production code.
- **release agent** — Drives version bumps, image builds, GHCR pushes,
  GitHub Releases, and CHANGELOG maintenance. Prepares releases by
  editing VERSION, CHANGELOG, and `docker-compose.prod.yml` `IMAGE_TAG`
  defaults; commits on a release branch. NEVER pushes git tags — that
  is always a human action. After the human pushes the tag,
  `.github/workflows/release.yml` takes over. **rc images are
  test-environment-only and never deployed to production**: rc bumps
  do not change the prod compose IMAGE_TAG default. See ADR-006.
- **tester agent** — Owns test design and execution. Reviews features
  during specification (writes acceptance test plans on issues),
  maintains Playwright e2e specs in `frontend/tests/e2e/`, runs targeted
  suites against dev or full regression on a release candidate, and
  files bugs with evidence. Tester does NOT decide bug priority — that's
  the PM agent's job. See `.claude/agents/tester.md`,
  `docs/test-runbook.md`, and `docs/test-strategy.md`.

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
- Frontend: vitest for unit, Playwright for E2E. E2E tests live under
  `frontend/tests/e2e/` and run via `make e2e`, `make e2e-suite SUITE=...`,
  or `make e2e-regression IMAGE_TAG=...`. They hit a running stack via
  docker compose; CI does not run them on every PR — they are invoked
  explicitly (chat command, after rc push, or weekly cron once Issue #86
  lands).
- Tester agent owns the e2e suite's evolution and runs regression on rcs
  before final release; see `docs/test-strategy.md` and (when filed)
  `docs/test-runbook.md`.
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
- Issue templates live in `.github/ISSUE_TEMPLATE/`. For user-visible
  features, the tester agent comments an Acceptance test plan on the
  issue during spec review; the plan plus a `.spec.ts` under
  `frontend/tests/e2e/` is part of the definition of done.

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
