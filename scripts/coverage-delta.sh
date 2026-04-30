#!/usr/bin/env bash
# Compare current backend + frontend coverage to baselines in docs/test-strategy.md.
# Threshold: warn at -2%, block at -5%.
#
# Usage:
#   scripts/coverage-delta.sh           # run both, print delta table, exit 0/1/2
#   scripts/coverage-delta.sh --json    # machine-readable output for the tester agent
#
# Exit codes:
#   0  both deltas >= -2.0% (OK)
#   1  either delta < -2.0% (WARN — recommend filing coverage-drop issue)
#   2  either delta < -5.0% (BLOCK — recommend not promoting rc)
#
# Dependencies: bash, awk, grep, sed, python3 (for JSON parse), docker compose, npm.

set -euo pipefail

# ─── Locate repo root ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STRATEGY_DOC="${REPO_ROOT}/docs/test-strategy.md"

# ─── Parse args ──────────────────────────────────────────────────────────────
JSON_OUTPUT=false
if [[ "${1:-}" == "--json" ]]; then
    JSON_OUTPUT=true
fi

log() {
    # Only emit human-readable progress when not in JSON mode
    if [[ "${JSON_OUTPUT}" == "false" ]]; then
        echo "$@" >&2
    fi
}

fail() {
    echo "ERROR: $*" >&2
    exit 3
}

# ─── 1. Read baselines from docs/test-strategy.md ────────────────────────────
if [[ ! -f "${STRATEGY_DOC}" ]]; then
    fail "Strategy doc not found: ${STRATEGY_DOC}"
fi

# Extract numeric value (allows decimals) after the labels.
backend_baseline=$(grep -oE 'Backend baseline:[[:space:]]*[0-9]+(\.[0-9]+)?' "${STRATEGY_DOC}" \
    | head -1 | grep -oE '[0-9]+(\.[0-9]+)?' | head -1 || true)
frontend_baseline=$(grep -oE 'Frontend baseline:[[:space:]]*[0-9]+(\.[0-9]+)?' "${STRATEGY_DOC}" \
    | head -1 | grep -oE '[0-9]+(\.[0-9]+)?' | head -1 || true)

if [[ -z "${backend_baseline}" ]]; then
    fail "Backend baseline not found in ${STRATEGY_DOC}. Expected line: 'Backend baseline: NN%'"
fi
if [[ -z "${frontend_baseline}" ]]; then
    fail "Frontend baseline not found in ${STRATEGY_DOC}. Expected line: 'Frontend baseline: NN.NN%'"
fi

log "Baselines: backend=${backend_baseline}%, frontend=${frontend_baseline}%"

# ─── 2. Run backend coverage ─────────────────────────────────────────────────
log "Running backend coverage (pytest --cov inside api container)..."

# Make sure the api container is up; otherwise we cannot compute backend coverage.
# Use plain `docker compose ps` and look for the api service in running state — works on
# both newer compose (with --status flag) and older releases.
if ! docker compose ps api 2>/dev/null | grep -qE '(running|Up)'; then
    fail "api container is not running. Start the dev stack with 'make up' first."
fi

docker compose exec -T api python -m pytest /app/tests/ \
    --cov=api --cov=ingest --cov=shared \
    --cov-report=xml -q >/dev/null 2>&1 || {
    fail "backend pytest run failed; cannot compute coverage"
}

# Pull the coverage XML out of the container (it lives at /app/coverage.xml).
backend_xml="$(mktemp -t coverage-backend.XXXXXX.xml)"
trap 'rm -f "${backend_xml}"' EXIT
docker compose exec -T api cat /app/coverage.xml > "${backend_xml}"

# Extract line-rate (e.g. 0.5734) from the root <coverage line-rate="..."> attr.
line_rate=$(grep -oE 'line-rate="[0-9]+(\.[0-9]+)?"' "${backend_xml}" \
    | head -1 | grep -oE '[0-9]+(\.[0-9]+)?')
if [[ -z "${line_rate}" ]]; then
    fail "could not parse line-rate from backend coverage.xml"
