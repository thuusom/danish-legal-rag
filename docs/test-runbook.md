# Tester runbook

Operator runbook for the tester agent. The agent runs in two modes:
ad-hoc suite (during development) and full regression (against a
release candidate). Both produce a report under `reports/test-runs/`
and route bugs to the PM agent.

For agent identity and rules, see `.claude/agents/tester.md`.
For coverage policy and baselines, see `docs/test-strategy.md`.
For the release flow that gates on regression, see
`docs/release-process.md`.

## Quick reference

| Command | Effect |
|---|---|
| `make e2e-install` | One-time Playwright + Chromium install |
| `make e2e-suite SUITE=chat` | Single suite (chat \| admin \| health) on dev |
| `make e2e` | Full suite on the local dev stack |
| `IMAGE_TAG=X.Y.Z-rc.N TEST_HOST=... make e2e-regression` | Full regression against rc on test host |
| `make e2e-report` | Open the HTML Playwright report |

## Prerequisites

- Stack reachable on `$E2E_BASE_URL` (default `http://localhost:3000`)
  for suite mode, OR `$TEST_HOST` set for regression mode
- Playwright installed: `make e2e-install` (one-time, ~90 MB)
- For regression: `.env.test` populated locally (see
  `.env.test.example`); `TEST_HOST` set; an rc tag pushed to GHCR
  (release agent's job — see `docs/release-process.md` step A)

## Mode A — ad-hoc suite

Use case: during development, validate a single area on the dev stack.

Bring the dev stack up first:

```bash
docker compose up -d --build
docker compose logs -f ingest      # wait for "Ingestion Complete"
```

Then run a suite:

```bash
# Single suite
make e2e-suite SUITE=chat
make e2e-suite SUITE=admin
make e2e-suite SUITE=health

# All suites against the dev stack
make e2e
```

After the run, the tester agent (or a human) writes
`reports/test-runs/{timestamp}-suite-{label}.md` based on
`frontend/test-results/results.json`.

In suite mode, bugs are filed only when explicitly requested — the
report is for visibility, not policing. This keeps friction low while
iterating.

The `chat.spec.ts` golden-path test requires a real LLM provider —
`mock` will not produce citations to retsinformation.dk. Set
`LLM_PROVIDER` in your compose env accordingly before running the
chat suite.

## Mode B — full regression on rc

Use case: a release candidate has been auto-published by the release
agent. Validate it before promoting to a final release.

```bash
TEST_HOST=tc@test.example.local IMAGE_TAG=1.2.0-rc.1 make e2e-regression
```

What this does, end to end:

1. SSH to `$TEST_HOST` (via `scripts/deploy-test.sh up`), scp
   `docker-compose.test.yml` and `.env.test` to `~/danish-legal-rag-test`
2. Pull the rc images and bring up the stack on ports 9220-9290
3. Wait for `/health` to respond on port 9230 (90s timeout, 5s
   interval) and verify each compose service is in an acceptable state
4. Run the full Playwright suite with
   `E2E_BASE_URL=http://${TEST_HOST_HOSTNAME}:9240`
5. Save the JSON results to `frontend/test-results/results.json` and
   the HTML report to `frontend/playwright-report/`

Then write `reports/test-runs/{timestamp}-regression-{rc-tag}.md`
including:

- Per-test PASS / FAIL / SKIP status
- Coverage delta vs baselines in `docs/test-strategy.md` (regression
  mode only — see "Coverage policy" below)
- One bug ticket per failure, labeled `test-failure` (or `flaky-test`
  if intermittent, or `coverage-drop` for coverage regressions)
- Verdict: `PASS — promote rc`, `FAIL — do not promote`, or
  `FAIL — flaky, requires investigation`

The tester agent does NOT decide priority on filed bugs. PM triages.

Note: the end-to-end regression flow has not yet been exercised
against a real test host. Mode A has been verified against the local
dev stack (PR #87, 9 specs passing). Treat the steps above as the
intended contract; expect minor fixes on the first real rc.

## Report format

The canonical template lives in `.claude/agents/tester.md` under the
"Test-run report template" section. An example file is at
`reports/test-runs/2026-04-30T14-00-00Z-example-suite-chat.md`.

File-naming convention (from `reports/test-runs/README.md`):

- `{ISO-timestamp}-{mode}-{label}.md` where colons in the timestamp
  are replaced with hyphens
- `mode` is `suite` or `regression`
- `label` is the suite name (`chat`, `admin`, `health`, `all`) or the
  rc tag for regression (`v1.2.0-rc.1`)

## Bug-filing template

```
Title: Test failure: {test_name}
Labels: bug, test-failure  (or flaky-test, or coverage-drop)
Body:
- Test: {file}::{name}
- Run: reports/test-runs/{filename}
- Failure: {message from Playwright}
- API logs: {docker compose logs api --tail 50, relevant lines}
- Browser console: {Playwright trace excerpt if e2e}
- Reproduction: {single-test command, e.g. `make e2e-suite SUITE=chat`}
- Expected: {assertion}
- Actual: {observation}
```

The PM picks priority and assigns to backend, frontend, or tester
(for flaky tests).

## Coverage policy

- Coverage is reported in regression mode only. Suite mode is too
  narrow to be informative and is skipped.
- Compare current coverage to the baselines in `docs/test-strategy.md`
  (backend statements, frontend statements / branches / functions /
  lines).
- Drop > 2%: file a `coverage-drop` issue with the modules affected.
- Drop > 5%: recommend BLOCKING the rc promotion in the report's
  Verdict section.

Backend coverage is collected via `make coverage` inside the api
container; frontend via `npm run coverage` in `frontend/`. See
`docs/test-strategy.md` for the caveats on what these numbers do and
do not measure (notably, the api/* integration paths report 0% because
`pytest --cov` does not cross the uvicorn process boundary).

## When to run regression

- After every rc tag push (the release agent prompts the human in
  chat; see `docs/release-process.md` step B)
- Weekly via `.github/workflows/weekly-regression.yml` (Issue #86,
  pending — not yet implemented)
- On demand when a backend or frontend change might have user-visible
  impact and the human asks

## Common failure modes

The table below lists symptoms that have been observed during
development of the harness (PR #87) and during the suite-mode runs
since. The regression flow has not yet been exercised against a real
test host, so the entries marked "(theoretical)" are extrapolated
from `scripts/deploy-test.sh` and not yet seen in practice.

| Symptom | Likely cause | Fix |
|---|---|---|
| Playwright "browser not installed" | First-time setup skipped | `make e2e-install` |
| Chat test fails with no citation | `LLM_PROVIDER=mock` set in compose env | Set `LLM_PROVIDER=anthropic` (or another real provider) and restart `api` |
| Admin test selector mismatch | Stale selector from a refactor | Use `data-testid` selectors; see PR #87 fix that switched from `nth-child(3)` to `data-testid='law-row'` |
| Chat law-filter test fails on `selectOption(/.../)` | Playwright's `selectOption` does not accept regex | Pass the law code value directly (e.g. `'AFL'`); see PR #87 |
| LLM tests time out | Slow LLM provider (e.g. Ollama on a small box) | `PLAYWRIGHT_LLM_TIMEOUT_MS=180000 make e2e` |
| `TEST_HOST not set` (theoretical) | Env var missing | `export TEST_HOST=tc@test.example.local` |
| `Cannot SSH to '$TEST_HOST' non-interactively` (theoretical) | Key not loaded or host unreachable | `ssh-add -l`; run `ssh "$TEST_HOST" true` to reproduce |
| `/health` never responds within 90s (theoretical) | Rc images failed to pull, or stack failed to start | Check `GHCR_TOKEN`, image names, that the rc tag exists on GHCR; inspect the log dump from `deploy-test.sh` |
| `docker compose pull` fails on test host (theoretical) | Rc tag not yet on GHCR | Wait for `release.yml` (`gh run watch`); confirm tag exists with `gh release list` |
| Tests pass locally, fail on test host (theoretical) | Env drift, different LLM provider, different corpus | Diff `.env.test` against the dev compose env; verify the test host's `LLM_PROVIDER` matches what the test suite expects |

When a new failure mode shows up in practice, append a row to this
table in the same PR that fixes it.

## Cross-references

- `.claude/agents/tester.md` — tester persona and the canonical
  report template
- `docs/test-strategy.md` — coverage baselines and policy
- `frontend/tests/e2e/README.md` — operator-level commands
- `docs/release-process.md` — release flow that gates on regression
- `reports/test-runs/README.md` — report file-naming convention and
  why these are committed
- `scripts/deploy-test.sh` — the deploy mechanism used by
  `make e2e-regression`
- `Makefile` — `e2e`, `e2e-suite`, `e2e-regression`, `e2e-report`,
  `e2e-install` targets
