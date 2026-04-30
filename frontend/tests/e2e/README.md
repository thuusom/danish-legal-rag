# End-to-end tests

Playwright tests for the Danish Legal RAG chat UI and admin page.

## Prerequisites

A running stack reachable on `$E2E_BASE_URL` (default `http://localhost:3000`):

```bash
docker compose up -d --build
docker compose logs -f ingest      # wait for "Ingestion Complete"
```

The `chat.spec.ts` golden-path test requires a real LLM provider — `mock`
won't produce citations to retsinformation.dk. Set `LLM_PROVIDER` in your
compose env accordingly.

## First-time setup

```bash
make e2e-install         # installs Chromium for Playwright (~90 MB)
```

## Run all tests (local stack)

```bash
make e2e
```

## Run a specific suite

```bash
make e2e-suite SUITE=chat
make e2e-suite SUITE=admin
make e2e-suite SUITE=health
```

## Against a remote test environment

```bash
E2E_BASE_URL=http://test.example.local:9240 make e2e
```

## Full regression on a release candidate

Requires `TEST_HOST` set and rc images on GHCR.

```bash
TEST_HOST=tc@test.example.local make e2e-regression IMAGE_TAG=1.2.0-rc.1
```

Deploys the rc to the test host via `make deploy-test`, then runs the
full Playwright suite against `http://test.example.local:9240`.

## View HTML report

```bash
make e2e-report          # opens browser
```

## Tuning timeouts

Slow LLMs (e.g. `llama3.3:70b` on local Ollama) can blow past the default
60s wait for the chat response. Override:

```bash
PLAYWRIGHT_LLM_TIMEOUT_MS=180000 npm run e2e
```

## Test layout

- `health.spec.ts` — backend smoke (no UI)
- `chat.spec.ts` — chat UI flows (golden path, streaming, law filter)
- `admin.spec.ts` — admin page (corpus listing, operator controls)

Tests run in serial (`workers: 1`) because the backend state (cache,
ingestion run flag) is shared.

## Artifacts

Failing tests produce screenshots and traces under
`frontend/test-results/`. The HTML report lives in
`frontend/playwright-report/`. Both directories are gitignored.
