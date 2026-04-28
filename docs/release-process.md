# Release process

This document is the operator runbook for releasing Danish Legal RAG.
Releases are tag-driven: the release agent prepares; the human pushes
the tag; `.github/workflows/release.yml` publishes.

For why, see `docs/decisions/ADR-006-tag-driven-release.md`.
For the full agent role, see `.claude/agents/release.md`.

## Prerequisites

- Clean working tree on `main`
- All changes for the release are merged to `main`
- You can `git push` to `origin`
- The repo has `GHCR_TOKEN` secret set (one-time setup; persists)

## Steps

### 1. Decide bump level

| Change type | Bump | Examples |
|---|---|---|
| Breaking API change | major | Remove or rename a field, change auth model |
| Additive feature | minor | New endpoint, new law in corpus, new agent |
| Bug fix or doc | patch | Fix a regression, fix a typo, dependency bump |

If unsure, ask. Semver matters because external consumers may pin.

### 2. Invoke the release agent

In Claude Code, on a fresh release branch:

```bash
git checkout -b release/v{NEW_VERSION}
```

Then in chat: `release minor` (or major / patch).

The agent runs `make release-prepare` which:

- Bumps VERSION
- Updates docker-compose.prod.yml IMAGE_TAG defaults
- Moves CHANGELOG `[Unreleased]` content into a new `[X.Y.Z]` section
- Commits the result

### 3. Review the commit

`git show HEAD` — verify:

- VERSION shows the new version
- CHANGELOG has a coherent entry under `[X.Y.Z]` (not just empty bullets)
- docker-compose.prod.yml shows updated IMAGE_TAG defaults

If CHANGELOG looks bare, the agent should regenerate from
`make release-notes` and curate before commit.

### 4. Open PR and merge

```bash
git push -u origin release/v{X.Y.Z}
gh pr create --title "Release v{X.Y.Z}" --body "..."
```

Review, merge to main.

### 5. Push the tag (the only human-only step)

After merge, locally on `main`:

```bash
git checkout main
git pull
git tag v{X.Y.Z}
git push origin v{X.Y.Z}
```

This triggers `.github/workflows/release.yml`.

### 6. Verify

- `gh run watch` — watch the workflow
- `gh release view v{X.Y.Z}` — confirm release page exists
- Check `https://github.com/thuusom/danish-legal-rag/pkgs/container/danish-legal-rag-api`
  for the new tag

## Troubleshooting

### "Tag does not match VERSION file"

The release.yml workflow failed at the consistency check. This means
the tag you pushed (e.g., `v1.2.0`) doesn't match the `VERSION` file
content on main (e.g., `1.1.0`).

Fix:

1. Delete the tag locally and remotely:

   ```bash
   git tag -d v1.2.0
   git push origin --delete v1.2.0
   ```

2. Either bump VERSION to match, or push the correct tag.

### Workflow fails after image build

Check the workflow logs. Common causes:

- `GHCR_TOKEN` secret is missing or expired (rotate at
  github.com/settings/tokens)
- Docker build broke (test locally with `make prod-build`)
- GHCR rate limit (rare for this project)

### CHANGELOG section is empty

The release.yml workflow expects `## [X.Y.Z]` section in CHANGELOG.md.
If the section is empty, the GitHub Release will have an empty body.
Edit CHANGELOG.md, push to main as a fix, delete the bad release with
`gh release delete v{X.Y.Z}`, and re-tag.

## What if I need to roll back?

We don't unrelease tags. To "fix" a bad release:

1. File an issue describing the regression
2. Cut a patch release (e.g., v1.0.1) with the fix
3. Note the deprecation in CHANGELOG

GHCR images stay available indefinitely; consumers can pin to a known-good
version.
