# ADR-006: Tag-driven release with human-in-the-loop

**Status:** Accepted
**Date:** 2026-04-28
**Context owner:** release agent, reviewed by Thomas

## Context

The v1.0.0 release was orchestrated manually through chat: bumping
`VERSION`, building and pushing GHCR images, drafting Release notes, and
tagging git were separate steps with no clear owner. Three identifiers had
to stay in lockstep — the git tag, the `VERSION` file, and the GHCR image
tags — and nothing enforced that. A typo silently ships a release where
"what is tagged" disagrees with "what is running in production."

This worked once. It does not scale and is the kind of process that fails
the second time it is exercised under time pressure.

## Decision

Adopt a tag-driven release model with one human-controlled step.

- A release agent prepares everything on a `release/vX.Y.Z` branch: bumps
  `VERSION`, adds a CHANGELOG entry, updates `IMAGE_TAG` defaults in
  `docker-compose.prod.yml`, opens a PR.
- Thomas reviews and merges to `main`. Nothing ships yet.
- Thomas then runs `git push origin vX.Y.Z` — the only irreversible step,
  and the only one that requires a human.
- `.github/workflows/release.yml` triggers on tag push. It first verifies
  the tag matches `VERSION`. If they disagree, it fails hard and ships
  nothing. Otherwise it builds and pushes the three images to GHCR with
  both `:X.Y.Z` and `:latest`, then creates the GitHub Release with the
  matching CHANGELOG section as the body.

## Consequences

**Positive:**

- Single source of truth for "this is released" is the git tag. Image
  tags, GitHub Release, CHANGELOG version are all derived from it.
- The `VERSION` ↔ tag check makes drift impossible: a forgotten bump
  becomes a CI failure, not a mis-versioned production image.
- Operator burden after merge is one command.
- The irreversible action stays in human hands. The agent cannot publish.

**Negative:**

- Requires a GHCR push token in repo secrets. Already provisioned as
  `GHCR_TOKEN`.
- Two-step ritual (merge, then push tag) is slightly heavier than a
  single click, but the separation is the safety property.

## Alternatives considered

- **Agent pushes the tag.** Rejected. Tag pushes are effectively
  irreversible for downstream consumers; not appropriate to fully
  automate at this stage.
- **Manual everything (status quo from v1.0.0).** Rejected. Worked once,
  does not scale, concentrates release knowledge in chat history.
- **Trigger on GitHub Release creation instead of tag push.** Rejected as
  circular: the workflow itself authors the Release, so it cannot also be
  the trigger.

## Amendment: pre-release flow (2026-04-30)

Issue #57 extended this decision with a release-candidate (rc) flow:

- `make release-rc` bumps VERSION to `X.Y.Z-rc.N` (scope inherited or
  overridden via `RC_LEVEL`). **The release script auto-pushes the
  branch and the rc tag** — no human-in-the-loop for rc, because rc
  images can't reach prod and don't update `:latest`. The consistency
  check in `release.yml` still gates the build. (Final releases retain
  the human-only tag-push rule from the original decision.)
- `release.yml` detects the `-rc.N` suffix and:
  - Pushes only `:X.Y.Z-rc.N` images (no `:latest` poisoning)
  - Marks the GitHub Release as pre-release
  - Falls back to a generic body when CHANGELOG has no matching section
    (rc bumps deliberately do not promote `[Unreleased]`)
- **rc images are test-environment-only and never deployed to
  production.** The release script does NOT update the
  `docker-compose.prod.yml` `IMAGE_TAG` default on rc bumps. Prod stays
  pinned to the last final release. Test deploys pass
  `IMAGE_TAG=X.Y.Z-rc.N` explicitly to `make deploy-test`.
- Final releases consume an in-flight rc: `make release-minor` while
  VERSION is `X.Y.Z-rc.N` produces `X.Y.Z`, but the level must match the
  rc's scope.

The original decision (final-only flow) remains valid; this is an
extension, not a supersession. See `docs/release-process.md` for the
operator runbook and ADR-007 for the test environment definition.
