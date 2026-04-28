#!/usr/bin/env bash
# Prepare a release: bump VERSION, update CHANGELOG, update compose, commit.
# DOES NOT push tags. The human runs `git push origin vX.Y.Z` after PR merge.
#
# Usage:
#   scripts/release.sh major     # bump major
#   scripts/release.sh minor     # bump minor
#   scripts/release.sh patch     # bump patch
#   scripts/release.sh dry       # show what would happen (defaults to patch)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="VERSION"
COMPOSE_FILE="docker-compose.prod.yml"
CHANGELOG_FILE="CHANGELOG.md"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: $0 {major|minor|patch|dry}

  major  Bump major (X.0.0)
  minor  Bump minor (x.Y.0)
  patch  Bump patch (x.y.Z)
  dry    Show what would happen with a patch bump (no writes)
EOF
}

LEVEL="${1:-}"
if [ -z "$LEVEL" ]; then
  usage
  exit 1
fi

case "$LEVEL" in
  major|minor|patch|dry) ;;
  -h|--help) usage; exit 0 ;;
  *) usage; exit 1 ;;
esac

DRY_RUN=0
if [ "$LEVEL" = "dry" ]; then
  DRY_RUN=1
  LEVEL="patch"
fi

# --- Preflight checks -------------------------------------------------------

# VERSION must exist and be well-formed (X.Y.Z)
if [ ! -f "$VERSION_FILE" ]; then
  die "$VERSION_FILE is missing."
fi

CURRENT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
if ! printf '%s' "$CURRENT_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  die "$VERSION_FILE contains a malformed version: '$CURRENT_VERSION' (expected X.Y.Z)"
fi

# Must be on a feature branch, not main
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "main" ]; then
  die "On 'main'. Release prep must happen on a feature branch — create one first."
fi

# Working tree must be clean (ignore untracked files)
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "Working tree is dirty. Commit or stash changes before running release prep."
fi

# Compute new version
IFS='.' read -r MAJ MIN PAT <<EOF
$CURRENT_VERSION
EOF

case "$LEVEL" in
  major) MAJ=$((MAJ + 1)); MIN=0; PAT=0 ;;
  minor) MIN=$((MIN + 1)); PAT=0 ;;
  patch) PAT=$((PAT + 1)) ;;
esac

NEW_VERSION="${MAJ}.${MIN}.${PAT}"
TAG="v${NEW_VERSION}"
TODAY="$(date +%Y-%m-%d)"

# Tag must not already exist locally
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  die "Tag ${TAG} already exists locally. Delete it or pick a different bump level."
fi

# --- Plan output ------------------------------------------------------------

echo "Release plan:"
echo "  Branch:       $CURRENT_BRANCH"
echo "  Current:      $CURRENT_VERSION"
echo "  New:          $NEW_VERSION  (level: $LEVEL)"
echo "  Tag (later):  $TAG"
echo "  Date:         $TODAY"
echo
echo "Files to update:"
echo "  - $VERSION_FILE         ($CURRENT_VERSION -> $NEW_VERSION)"
echo "  - $COMPOSE_FILE         (IMAGE_TAG default: $CURRENT_VERSION -> $NEW_VERSION)"
if [ -f "$CHANGELOG_FILE" ]; then
  echo "  - $CHANGELOG_FILE             ([Unreleased] -> [$NEW_VERSION] - $TODAY)"
else
  echo "  - $CHANGELOG_FILE             (missing — will skip with warning)"
fi
echo
echo "Commit message: 'Bump version to $NEW_VERSION for release'"
echo
echo "After PR merge, the human runs:"
echo "  git push origin $TAG"
echo

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run — no changes made."
  exit 0
fi

# --- Apply changes ----------------------------------------------------------

# 1. VERSION
printf '%s\n' "$NEW_VERSION" > "$VERSION_FILE"
echo "Updated $VERSION_FILE"

# 2. docker-compose.prod.yml — replace IMAGE_TAG default for all services.
# Match `${IMAGE_TAG:-OLD}` literally and replace OLD with NEW.
if [ -f "$COMPOSE_FILE" ]; then
  # macOS/BSD sed and GNU sed both accept `-i.bak` then we remove the backup.
  sed -i.bak "s|\${IMAGE_TAG:-${CURRENT_VERSION}}|\${IMAGE_TAG:-${NEW_VERSION}}|g" "$COMPOSE_FILE"
  rm -f "${COMPOSE_FILE}.bak"
  echo "Updated $COMPOSE_FILE"
else
  echo "WARNING: $COMPOSE_FILE not found — skipped."
fi

# 3. CHANGELOG.md — promote [Unreleased] section to [NEW] - DATE.
if [ -f "$CHANGELOG_FILE" ]; then
  # Build replacement: replace `## [Unreleased]` with a new empty Unreleased
  # section followed by the released section header.
  TMP="$(mktemp)"
  awk -v new="$NEW_VERSION" -v today="$TODAY" '
    BEGIN { replaced = 0 }
    {
      if (!replaced && $0 ~ /^##[[:space:]]+\[Unreleased\]/) {
        print "## [Unreleased]"
        print ""
        print "## [" new "] - " today
        replaced = 1
        next
      }
      print
    }
  ' "$CHANGELOG_FILE" > "$TMP"

  if cmp -s "$CHANGELOG_FILE" "$TMP"; then
    echo "WARNING: $CHANGELOG_FILE has no [Unreleased] section — left unchanged."
    rm -f "$TMP"
  else
    mv "$TMP" "$CHANGELOG_FILE"
    echo "Updated $CHANGELOG_FILE"
  fi
else
  echo "WARNING: $CHANGELOG_FILE not found — skipped (Issue #32 will create it)."
fi

# 4. Stage and commit
git add "$VERSION_FILE" "$COMPOSE_FILE"
if [ -f "$CHANGELOG_FILE" ]; then
  git add "$CHANGELOG_FILE"
fi

git commit -m "Bump version to ${NEW_VERSION} for release"

echo
echo "Release prep committed on branch '$CURRENT_BRANCH'."
echo
echo "Next steps:"
echo "  1. Push the branch and open a PR:    git push -u origin $CURRENT_BRANCH"
echo "  2. After PR merges to main:          git checkout main && git pull"
echo "  3. Tag the release commit:           git tag $TAG"
echo "  4. Push the tag to trigger publish:  git push origin $TAG"
