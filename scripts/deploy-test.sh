#!/usr/bin/env bash
# Deploy the pre-release stack to the test host over SSH.
#
# Usage:
#   scripts/deploy-test.sh up      # default — deploy and health-check
#   scripts/deploy-test.sh down    # stop the stack on the host (keep volumes)
#   scripts/deploy-test.sh reset   # stop and remove volumes (clean slate)
#
# Required env vars (read from the caller's environment):
#   TEST_HOST   SSH target, e.g. tc@test.example.local or test.example.local
#   IMAGE_TAG   Image tag to deploy, e.g. 1.2.0-rc.1
#
# Required files at repo root:
#   docker-compose.test.yml
#   .env.test  (gitignored; copied to the host and used as --env-file)
#
# This script never pushes images. Images are published to GHCR by
# .github/workflows/release.yml on tag push; deploy-test only pulls.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

REMOTE_DIR="~/danish-legal-rag-test"
COMPOSE_FILE="docker-compose.test.yml"
ENV_FILE=".env.test"
HEALTH_PORT=9230
FRONTEND_PORT=9240
QDRANT_PORT=9220
HEALTH_TIMEOUT=90
HEALTH_INTERVAL=5

die() {
  echo "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: $0 {up|down|reset}

  up     Deploy: scp compose + env, pull images, up -d, health-check (default)
  down   Stop the stack on the host without removing volumes
  reset  Stop the stack and remove named volumes (clean slate for next deploy)

Required environment:
  TEST_HOST   SSH target (e.g. tc@test.example.local)
  IMAGE_TAG   Image tag to deploy (e.g. 1.2.0-rc.1)
EOF
}

ACTION="${1:-up}"
case "$ACTION" in
  up|down|reset) ;;
  -h|--help) usage; exit 0 ;;
  *) usage; exit 1 ;;
esac

# --- Common preflight (all actions need TEST_HOST and the compose file) -----

[ -n "${TEST_HOST:-}" ] || die "TEST_HOST is not set. Example: TEST_HOST=tc@test.example.local make deploy-test"
[ -f "$COMPOSE_FILE" ] || die "$COMPOSE_FILE not found at repo root."

# Strip user@ prefix from TEST_HOST to get the bare hostname for HTTP probes.
TEST_HOST_HOSTNAME="${TEST_HOST#*@}"
if [ "$TEST_HOST_HOSTNAME" = "$TEST_HOST" ]; then
  # No '@' was present; the whole value is the hostname.
  TEST_HOST_HOSTNAME="$TEST_HOST"
fi

# SSH reachability — same check for every action so we fail fast on a typo.
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$TEST_HOST" true 2>/dev/null; then
  die "Cannot SSH to '$TEST_HOST' non-interactively. Check that your key is loaded and the host is reachable (BatchMode=yes, ConnectTimeout=5)."
fi

# --- down / reset short-circuit --------------------------------------------

if [ "$ACTION" = "down" ] || [ "$ACTION" = "reset" ]; then
  EXTRA_FLAG=""
  if [ "$ACTION" = "reset" ]; then
    EXTRA_FLAG="-v"
    echo "Stopping stack and removing volumes on $TEST_HOST..."
  else
    echo "Stopping stack on $TEST_HOST (volumes preserved)..."
  fi

  # Use --env-file only if it exists on the remote; otherwise fall back to a
  # bare `down` which docker compose accepts even without env vars set.
  ssh "$TEST_HOST" "cd $REMOTE_DIR && \
    if [ -f $ENV_FILE ]; then \
      docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down $EXTRA_FLAG; \
    else \
      IMAGE_TAG=unused docker compose -f $COMPOSE_FILE down $EXTRA_FLAG; \
    fi" \
    || die "docker compose down failed on $TEST_HOST."

  echo "Done."
  exit 0
fi

# --- up: full preflight -----------------------------------------------------

[ -n "${IMAGE_TAG:-}" ] || die "IMAGE_TAG is not set. Example: IMAGE_TAG=1.2.0-rc.1 TEST_HOST=... make deploy-test"
[ -f "$ENV_FILE" ]      || die "$ENV_FILE not found at repo root. Copy .env.test.example to .env.test and fill it in."

# Required-fields check on .env.test. Treat lines starting with '#' as comments
# and require that named keys have a non-empty value.
require_env_var() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    die "$ENV_FILE is missing required key '$key'."
  fi
  local value="${line#${key}=}"
  # Strip surrounding quotes if any.
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  if [ -z "$value" ]; then
    die "$ENV_FILE has '$key' set to an empty value."
  fi
}

require_env_var IMAGE_TAG

# If LLM_PROVIDER=anthropic, ANTHROPIC_API_KEY must be populated. mock + others
# don't require a key.
LLM_PROVIDER_LINE="$(grep -E '^LLM_PROVIDER=' "$ENV_FILE" | tail -n 1 || true)"
LLM_PROVIDER_VAL="${LLM_PROVIDER_LINE#LLM_PROVIDER=}"
LLM_PROVIDER_VAL="${LLM_PROVIDER_VAL%\"}"; LLM_PROVIDER_VAL="${LLM_PROVIDER_VAL#\"}"
LLM_PROVIDER_VAL="${LLM_PROVIDER_VAL%\'}"; LLM_PROVIDER_VAL="${LLM_PROVIDER_VAL#\'}"

if [ "$LLM_PROVIDER_VAL" = "anthropic" ]; then
  require_env_var ANTHROPIC_API_KEY
fi

