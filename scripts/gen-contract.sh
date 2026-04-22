#!/usr/bin/env bash
# Dump the running API's OpenAPI spec to contracts/openapi.yaml
# Usage: ./scripts/gen-contract.sh
#
# Requires: docker compose stack running, jq, python3, pyyaml
# Run: make contract   (defined in Makefile)

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
OUT="contracts/openapi.yaml"

if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq is required" >&2
  exit 1
fi

echo "Fetching OpenAPI JSON from $API_URL/openapi.json..."
JSON=$(curl -fsS "$API_URL/openapi.json")

echo "Converting to YAML..."
python3 -c "
import sys, json, yaml
data = json.loads(sys.stdin.read())
# Preserve a stable key order so diffs stay readable
print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
" <<< "$JSON" > "$OUT.generated"

# If no existing file, just move into place
if [ ! -f "$OUT" ]; then
  mv "$OUT.generated" "$OUT"
  echo "Created $OUT"
  exit 0
fi

# Show the diff; if identical, remove the generated file
if diff -q "$OUT" "$OUT.generated" >/dev/null 2>&1; then
  rm "$OUT.generated"
  echo "Contract unchanged."
else
  echo "Contract drift detected. Review:"
  echo "  diff $OUT $OUT.generated"
  echo ""
  echo "To accept: mv $OUT.generated $OUT"
  echo "To reject (hand-curated spec is authoritative): rm $OUT.generated"
  exit 1
fi
