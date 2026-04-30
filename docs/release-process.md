# Release process

This document is the operator runbook for releasing Danish Legal RAG.
Releases are tag-driven: the release agent prepares; the human pushes
the tag; `.github/workflows/release.yml` publishes.

The flow has two stages — cut a release candidate (rc), validate it on
the test environment, then promote a green rc to a final release.

For why, see `docs/decisions/ADR-006-tag-driven-release.md` (with the
"Pre-release flow" amendment) and `docs/decisions/ADR-007-test-environment.md`.
For the full agent role, see `.claude/agents/release.md`.

## Quick reference

| Command | Effect |
|---|---|
| `make release-rc` | Bumps to `X.Y.Z-rc.N`, commits (no tag push) |
| `make release-{patch,minor,major}` | Final bump (or consumes a matching in-flight rc) |
| `make release-dry [LEVEL=rc]` | Shows the plan without changes |
| `make release-notes` | Bullet list of commits since last tag |
| `make deploy-test` | SSH-deploys the rc to `$TEST_HOST` |

`RC_LEVEL=major|minor|patch` overrides the rc's default scope (minor)
when going from a final version to its first rc.

## Prerequisites

- Clean working tree on `main`
- All changes for the release are merged to `main`
- You can `git push` to `origin`
- The repo has `GHCR_TOKEN` secret set (one-time setup; persists)
- For test deploys: `TEST_HOST` env var set and `.env.test` populated at
  repo root (see `.env.test.example`)

## Steps

### A — Cut a release candidate

1. Decide bump scope (major / minor / patch). The rc inherits this scope;
   the final release that consumes it must use the matching `release-*`
   target.

   | Change type | Bump | Examples |
   |---|---|---|
   | Breaking API change | major | Remove or rename a field, change auth model |
   | Additive feature | minor | New endpoint, new law in corpus, new agent |
   | Bug fix or doc | patch | Fix a regression, fix a typo, dependency bump |

2. Cut a release branch:

   ```bash
   git checkout main && git pull
   git checkout -b release/v1.2.0-rc.1
   ```

3. Run `make release-rc`. Defaults to a minor scope; override with e.g.
   `RC_LEVEL=patch make release-rc` or `RC_LEVEL=major make release-rc`.

   The script bumps `VERSION`, updates `IMAGE_TAG` defaults in
   `docker-compose.prod.yml`, and commits — but does NOT push the tag.
   `CHANGELOG.md` is intentionally left as-is (rc bumps do not promote
   `[Unreleased]`).

4. Open a PR, review, merge to main.

5. Push the rc tag (the only human-only step):

   ```bash
   git checkout main && git pull
   git push origin v1.2.0-rc.1
   ```

   This triggers `release.yml`, which:

   - Builds and pushes `ghcr.io/thuusom/danish-legal-rag-{api,ingest,frontend}:1.2.0-rc.1`
   - Does NOT push `:latest`
   - Creates a GitHub Release marked as pre-release

   See `docs/github-workflows.md` for the workflow's behavior in detail.

### B — Deploy the rc to the test environment

1. Ensure `TEST_HOST` is set (e.g. `tc@test.example.local`) and
   `.env.test` exists at the repo root.

2. Run:

   ```bash
   IMAGE_TAG=1.2.0-rc.1 make deploy-test
   ```

   This SSHes to the test host, copies the compose and env file, pulls
   the rc images, brings up the stack on ports 9220-9290, and
   health-checks `/health`. See `docs/decisions/ADR-007-test-environment.md`
   for the port mapping and host model.

3. Verify the deployed environment:

   - `http://$TEST_HOST:9230/health` returns 200
   - Frontend is reachable at `http://$TEST_HOST:9240`
   - Run any smoke or e2e checks you would gate the release on

4. If broken: fix the issue on a feature branch, merge to main, then
   produce the next rc:

   ```bash
   git checkout main && git pull
   git checkout -b release/v1.2.0-rc.2
   make release-rc
   ```

   `make release-rc` from an existing `1.2.0-rc.1` produces `1.2.0-rc.2`,
   then `1.2.0-rc.3`, and so on. Each rc gets its own tag, its own
   pre-release on GitHub, and its own test deploy.

### C — Promote the rc to a final release

When the rc is green:

1. Cut a release branch:

   ```bash
   git checkout main && git pull
   git checkout -b release/v1.2.0
   ```

