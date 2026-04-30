# PRODUCT.md — Danish Legal RAG

This document describes what the project is, who it is for, and what it
deliberately is not. It is the durable record of product intent — the
companion to `CLAUDE.md` (agent rules), `docs/decisions/` (technical
decisions), and `human.md` (collaboration model).

When a goal, capability, or non-goal changes in a chat with Claude, the
PM agent updates this file before any implementation begins. Sections
are append-mostly: add new entries, do not silently rewrite history.

## What this is

A Danish-language Retrieval-Augmented Generation system for Danish tax
and accounting legislation. A web chat UI lets users ask questions in
Danish; the backend retrieves the relevant statutory paragraphs from a
vector index and asks an LLM to write a grounded answer that cites
those paragraphs.

The corpus self-maintains: a daily check against retsinformation-api.dk
detects upstream amendments and updates the local cache; the operator
re-ingests on demand to refresh the search index.

## Who it is for

- **Tax advisors and accountants** who need to cite specific paragraphs
  in Danish tax and accounting law without scrolling through
  retsinformation.dk.
- **In-house finance staff** at small and mid-sized companies dealing
  with VAT, bookkeeping, and depreciation rules.
- **Curious laypeople** who want a faster path into Danish tax law than
  raw legislation provides.

The system is consultative — it surfaces and explains; the human
decides.

## Problems it solves

1. **Manual lookup is slow.** Searching across 12+ Danish tax and
   accounting laws to find the relevant paragraph for a specific
   question takes minutes; this system answers in seconds.
2. **Generic LLMs hallucinate Danish citations.** Asking ChatGPT about
   Danish tax law produces plausible-looking paragraph numbers that
   often do not exist. Grounding answers in retrieved chunks
   eliminates this.
3. **Hand-curated copies of law go stale.** Many derivative tools snapshot
   law text and never update it. We detect upstream version changes
   daily and refresh.
4. **Operators have no visibility into corpus state.** A small admin
   page surfaces what is loaded, when it was last fetched, and whether
   anything is outdated.

## What success looks like

- A user asking a question gets a Danish answer in under 5 seconds with
  links to the cited paragraphs on retsinformation.dk.
- Every cited paragraph is real — paragraph numbers, stk numbers, and
  law identifiers all match the live source.
- The corpus is at most one day behind retsinformation.dk for any law
  in `ingest/sources.yaml`.
- Adding a new law to the corpus is a single-file change
  (`ingest/sources.yaml` + a seed JSON), no code changes required.
- Cutting a release is one human action (`git push origin v{X.Y.Z}`)
  after the release agent prepares the commit.

## Out of scope (deliberately)

- **Legal advice.** This system retrieves and explains; it does not
  substitute for a qualified tax advisor or lawyer.
- **Other jurisdictions.** Danish tax and accounting law only.
- **Court rulings (SKM-afgørelser).** Not in the corpus today; revisit
  in a future major version if retrieval quality demands it.
- **Skattestyrelsens juridiske vejledning.** The interpretive guide is
  the natural Tier 2 corpus expansion but not currently included.
- **Authentication and per-user accounts.** Open-by-default for now;
  tracked as Roadmap item #1 in `README.md`.
- **Rate limiting / cost reporting.** Roadmap items #2 and #3.
- **Multilingual UI.** The user-visible UI is Danish. Code, docs, and
  agent instructions are English.

## Current capabilities (kept current)

Se `docs/user-guide.md` for brugsvejledning.

- 12 legal sources covering core Danish tax and accounting law
  (Afskrivningsloven, Årsregnskabsloven, Bogføringsloven,
  Selskabsskatteloven, Momsloven, Ligningsloven, Skattekontrolloven,
  Revisorloven, Skatteforvaltningsloven, plus three bekendtgørelser).
- ~3,673 provisions after live ingestion (was 398 from hand-curated seed
  before v1.1.0).
- Streaming Danish chat UI with Markdown rendering, session history,
  law-filter dropdown, and clickable references that link to
  retsinformation.dk at the paragraph level.
- Mobile-responsive layout with safe-area handling.
- Server-side API proxy: the backend is never directly exposed to the
  browser.
- Live law fetcher pulling structured JSON from retsinformation-api.dk
  on demand or on the daily schedule.
- `/admin` page showing per-law version, snapshot date, ingestion time,
  and a manual "Pull updates now" trigger.
- Daily GitHub Actions cron that auto-opens `Stale law: ...` issues
  when upstream drifts and auto-closes them when the local cache
  catches up.
- Idempotent re-ingestion: removed paragraphs disappear from search
  instead of becoming orphans.
- Dense vector search (sentence-transformers, multilingual mpnet);
  hybrid search infrastructure (dense + BM25) available behind a flag.
- Configurable LLM provider: Anthropic, OpenAI, Ollama, mock.
- MCP server for Claude Desktop integration.
- Tag-driven release pipeline: `make release-{patch,minor,major}`,
  human pushes the tag, GitHub Actions builds and publishes images to
  GHCR.
- Playwright e2e harness with 9 first test cases (chat golden path,
  admin status, backend smoke) covering the user-visible flow. Run via
  `make e2e*` against dev or against an rc on the test environment.
  See [`docs/test-strategy.md`](docs/test-strategy.md) and
  [`docs/test-runbook.md`](docs/test-runbook.md). Tester agent
  persona at [`.claude/agents/tester.md`](.claude/agents/tester.md).

## Current limitations (kept current)

- **BOG-MBK** (Mindstekravsbekendtgørelsen) returns only two provisions
  after live fetch from retsinformation-api.dk; root cause not yet
  determined.
- **ABL** (Aktieavancebeskatningsloven) is not in the corpus, so
  questions about share gains return weak retrieval.
- No authentication; the chat is reachable to anyone who can reach the
  service URL.
- No per-user rate limiting or token-cost reporting.
- No structured cost or token telemetry per request.
- Admin page has no manual job-trigger UI yet (currently only the
  currency check can be triggered from the page).
- Retsinformation-api.dk is a third-party service; if it goes down, the
  fetcher pauses cleanly but no fresh updates flow until it returns.
- Weekly regression cron (Issue #86) still pending. The tester persona,
  runbook, e2e harness, and coverage-delta script are in place; only
  scheduled regression-on-rc against a remote test host has not been
  wired up yet.

## Versions

| Version | Date | Theme |
|---|---|---|
| v1.0.0 | 2026-04-26 | First production release: chat UI, FastAPI backend, 12-source corpus, prod compose with GHCR images, OpenAPI contract. |
| v1.1.0 | 2026-04-28 | Live law fetcher, idempotent re-ingestion, `/admin` page, release agent, daily cron, full English docs, ADRs 003-006. |
| v1.1.1 | 2026-04-30 | Bug fixes: api `law_cache` mount made writable so `/admin/check-currency` works; admin table layout improved. |

See `CHANGELOG.md` for the per-version diff.

## What is next

See `README.md` Roadmap section for the prioritized list of ideas:
auth + Postgres, per-user rate limiting, cost & token reporting,
extended admin background jobs, Celery + Redis for scheduling, and a
Loki/Grafana/Prometheus monitoring stack.

None of those are committed; they are ideas. File issues and plans
before any work starts, per `CLAUDE.md`.
