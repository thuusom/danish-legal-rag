# Test strategy

This document records the project's automated test posture: what each layer
covers, how coverage is measured, and the current baseline numbers.

Coverage is **informational** today. CI does not gate on a coverage
threshold; this file is the single place where the team can see whether
the trend is going in the right direction over time.

## Backend

- Tooling: [pytest-cov](https://pytest-cov.readthedocs.io/) (coverage.py
  under the hood), invoked via `make coverage`.
- Run locally: `make coverage` from the repo root. Requires the dev
  stack to be up (`make up`); the target executes
  `pytest --cov` inside the `api` container where pytest is already
  installed.
- Reports: `term` (stdout) and `xml` (`/app/coverage.xml` inside the
  container — not bind-mounted to the host today).
- Coverage scope: `api/`, `ingest/`, `shared/`, `mcp/`. See the caveats
  below for why the `api/*` and `mcp/*` numbers underrepresent reality.

### Headline (2026-04-30)

| Metric     | Coverage |
|------------|----------|
| Statements | 57%      |

125 tests collected; 120 passed, 5 skipped (skips are network-gated
fetcher tests, not coverage-relevant).

### Per-module breakdown

| Module    | Statements | Coverage | Notes                                                                                                  |
|-----------|-----------:|---------:|--------------------------------------------------------------------------------------------------------|
| `api/`    | 497        | 23%      | Only `api/admin.py` (55%) is exercised in-process. See caveat #1 below.                                |
| `ingest/` | 743        | 67%      | `law_fetcher.py` 77%, `cache.py` 100%, `chunker.py` 87%, `embedder.py` 80%. `fetcher.py` is 0%, see #2. |
| `shared/` | 361        | 71%      | `models.py` 98%, `admin_state.py` 86%, `qdrant_utils.py` 44%, `sparse.py` 56%.                         |
| `mcp/`    | n/a        | n/a      | Module not present in the api container — see caveat #3.                                               |

### Caveats — why the headline understates real coverage

1. **`api/main.py`, `api/rag.py`, `api/embeddings.py`, `api/models.py`
   all report 0%** despite being exercised end-to-end by
   `tests/test_integration.py`. The integration tests hit the live
   uvicorn server in a separate process, and `pytest --cov` only
   instruments the test runner's own process. Lifting these numbers
   would require either FastAPI `TestClient` in-process tests or
   running uvicorn under coverage — out of scope for this baseline.
2. **`ingest/fetcher.py` is 0%** — that module is the legacy
   retsinformation.dk HTML fetcher; the active code path is
   `ingest/law_fetcher.py`. Candidate for deletion in a future cleanup.
3. **`mcp/` is not copied into the api Docker image**, so `--cov=mcp`
   emits a `module-not-imported` warning and contributes nothing. To
   measure mcp coverage we either copy the package into the api image
   or run a separate coverage pass in the mcp container.

### Interpretation

The 57% headline is a floor, not a ceiling. The api package looks much
worse than it is because integration testing crosses a process boundary
that coverage cannot follow. Treat this number as the "easy wins"
indicator: when raising it, the highest-value targets are
`shared/qdrant_utils.py` (pure functions, 44%) and the in-process
testable parts of `api/admin.py` (already 55%).

## Frontend

- Tooling: [vitest](https://vitest.dev/) with the `@vitest/coverage-v8`
  provider
- Run locally: `npm run coverage` from `frontend/`
- Reports: `text` (stdout), `html` (`frontend/coverage/index.html`),
  `lcov` (`frontend/coverage/lcov.info`)
- Excluded from coverage: test files, the generated OpenAPI client
  (`src/lib/api/schema.d.ts`), SvelteKit ambient types (`src/app.d.ts`),
  and build output (`.svelte-kit/`, `build/`, `dist/`).

### Headline (2026-04-30)

| Metric     | Coverage |
|------------|----------|
| Statements | 66.75%   |
| Branches   | 75.08%   |
| Functions  | 75.75%   |
| Lines      | 66.75%   |

57 unit tests across 6 files pass.

### Per-area breakdown

| Area               | Statements | Notes                                                                 |
|--------------------|-----------:|-----------------------------------------------------------------------|
| `lib/utils`        | 100%       | `id.ts`, `markdown.ts` — fully covered.                               |
| `lib/stores`       | 96.27%     | `chat.ts`, `sessions.ts`, `toast.ts` — well covered.                  |
| `lib/api`          | 94.82%     | `sse.ts` fully covered; `client.ts` is a thin generated-client wrapper that is exercised end-to-end via Playwright rather than unit tests. |
| `lib/components/admin` | 92.96% | `LawTable.svelte`, `LawTableHeader.svelte` covered via admin tests.   |
| `routes/admin`     | 85.29%     | Admin page covered alongside its component tests.                     |
| `lib/components`   | 8.33%      | Chat-flow components (`ChatInput`, `MessageList`, `Reference`, `Sidebar`, etc.) are exercised end-to-end by Playwright; no unit tests yet. `Toaster.svelte` is the lone exception at 95%. |
| `routes` (root)    | 0%         | `+page.svelte`, `+layout.svelte`, and `routes/api/[...path]/+server.ts` are integration surfaces — covered by Playwright, not vitest. |

### Interpretation

The 66.75% headline understates the real test posture: the chat UI
components and the SvelteKit proxy route are intentionally exercised via
Playwright E2E rather than vitest unit tests. The "missing" lines are
mostly Svelte component templates and the API proxy — both better tested
against a running stack than in isolation.

When raising frontend coverage, prioritise in this order:

1. Branch coverage in `lib/stores/chat.ts` (currently 88.46%) — these are
   pure TypeScript and easy to unit-test.
2. `lib/components/Reference.svelte` and `MessageList.svelte` — citation
   rendering is the core trust mechanism and worth a focused unit test
   even though it is also covered E2E.
3. `routes/api/[...path]/+server.ts` — the proxy is small but security-
   relevant; a unit test for header forwarding would be cheap.

### What we do not measure here

- Playwright E2E coverage. The E2E suite under `frontend/tests/` runs
  against a live `docker compose` stack and is the primary check for the
  chat flow, streaming, and references rendering.
- Visual regression. Out of scope for this baseline.

## End-to-end testing (Playwright)

Since 2026-04-30 (PR #87), the project has a Playwright harness with 9
first test cases living in `frontend/tests/e2e/`. Run via:

- `make e2e` — full suite against the local stack
- `make e2e-suite SUITE=chat` — single suite (chat | admin | health)
- `make e2e-regression IMAGE_TAG=X.Y.Z-rc.N` — regression on a deployed rc
- `make e2e-report` — open the HTML report

The tester agent (Issue #79, in flight) will:

- Comment acceptance test plans on feature issues during spec review
- Translate plans into executable `.spec.ts` files alongside the frontend
  agent's feature work
- Run regression on every rc and write reports under `reports/test-runs/`
- File bugs (`test-failure`, `flaky-test`, `coverage-drop`) for PM to
  triage; PM owns the priority decision
- Track coverage delta vs the baselines documented above (Issue #85)

E2E does not run in CI on every PR — the suite is invoked explicitly: by
the human, by the tester agent in chat, after an rc tag, or by the
weekly cron once Issue #86 lands. See
[`frontend/tests/e2e/README.md`](../frontend/tests/e2e/README.md) for
operator instructions and (when filed) `docs/test-runbook.md` for the
tester's runbook.
