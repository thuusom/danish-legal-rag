#!/usr/bin/env bash
# Prepare a release: bump VERSION, update CHANGELOG, update compose, commit.
# DOES NOT push tags. The human runs `git push origin vX.Y.Z` after PR merge.
#
# Usage:
#   scripts/release.sh major         # bump major
#   scripts/release.sh minor         # bump minor
#   scripts/release.sh patch         # bump patch
#   scripts/release.sh rc            # bump to next rc (pre-release)
#   scripts/release.sh dry [LEVEL]   # show what would happen (default: patch)
#
# rc semantics:
#   - From a final version X.Y.Z (no -rc suffix), `rc` produces a minor
#     pre-release X.(Y+1).0-rc.1 by default. Override the bump scope with
#     RC_LEVEL=major|minor|patch.
#   - From a pre-release X.Y.Z-rc.N, `rc` produces X.Y.Z-rc.(N+1).
#   - Calling minor (or major/patch) while VERSION is X.Y.Z-rc.N consumes
#     the rc into the final X.Y.Z, but only when the level matches the
#     scope encoded in the rc target. Mismatches fail clearly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="VERSION"
COMPOSE_FILE="docker-compose.prod.yml"
CHANGELOG_FILE="CHANGELOG.md"

VERSION_REGEX='^[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$'

die() {
  echo "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: $0 {major|minor|patch|rc|dry [LEVEL]}

  major  Bump major (X.0.0)
  minor  Bump minor (x.Y.0)
  patch  Bump patch (x.y.Z)
  rc     Bump to next release candidate (X.Y.Z-rc.N)
         RC_LEVEL=major|minor|patch overrides the default minor scope
         when going from a final version to its first rc.
  dry    Show what would happen with a given bump level (default: patch)
         Example: $0 dry rc
EOF
}

LEVEL="${1:-}"
DRY_LEVEL="${2:-}"
if [ -z "$LEVEL" ]; then
  usage
  exit 1
fi

case "$LEVEL" in
  major|minor|patch|rc|dry) ;;
  -h|--help) usage; exit 0 ;;
  *) usage; exit 1 ;;
esac

DRY_RUN=0
if [ "$LEVEL" = "dry" ]; then
  DRY_RUN=1
  if [ -n "$DRY_LEVEL" ]; then
    case "$DRY_LEVEL" in
      major|minor|patch|rc) LEVEL="$DRY_LEVEL" ;;
      *) die "Invalid dry level: '$DRY_LEVEL' (expected major|minor|patch|rc)" ;;
    esac
  else
    LEVEL="patch"
  fi
fi

# --- Preflight checks -------------------------------------------------------

# VERSION must exist and be well-formed (X.Y.Z or X.Y.Z-rc.N)
if [ ! -f "$VERSION_FILE" ]; then
  die "$VERSION_FILE is missing."
fi

CURRENT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
if ! printf '%s' "$CURRENT_VERSION" | grep -Eq "$VERSION_REGEX"; then
  die "$VERSION_FILE contains a malformed version: '$CURRENT_VERSION' (expected X.Y.Z or X.Y.Z-rc.N)"
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

# --- Parse current version --------------------------------------------------

# Split into base (X.Y.Z) and optional rc counter.
CUR_BASE="${CURRENT_VERSION%-rc.*}"
CUR_RC=""
if [ "$CUR_BASE" != "$CURRENT_VERSION" ]; then
  CUR_RC="${CURRENT_VERSION#*-rc.}"
fi

IFS='.' read -r MAJ MIN PAT <<EOF
$CUR_BASE
EOF

# --- Compute new version ----------------------------------------------------

IS_RC=0
PROMOTE_CHANGELOG=1
PRE_RC=""

if [ "$LEVEL" = "rc" ]; then
  IS_RC=1
  PROMOTE_CHANGELOG=0
  if [ -n "$CUR_RC" ]; then
    # Already on an rc — bump the counter only.
    NEW_RC=$((CUR_RC + 1))
    NEW_VERSION="${MAJ}.${MIN}.${PAT}-rc.${NEW_RC}"
  else
    # Final → first rc. Default scope is minor; allow override via RC_LEVEL.
    SCOPE="${RC_LEVEL:-minor}"
    case "$SCOPE" in
      major) MAJ=$((MAJ + 1)); MIN=0; PAT=0 ;;
      minor) MIN=$((MIN + 1)); PAT=0 ;;
      patch) PAT=$((PAT + 1)) ;;
      *) die "Invalid RC_LEVEL='$SCOPE' (expected major|minor|patch)" ;;
    esac
    NEW_VERSION="${MAJ}.${MIN}.${PAT}-rc.1"
  fi