# Sanity-check that the IMAGE_TAG in .env.test matches the IMAGE_TAG env var,
# since docker-compose.test.yml interpolates `${IMAGE_TAG}` from --env-file.
ENV_FILE_TAG_LINE="$(grep -E '^IMAGE_TAG=' "$ENV_FILE" | tail -n 1 || true)"
ENV_FILE_TAG="${ENV_FILE_TAG_LINE#IMAGE_TAG=}"
ENV_FILE_TAG="${ENV_FILE_TAG%\"}"; ENV_FILE_TAG="${ENV_FILE_TAG#\"}"
ENV_FILE_TAG="${ENV_FILE_TAG%\'}"; ENV_FILE_TAG="${ENV_FILE_TAG#\'}"
if [ "$ENV_FILE_TAG" != "$IMAGE_TAG" ]; then
  echo "WARNING: IMAGE_TAG env var ('$IMAGE_TAG') differs from $ENV_FILE ('$ENV_FILE_TAG')."
  echo "         The compose stack will use the value from $ENV_FILE on the host."
fi

# --- Helpers ---------------------------------------------------------------

dump_logs() {
  echo
  echo "--- Last 50 log lines from the test host ---"
  ssh "$TEST_HOST" "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE logs --tail 50" \
    || echo "(failed to fetch logs)"
  echo "--- end logs ---"
}

fail_step() {
  local step="$1"; shift || true
  echo "ERROR: deploy-test failed at step: $step" >&2
  dump_logs
  exit 1
}

# --- Deploy ----------------------------------------------------------------

echo "Deploying $IMAGE_TAG to $TEST_HOST..."

# 1. Ensure remote workdir exists.
ssh "$TEST_HOST" "mkdir -p $REMOTE_DIR" \
  || fail_step "mkdir remote workdir"

# 2. Copy compose + env file.
echo "Copying $COMPOSE_FILE and $ENV_FILE to $TEST_HOST:$REMOTE_DIR ..."
scp "$COMPOSE_FILE" "$ENV_FILE" "$TEST_HOST:$REMOTE_DIR/" \
  || fail_step "scp compose+env"

# 3. Pull images.
echo "Pulling images on $TEST_HOST ..."
ssh "$TEST_HOST" "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE --env-file $ENV_FILE pull" \
  || fail_step "docker compose pull"

# 4. Up -d.
echo "Starting stack on $TEST_HOST ..."
ssh "$TEST_HOST" "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d" \
  || fail_step "docker compose up -d"

# --- Health check ----------------------------------------------------------

echo "Waiting for API health at http://${TEST_HOST_HOSTNAME}:${HEALTH_PORT}/health ..."

ELAPSED=0
HEALTHY=0
while [ "$ELAPSED" -lt "$HEALTH_TIMEOUT" ]; do
  if curl -fsS "http://${TEST_HOST_HOSTNAME}:${HEALTH_PORT}/health" >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  sleep "$HEALTH_INTERVAL"
  ELAPSED=$((ELAPSED + HEALTH_INTERVAL))
  echo "  ...still waiting (${ELAPSED}s / ${HEALTH_TIMEOUT}s)"
done

if [ "$HEALTHY" -ne 1 ]; then
  fail_step "API /health did not respond within ${HEALTH_TIMEOUT}s"
fi

# Verify each compose service is in an acceptable state. The ingest container
# exits cleanly after seeding (state 'exited', exit code 0) — that's expected
# and counts as healthy for ingest. All others must be running.
echo "Verifying container states ..."

PS_JSON="$(ssh "$TEST_HOST" "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE ps --format json" 2>/dev/null || true)"

if [ -z "$PS_JSON" ]; then
  fail_step "docker compose ps returned no output"
fi

# The compose ps output is one JSON object per line on modern docker compose.
# We do a forgiving check: for each expected service, find its line and
# verify state. We avoid jq to keep this dependency-free.
check_service_state() {
  local svc="$1"
  local accept_exited="$2"   # 1 if 'exited (0)' is acceptable, 0 otherwise
  local line
  line="$(printf '%s\n' "$PS_JSON" | grep -E "\"Service\"[[:space:]]*:[[:space:]]*\"${svc}\"" | head -n 1 || true)"
  if [ -z "$line" ]; then
    echo "  WARNING: service '$svc' not found in compose ps output."
    return 1
  fi
  # State field examples: "running", "exited", "restarting", "dead".
  local state
  state="$(printf '%s' "$line" | sed -n 's/.*"State"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  local exitcode
  exitcode="$(printf '%s' "$line" | sed -n 's/.*"ExitCode"[[:space:]]*:[[:space:]]*\([0-9-]*\).*/\1/p')"

  case "$state" in
    running)
      echo "  $svc: running"
      return 0
      ;;
    exited)
      if [ "$accept_exited" = "1" ] && [ "${exitcode:-1}" = "0" ]; then
        echo "  $svc: exited(0) — OK (one-shot)"
        return 0
      fi
      echo "  $svc: exited (code=${exitcode:-?}) — not OK"
      return 1
      ;;
    *)
      echo "  $svc: state=$state — not OK"
      return 1
      ;;
  esac
}

ALL_OK=1
check_service_state qdrant   0 || ALL_OK=0
check_service_state ingest   1 || ALL_OK=0
check_service_state api      0 || ALL_OK=0
check_service_state frontend 0 || ALL_OK=0

if [ "$ALL_OK" -ne 1 ]; then
  fail_step "one or more containers are not in an acceptable state"
fi

# --- Success ---------------------------------------------------------------

cat <<EOF

Test environment up at:
  Frontend:  http://${TEST_HOST_HOSTNAME}:${FRONTEND_PORT}
  API:       http://${TEST_HOST_HOSTNAME}:${HEALTH_PORT}
  Qdrant:    http://${TEST_HOST_HOSTNAME}:${QDRANT_PORT}
Deployed image tag: ${IMAGE_TAG}
EOF
