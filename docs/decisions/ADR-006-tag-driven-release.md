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