else
  # major | minor | patch
  if [ -n "$CUR_RC" ]; then
    # Consuming an rc: the target is fixed by the rc base. The level the
    # human asked for must match the implicit scope of the rc.
    PRE_RC="$CURRENT_VERSION"

    # We don't store the rc's original scope, so we infer it: an rc whose
    # PAT == 0 and MIN > 0 is a minor; PAT == 0 and MIN == 0 (and MAJ > 0)
    # is a major; PAT > 0 is a patch. Any mismatch fails clearly.
    if [ "$PAT" -gt 0 ]; then
      RC_SCOPE="patch"
    elif [ "$MIN" -gt 0 ]; then
      RC_SCOPE="minor"
    else
      RC_SCOPE="major"
    fi

    if [ "$LEVEL" != "$RC_SCOPE" ]; then
      die "Cannot consume rc '$CURRENT_VERSION' with 'release-${LEVEL}'. The rc targets a $RC_SCOPE release; use 'release-${RC_SCOPE}' to ship it, or 'release-rc' to spin another rc."
    fi

    # Consume: drop the -rc.N suffix, base stays as-is.
    NEW_VERSION="${MAJ}.${MIN}.${PAT}"
  else
    # Standard final bump from a final version.
    case "$LEVEL" in
      major) MAJ=$((MAJ + 1)); MIN=0; PAT=0 ;;
      minor) MIN=$((MIN + 1)); PAT=0 ;;
      patch) PAT=$((PAT + 1)) ;;
    esac
    NEW_VERSION="${MAJ}.${MIN}.${PAT}"
  fi
fi

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
if [ "$IS_RC" -eq 1 ]; then
  echo "  New:          $NEW_VERSION  (level: rc, pre-release)"
  echo "  Image tags:   :$NEW_VERSION  (no :latest for rc)"
else
  if [ -n "$PRE_RC" ]; then
    echo "  New:          $NEW_VERSION  (level: $LEVEL, consumes rc $PRE_RC)"
  else
    echo "  New:          $NEW_VERSION  (level: $LEVEL)"
  fi
  echo "  Image tags:   :$NEW_VERSION and :latest"
fi
echo "  Tag (later):  $TAG"
echo "  Date:         $TODAY"
echo
echo "Files to update:"
echo "  - $VERSION_FILE         ($CURRENT_VERSION -> $NEW_VERSION)"
echo "  - $COMPOSE_FILE         (IMAGE_TAG default: $CURRENT_VERSION -> $NEW_VERSION)"
if [ -f "$CHANGELOG_FILE" ]; then
  if [ "$PROMOTE_CHANGELOG" -eq 1 ]; then
    echo "  - $CHANGELOG_FILE             ([Unreleased] -> [$NEW_VERSION] - $TODAY)"
  else
    echo "  - $CHANGELOG_FILE             (left as-is; rc bumps do not promote [Unreleased])"
  fi
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
# Match `${IMAGE_TAG:-OLD}` literally and replace OLD with NEW. Always update,
# even for rc bumps, so `docker compose up` defaults to the in-flight rc.
if [ -f "$COMPOSE_FILE" ]; then
  # macOS/BSD sed and GNU sed both accept `-i.bak` then we remove the backup.
  sed -i.bak "s|\${IMAGE_TAG:-${CURRENT_VERSION}}|\${IMAGE_TAG:-${NEW_VERSION}}|g" "$COMPOSE_FILE"
  rm -f "${COMPOSE_FILE}.bak"
  echo "Updated $COMPOSE_FILE"
else
  echo "WARNING: $COMPOSE_FILE not found — skipped."
fi

# 3. CHANGELOG.md — promote [Unreleased] only for final releases.
#    rc bumps point at the same in-flight content under [Unreleased] and
#    must not lock it into a dated section.
if [ "$PROMOTE_CHANGELOG" -eq 1 ]; then
  if [ -f "$CHANGELOG_FILE" ]; then
    TMP="$(mktemp)"
    awk -v new="$NEW_VERSION" -v today="$TODAY" '
      BEGIN { mode = 0; n = 0 }

      # mode 0: before [Unreleased] — pass through
      # mode 1: collecting under old [Unreleased]
      # mode 2: after promotion — pass through

      mode == 0 {
        if ($0 ~ /^##[[:space:]]+\[Unreleased\]/) {
          # Emit fresh empty [Unreleased] block
          print "## [Unreleased]"
          print ""
          print "### Added"
          print ""
          print "### Changed"
          print ""
          print "### Deprecated"
          print ""
          print "### Removed"
          print ""
          print "### Fixed"
          print ""
          print "### Security"
          print ""
          mode = 1
          next
        }
        print
        next
      }

      mode == 1 {
        # Hitting the next "## [" header means we have captured everything
        # that used to live under [Unreleased].
        if ($0 ~ /^##[[:space:]]+\[/) {
          print "## [" new "] - " today
          print ""
          for (i = 1; i <= n; i++) print buf[i]
          print $0
          mode = 2
          next
        }
        buf[++n] = $0
        next
      }

      mode == 2 { print; next }

      END {
        # [Unreleased] was the last section in the file — flush captured content.
        if (mode == 1) {
          print "## [" new "] - " today
          print ""
          for (i = 1; i <= n; i++) print buf[i]
        }
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
    echo "WARNING: $CHANGELOG_FILE not found — skipped."
  fi
else
  echo "Skipped $CHANGELOG_FILE promotion (rc bumps keep [Unreleased] intact)."
fi

# 4. Stage and commit
git add "$VERSION_FILE" "$COMPOSE_FILE"
if [ -f "$CHANGELOG_FILE" ] && [ "$PROMOTE_CHANGELOG" -eq 1 ]; then
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
