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
| `.github/workflows/release.yml` | push of `v*.*.*` tag | release agent / operator | See "Release publish" below; usually re-tag after fixing root cause |

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

## Release publish (`release.yml`)

**Trigger:** push of a tag matching `v*.*.*` to the repo. Branch pushes
and PRs do not trigger it. The human is the only entity that pushes the
tag — see `docs/release-process.md` and ADR-006 for the rationale.

**What it does:**

1. Checkout with full history (so the CHANGELOG section can be extracted).
2. **Verify VERSION matches the tag.** Strips the leading `v` from
   `github.ref_name` and compares to the contents of `VERSION`. If they
   disagree, the workflow fails hard before any image is built or pushed.
   This is the safety net that catches a mis-tagged release.
3. Set up Docker Buildx and log in to GHCR using `secrets.GHCR_TOKEN`.
4. `make prod-build` — builds api, ingest, frontend at `:$(VERSION)`.
5. `make prod-push` — pushes the three versioned tags to
   `ghcr.io/thuusom/danish-legal-rag-{api,ingest,frontend}`.
6. Re-tag and push `:latest` for each of the three images.
7. Extract the matching `## [X.Y.Z]` section from `CHANGELOG.md` (awk
   block from the version header to the next `## [` line).
8. Create a GitHub Release named after the tag with the extracted
   CHANGELOG section as the body.

**Required secret:** `GHCR_TOKEN` — Personal Access Token with
`write:packages` scope. One-time setup at github.com/settings/tokens; the
token is added to the repo at Settings → Secrets and variables → Actions.

**Operator runbook:** `docs/release-process.md` is the canonical
end-to-end guide (decide bump level → invoke release agent → review →
PR → merge → push tag → verify). Always read it before cutting a release.

**Failure response (most common cases):**

- *Tag does not match VERSION file* — the `Verify VERSION matches tag`
  step failed. Delete the bad tag (`git tag -d` and `git push origin
  --delete`), fix VERSION (or push the correct tag), re-push.
- *Image build failed* — reproduce locally with `make prod-build`. The
  release agent should never be the discovery moment for a broken build.
- *GHCR push failed (auth)* — `GHCR_TOKEN` is missing or expired. Rotate
  at github.com/settings/tokens and update the repo secret. Re-tag.
- *CHANGELOG section is empty* — the GitHub Release body will be blank.
  Fix CHANGELOG.md on main, delete the bad release with `gh release
  delete`, re-tag.

See the troubleshooting section of `docs/release-process.md` for more.

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
