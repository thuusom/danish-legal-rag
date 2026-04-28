# GitHub workflows

Single reference for everything in this repo that touches GitHub: scheduled
jobs, CI, image publishing, issue templates, and branch rules. Read this
first when an automated issue appears, when CI fails, or before adding a
new workflow.

## Quick reference

| File | Trigger | Owner | What to do on failure |
|------|---------|-------|-----------------------|
| `.github/workflows/ci.yml` | push to `feat/*`, PRs to `main` | backend / frontend | Read failed step logs, fix, push again |
| `.github/workflows/check-law-currency.yml` | daily 06:00 UTC + manual | pm / operator | Investigate `fetch-failed` rows; act on `stale-law,auto` issues |
| (no release workflow yet) | manual `make prod-push` | pm | See "GHCR image publishing" below |

---

## CI (`ci.yml`)

**Trigger:** push to any `feat/*` branch and pull requests targeting `main`.
Concurrent runs on the same ref are auto-cancelled.

**Jobs:**

1. `unit` — installs Python 3.11 + ruff + pytest, runs `ruff check .` and
   the embedding unit tests (`tests/test_embeddings.py`, `-m "not slow"`).
   Timeout 5 min.
2. `frontend-lint` — when `frontend/` exists, installs npm deps, runs ESLint
   and `npm run check` (svelte-check). Timeout 5 min.
3. `integration` — boots the full stack via `docker compose up -d qdrant
   api`, runs the ingestion job, executes `make test-integration`, and
   verifies the contract has not drifted. Timeout 25 min. Uses
   `LLM_PROVIDER=mock`, so no API keys are needed. Caches both the Docker
   build layers and the ~440 MB HuggingFace model across runs.

**Failure response:**

- Unit / lint failures: read the failed step in the run log, reproduce
  locally with `ruff check .` or `pytest tests/test_embeddings.py`, fix,
  push again.
- Integration failures: the workflow uploads `docker compose logs` on
  failure. Reproduce locally with `make up && make ingest && make
  test-integration`.
- Contract drift: `make contract-verify` runs with `continue-on-error`
  (the curated spec intentionally diverges from FastAPI auto-output), so
  this is informational, not blocking.

**Manual setup:** none. Vanilla `GITHUB_TOKEN` is sufficient.

---

## Daily law currency check (`check-law-currency.yml`)

**Trigger:** cron `0 6 * * *` (06:00 UTC, ~07:00 / ~08:00 Europe/Copenhagen
depending on DST) plus `workflow_dispatch` for ad-hoc runs.

**What it does:**

1. Installs `ingest/requirements.txt`.
2. Ensures the `stale-law` and `auto` labels exist (idempotent
   `gh label create --force`).
3. Runs `python -m ingest.law_fetcher --dry-run` against
   `retsinformation-api.dk`, writing `law_cache/currency-report.json` to
   the runner's ephemeral workspace. Production data is never touched —
   the runner has its own throw-away cache.
4. Uploads the report as an artifact (`currency-report`) for inspection.
5. Walks the report and manages issues (see lifecycle below).

**Auto-issue lifecycle (`stale-law,auto`):**

- `status: new` or `status: updated` → opens a new issue titled
  `Stale law: {law_code} — v{ours} -> v{latest}`, or updates the existing
  one if the version has moved further ahead.
- `status: up-to-date` for a law that has an open `stale-law,auto` issue
  → auto-closes the issue with a confirmation comment.
- `status: fetch-failed` → left alone for the operator to investigate. Not
  an auto-issue case (intentional; transient network errors should not
  spam issues).

**Operator response when an issue fires:**

1. Run the fetcher against the real cache:
   ```bash
   make fetch-laws
   ```
   (or in production: `docker compose exec api python -m ingest.law_fetcher`,
   then `docker compose restart` as appropriate).
2. Re-ingest:
   ```bash
   make ingest
   ```
   The ingestion is idempotent (per-law delete-then-insert, see
   [ADR-005](decisions/ADR-005-idempotent-reingestion.md)), so unchanged
   provisions skip embedding.
3. The next scheduled workflow run sees the cache match upstream and
   auto-closes the issue. Nothing else to do.

**Rate-limit considerations:** the fetcher uses ~12 calls per run, well
under the 50/day API budget published by retsinformation-api.dk.

**Manual setup:** none — labels self-create on first run. References:
[ADR-003](decisions/ADR-003-retsinformation-api-as-primary-source.md) for
the source choice, [ADR-004](decisions/ADR-004-update-only-fetcher-with-seed.md)
for the update-only model.

---

## GHCR image publishing (manual today)

There is no CI workflow for image publishing. Releases are cut manually:

```bash
make prod-build   # tags ghcr.io/thuusom/danish-legal-rag-{api,ingest,frontend}:$(VERSION)
make prod-push    # pushes the three images to GHCR
```

`VERSION` is read from the `VERSION` file at the repo root.

**Required setup (one time, on the operator's machine):**

```bash
docker login ghcr.io -u thuusom
# Paste a Personal Access Token with scope: write:packages, read:packages
```

The PAT also needs `repo` scope if the package visibility is private.

**Future:** add `.github/workflows/release.yml` triggered by version tags
(`v*`) that builds and pushes via `docker/build-push-action`. Would need
GHCR credentials in repo secrets (`GHCR_USERNAME`, `GHCR_TOKEN`). Tracked
informally — file an issue when the release cadence justifies it.

---

## Issue templates

Templates live at `.github/*.md` (this repo does not use the
`ISSUE_TEMPLATE/` subdirectory convention; the templates work either way
because they have YAML frontmatter):

- `backend-task.md` — backend agent work; includes API contract impact and
  MCP-still-works checks in the DoD.
- `frontend-task.md` — frontend agent work; includes contract-readiness
  gate (do not start until the API exists in `contracts/openapi.yaml`).
- `feature-parent.md` — multi-agent feature with child issues and an
  explicit end-to-end integration test the PM keeps open until proven.

To use a template manually with `gh`:

```bash
gh issue create --label backend --body-file .github/backend-task.md
```

---

## PR workflow

See `CLAUDE.md` for the full coordination model. Summary:

- One PR per issue. PR description references the issue number.
- PRs target the active feature branch (currently long-lived feature
  branches per phase, not direct-to-`main`). The feature branch is merged
  to `main` when the phase is complete.
- Contract-touching PRs must update `contracts/openapi.yaml` in the same
  PR. The CI integration job warns on drift but does not block.
- Tests are non-negotiable: no PR merges on "looks fine".

---

## Branch protection

`main` has no protection rules configured (verified via
`gh api repos/thuusom/danish-legal-rag/branches/main/protection` →
`Branch not protected`). The repo relies on convention and PR review
rather than enforced rules. Reconsider adding required status checks
(at minimum CI green) once the team grows beyond the current owner.