2. Run the matching final bump — the level MUST match the rc's scope:

   ```bash
   make release-minor
   ```

   If you cut the rc with the default (or `RC_LEVEL=minor`), use
   `release-minor`. For an `RC_LEVEL=patch` rc, use `release-patch`. For
   `RC_LEVEL=major`, use `release-major`. Mismatches fail with a clear
   error from `scripts/release.sh` ("Cannot consume rc … with
   release-X"). The bump consumes the rc by stripping the `-rc.N`
   suffix and promoting `[Unreleased]` to a dated `[1.2.0]` section in
   `CHANGELOG.md`.

3. Open a PR, review, merge to main.

4. Push the final tag:

   ```bash
   git checkout main && git pull
   git push origin v1.2.0
   ```

   `release.yml` builds and pushes `:1.2.0` and re-tags `:latest` for
   each image, then creates a final GitHub Release with the matching
   CHANGELOG section as the body.

### D — Promote to production

Manual today; future: `make deploy-prod`.

1. SSH to the prod host (or use your existing deploy method).
2. Pull and start with the new tag:

   ```bash
   IMAGE_TAG=1.2.0 docker compose -f docker-compose.prod.yml pull
   IMAGE_TAG=1.2.0 docker compose -f docker-compose.prod.yml up -d
   ```

3. Verify `/health` and key user paths.

## Verifying a release in CI

- `gh run watch` — watch the publish workflow as it runs.
- `gh release view v1.2.0` — confirm the release page exists. The
  pre-release (`v1.2.0-rc.1`) and final (`v1.2.0`) entries are separate
  releases on GitHub; the rc is flagged as pre-release.
- Check
  `https://github.com/thuusom/danish-legal-rag/pkgs/container/danish-legal-rag-api`
  for the new tag. Final releases also update `:latest`; rc releases
  do not.

## Troubleshooting

### "Cannot consume rc 'X.Y.Z-rc.N' with 'release-LEVEL'"

The `release-{patch|minor|major}` you ran does not match the scope the
rc was cut at. `scripts/release.sh` infers the rc's scope from the base
version: PAT > 0 → patch, MIN > 0 → minor, otherwise major.

Fix: run the matching `release-{scope}` target. If you cannot recall the
scope, run `make release-dry LEVEL=minor` (or patch / major); the
mismatch error reports the inferred scope.

### "Tag does not match VERSION file"

The `release.yml` consistency check failed: the tag you pushed (e.g.
`v1.2.0-rc.1` or `v1.2.0`) doesn't match the `VERSION` file content on
main. Most common cause: the tag was pushed before the release-prep PR
merged, so `VERSION` on main is still the old value.

Fix:

1. Delete the tag locally and remotely:

   ```bash
   git tag -d v1.2.0-rc.1
   git push origin --delete v1.2.0-rc.1
   ```

2. Make sure the release-prep PR is merged to main, then re-push the
   tag from a freshly pulled main.

### `make deploy-test` cannot SSH to the host

- `TEST_HOST` is not set in your environment, or is set to the wrong
  target. Example: `TEST_HOST=tc@test.example.local make deploy-test`.
- Your SSH key is not loaded (`ssh-add -l`) or the host does not have
  the matching public key in `authorized_keys`.
- The host is unreachable from your network.

The deploy script uses `BatchMode=yes`, so it never prompts for a
password. Run `ssh "$TEST_HOST" true` manually to reproduce the failure
and diagnose.

### `make deploy-test` fails at "docker compose pull"

The rc tag isn't on GHCR yet. Causes:

- The rc tag was pushed but `release.yml` is still running — wait for
  `gh run watch` to finish.
- `release.yml` failed before the push step (typically the
  consistency check). Fix the underlying issue (see "Tag does not
  match VERSION" above) and re-push.
- You typed an `IMAGE_TAG` that doesn't exist. Confirm with
  `gh release list` or the GHCR package page.

### Pre-release CHANGELOG section is missing

`release-rc` deliberately does not promote `[Unreleased]`, so the
GitHub Release for an rc has no matching `## [X.Y.Z-rc.N]` section.
`release.yml` falls back to a generic body
("Pre-release of vX.Y.Z. See [Unreleased] in CHANGELOG.md…"). This is
expected; nothing to fix.

### Final-release workflow fails after image build

Check the workflow logs. Common causes:

- `GHCR_TOKEN` secret is missing or expired (rotate at
  github.com/settings/tokens).
- Docker build broke (test locally with `make prod-build`).
- GHCR rate limit (rare for this project).

### Final-release CHANGELOG section is empty

`release.yml` expects `## [X.Y.Z]` in `CHANGELOG.md`. If the section
is empty after `release-{patch|minor|major}`, the GitHub Release will
have an empty body. Edit `CHANGELOG.md` on main, delete the bad
release with `gh release delete v1.2.0`, and re-push the tag.

## What if I need to roll back?

We don't unrelease tags. To "fix" a bad release:

1. File an issue describing the regression.
2. Cut a patch rc (`make release-rc` with `RC_LEVEL=patch`), validate
   on the test env, then promote to a final patch release.
3. Note the deprecation in `CHANGELOG.md` under `[Unreleased]` so the
   next release inherits the note.

GHCR images stay available indefinitely; consumers can pin to a
known-good version.
