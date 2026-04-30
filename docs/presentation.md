---
marp: true
theme: default
paginate: true
---

# Danish Legal RAG

**An AI-built RAG system for Danish tax and accounting law**

Thomas Christensen · 2026-04-28

---

## What it is

A web chat application that answers questions about Danish tax and
accounting legislation, grounded in actual law text — not invented.

- 12 legal sources, 398+ provisions
- Built almost entirely through dialogue with Claude
- Single human developer; multiple AI agents

The interesting part is not the chat app. It is **how it was built.**

---

## What it does

Users ask in Danish; the system retrieves the relevant paragraphs and
generates an answer that cites them.

```
"Kan jeg fradrage indkøb af en computer som driftsudgift?"
```

→ Retrieves matching provisions across Afskrivningsloven,
   Ligningsloven, Bogføringsloven, …
→ LLM writes a Danish answer
→ UI shows clickable references to retsinformation.dk

Streaming responses, session history, law filter, mobile-friendly.

---

## What it does — the operator side

A small `/admin` page surfaces:

- Which laws are in the corpus, what version
- When each was last ingested
- Whether retsinformation.dk has a newer version (daily check)
- A "Pull updates" button to re-fetch on demand

The corpus stays current without anyone doing manual JSON curation.

---

## How it is done — stack

| Layer | Tech |
|---|---|
| Frontend | SvelteKit, TypeScript, Tailwind |
| Backend | FastAPI, pydantic v2 |
| Vector DB | Qdrant (dense + BM25 sparse, RRF fusion) |
| Embeddings | sentence-transformers (multilingual) |
| LLM | Configurable: Anthropic, OpenAI, Ollama, mock |
| Law source | retsinformation-api.dk + in-repo seed JSON |
| Infra | Docker Compose (dev + prod), GHCR images |
| CI/CD | GitHub Actions |
| MCP | stdio integration for Claude Desktop |

---

## How it is done — architecture

```
Frontend (SvelteKit) ──▶ /api proxy ──▶ FastAPI backend
                                         ├─▶ Qdrant (vectors)
                                         └─▶ LLM provider

Daily cron ──▶ retsinformation-api.dk ──▶ law_cache volume
                                           └─▶ ingest job ──▶ Qdrant
```

Single source of truth: `contracts/openapi.yaml` defines the HTTP API.
Frontend generates its TypeScript client from it.

---

## The agent setup

Four specialized agent personas, each with strict file ownership:

| Agent | Owns | Job |
|---|---|---|
| **backend** | `api/`, `ingest/`, `mcp/`, `shared/`, `tests/`, `contracts/` | Code, tests, OpenAPI |
| **frontend** | `frontend/` | UI, types from contract |
| **pm** | `docs/`, `reports/`, `Makefile`, compose, `.github/` | Plans, issues, docs |
| **release** | `VERSION`, `CHANGELOG`, `release.yml`, runbook | Version bumps, image publish |

Defined in `.claude/agents/*.md`. Loaded at session start.

---

## Five agents now

| Agent | Owns | Job |
|---|---|---|
| backend | `api/`, `ingest/`, `mcp/`, `shared/`, `tests/`, `contracts/` | Code, tests, OpenAPI |
| frontend | `frontend/` | UI, types from contract |
| pm | `docs/`, `reports/`, `Makefile`, compose, `.github/` | Plans, issues, docs, bug triage |
| release | `VERSION`, `CHANGELOG`, `release.yml`, runbook | Version bumps, image publish |
| tester | `frontend/tests/e2e/`, `reports/test-runs/` | Test design, run suites, file bugs |

