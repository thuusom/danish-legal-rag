# Test strategy

This document records the project's automated test posture: what each layer
covers, how coverage is measured, and the current baseline numbers.

Coverage is **informational** today. CI does not gate on a coverage
threshold; this file is the single place where the team can see whether
the trend is going in the right direction over time.

## Backend (placeholder)

> Owner: backend agent (Issue #68). This section will be populated when the
> backend coverage tooling lands. Frontend has filed its baseline below
> ahead of that work.

- Tooling: pytest + coverage.py (planned)
- Headline coverage: _to be filled in by backend agent_
- Date measured: _pending_

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