fi
backend_current=$(awk -v r="${line_rate}" 'BEGIN { printf "%.2f", r * 100 }')
log "Backend current: ${backend_current}%"

# ─── 3. Run frontend coverage ────────────────────────────────────────────────
log "Running frontend coverage (vitest with v8 + json-summary reporter)..."

(
    cd "${REPO_ROOT}/frontend"
    # --silent suppresses npm's own banner; vitest still emits its summary.
    # We don't fail-fast here because vitest exits non-zero on test failures,
    # but we still want to read whatever coverage-summary.json was written.
    npm run coverage --silent >/dev/null 2>&1 || true
)

summary_json="${REPO_ROOT}/frontend/coverage/coverage-summary.json"
if [[ ! -f "${summary_json}" ]]; then
    fail "frontend coverage summary not found at ${summary_json}. \
Check that vitest.config.ts includes 'json-summary' in coverage.reporter."
fi

# .total.lines.pct is the canonical "lines covered %" — same metric the
# strategy doc baselines use.
frontend_current=$(python3 -c "
import json, sys
with open('${summary_json}') as f:
    data = json.load(f)
pct = data['total']['lines']['pct']
print(f'{float(pct):.2f}')
")
log "Frontend current: ${frontend_current}%"

# ─── 4. Compute deltas + statuses ────────────────────────────────────────────
compute_status() {
    # $1 = delta as decimal string (e.g. "-3.45")
    awk -v d="$1" 'BEGIN {
        if (d < -5.0) print "block";
        else if (d < -2.0) print "warn";
        else print "ok";
    }'
}

backend_delta=$(awk -v c="${backend_current}" -v b="${backend_baseline}" \
    'BEGIN { printf "%.2f", c - b }')
frontend_delta=$(awk -v c="${frontend_current}" -v b="${frontend_baseline}" \
    'BEGIN { printf "%.2f", c - b }')

backend_status=$(compute_status "${backend_delta}")
frontend_status=$(compute_status "${frontend_delta}")

# Verdict precedence: block > warn > ok
verdict="ok"
for s in "${backend_status}" "${frontend_status}"; do
    case "$s" in
        block) verdict="block" ;;
        warn)  [[ "${verdict}" == "ok" ]] && verdict="warn" ;;
    esac
done

# ─── 5. Output ───────────────────────────────────────────────────────────────
fmt_signed() {
    # Add a leading + sign for non-negative numbers; awk already gives the - sign.
    awk -v n="$1" 'BEGIN {
        if (n+0 >= 0) printf "+%.2f", n;
        else printf "%.2f", n;
    }'
}

upper_status() {
    case "$1" in
        ok)    echo "OK" ;;
        warn)  echo "WARN" ;;
        block) echo "BLOCK" ;;
    esac
}

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    cat <<EOF
{
  "backend": {"baseline": ${backend_baseline}, "current": ${backend_current}, "delta": ${backend_delta}, "status": "${backend_status}"},
  "frontend": {"baseline": ${frontend_baseline}, "current": ${frontend_current}, "delta": ${frontend_delta}, "status": "${frontend_status}"},
  "verdict": "${verdict}"
}
EOF
else
    backend_delta_disp=$(fmt_signed "${backend_delta}")
    frontend_delta_disp=$(fmt_signed "${frontend_delta}")

    cat <<EOF

Coverage delta vs baselines in docs/test-strategy.md:

Area      | Baseline | Current | Delta   | Status
----------|----------|---------|---------|-------
Backend   |  ${backend_baseline}%   |  ${backend_current}%  | ${backend_delta_disp}%  | $(upper_status "${backend_status}")
Frontend  |  ${frontend_baseline}%  |  ${frontend_current}%  | ${frontend_delta_disp}%  | $(upper_status "${frontend_status}")

Verdict: $(upper_status "${verdict}")
EOF
fi

# ─── 6. Exit code ────────────────────────────────────────────────────────────
case "${verdict}" in
    ok)    exit 0 ;;
    warn)  exit 1 ;;
    block) exit 2 ;;
esac