Phase 3 mostly complete: persona, e2e harness, runbook, and
coverage-delta script all shipped. Weekly regression cron (Issue #86)
deferred until at least one rc has been cut through the manual flow.

---

## House rules (CLAUDE.md)

- **Issue first** — no work without a tracked GitHub Issue
- **Contract first** — `openapi.yaml` updates land in the same PR as
  the code change
- **One PR per ticket** — auto-closes on merge with `Closes #N`
- **Strict ownership** — agents never write outside their owned paths
- **Tag push is human-only** — irreversible action, stays in human hands

These rules survive across every conversation because they live in
`CLAUDE.md`, which every agent loads at startup.

---

## Where decisions live

Three-tier durability model so decisions don't evaporate when chat ends:

| Tier | Lives in | Example |
|---|---|---|
| Project conventions | `CLAUDE.md` | "Tag push is human-only" |
| Substantive decisions | `docs/decisions/ADR-NNN.md` | "Use retsinformation-api.dk" |
| Task instructions | Issue or agent prompt | "Add field X to model Y" |

If a decision is made in chat that doesn't yet live anywhere, the PM
agent files it before any implementation begins.

---

## Workflow — from spec to release

```
1. Human asks                  ◀ "add live law fetching"
2. Claude proposes plan        ◀ scope, trade-offs, effort
3. Human refines / approves    ◀ "use option B; go"
4. PM files GitHub Issues      ◀ parent + sub-issues, owners
5. Tester comments test plan   ◀ NEW: positive/negative cases on issue
6. Backend/frontend agents     ◀ implement against issues
   work in parallel            ◀ contract-first when API changes
7. Each agent opens a PR       ◀ CI: unit + integration; closes #N
8. Human reviews & merges      ◀ never agent-merged
9. Release agent prepares rc   ◀ auto-pushes branch + rc tag
10. Tester runs regression     ◀ NEW: full Playwright on the rc deploy
                               ◀ PASS/FAIL → bugs to PM if red
11. If green: release agent    ◀ prepares final, consumes the rc
    prepares final
12. Human pushes the tag       ◀ triggers release.yml
13. Workflow builds + ships    ◀ :X.Y.Z + :latest GHCR + GitHub Release
```

---

## Workflow — what is automated vs reactive

Only **one** thing in the project runs on its own:

| Component | Trigger | Autonomous? |
|---|---|---|
| `check-law-currency.yml` | Daily 06:00 UTC cron | **Yes — only one** |
| `ci.yml` | push, PR | No |
| `release.yml` | tag push (human) | No |
| Claude Code agents | chat invocation | **No — never** |

The daily check opens a "Stale law: ..." GitHub Issue when upstream
drifts. It does not modify production data — that requires a human.

---

## Approval gates — what agents must ask humans

Agents stop and require explicit approval for:

- Plan approval before implementation
- Branch creation for major efforts
- Scope expansion mid-work
- Cross-boundary file edits
- **Pushing the release tag**
- Merging PRs to main
- Force-push, branch deletion, history rewrites
- Rotating secrets
- Spending money (paid models, large datasets)
- Touching production data
- Overriding an existing ADR

Default rule: **when unsure, ask.** Documented in `human.md`.

---

## Models in use to build this

| Role | Model | Why |
|---|---|---|
| Orchestrator (chat with human) | Claude Opus 4.7 (1M context) | Heavy reasoning, plans, distributing work |
| Backend agent | Opus default | Code with non-trivial constraints |
| Frontend agent | Opus default | UI plus typed clients |
| PM agent | Opus default | Doc and ticket writing |
| Release agent | Claude Sonnet | Mostly mechanical work; cheaper |
| Fast mode (`/fast`) | Claude Opus 4.6 | When latency matters |

The product itself uses a different LLM at runtime — currently Claude
Sonnet 4.6 via the Anthropic API, with Ollama and OpenAI providers
available as alternatives.

---

## Two distinct cost surfaces

There is a clear split between *building* and *running* this project:

| Surface | Pays for | How billed |
|---|---|---|
| **Building** (this presentation included) | Claude Code agent work — orchestrator + 4 sub-agents | Claude.ai subscription via OAuth (Claude Max plan, fixed monthly) |
| **Running** (production) | LLM calls per user question, embeddings on ingest | Anthropic API key (per token) |

OAuth means the build cost is essentially **flat** — the subscription
is paid regardless of how much agent work happens within its limits.

---

## What the build has consumed (rough)

I cannot read exact token counts from inside this conversation, but
from completion notifications during agent runs:

- ~25 sub-agent dispatches in this project so far
- Each used 30k–180k tokens (typical: 50k)
- Total sub-agent usage: **~1.5M – 3M tokens**
- Orchestrator usage (chat with human) is similar in order of magnitude
- Combined estimate: **3M – 6M tokens of Claude work** to build v1.1.0

On a Claude Max plan via OAuth, this stays within the included
allowance — no per-token billing surprises.

---

## What v1.1.0 ships

**Live law fetcher**
12 sources kept current automatically; daily drift detection;
`/admin` UI; idempotent re-ingestion.

**Release agent**
Tag-driven publish to GHCR. `make release-minor` → human pushes tag →
images live in 12 minutes.

**Documentation**
6 ADRs · `human.md` · runbook · workflow docs · automation table.

All built through dialogue. The first commit on this project was
6 months ago; v1.0.0 shipped 2 days ago; v1.1.0 today.

---

## Reading order (for someone new)

1. `README.md` — what this project is
2. `human.md` — how to engage with the AI workflow
3. `CLAUDE.md` — agent rules and ownership
4. `docs/decisions/README.md` — the ADRs
5. `docs/release-process.md` — operator runbook
6. `docs/github-workflows.md` — what each workflow does

The whole project doubles as documentation of an AI-assisted
development pattern that scales to one person + four agents.

---

# Questions?

🔗 https://github.com/thuusom/danish-legal-rag
🔗 https://github.com/thuusom/danish-legal-rag/releases/tag/v1.1.0
