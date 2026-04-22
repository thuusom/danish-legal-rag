#!/usr/bin/env bash
# Generate TypeScript types from contracts/openapi.yaml for the frontend.
# Usage: ./scripts/gen-api-client.sh
# Requires: Node.js, run from repo root. Installs openapi-typescript locally
# into frontend/ the first time.
#
# Output: frontend/src/lib/api/schema.d.ts

set -euo pipefail

if [ ! -d frontend ]; then
  echo "error: frontend/ directory missing. Run this from the repo root after frontend scaffold exists." >&2
  exit 1
fi

cd frontend

if [ ! -f package.json ]; then
  echo "error: frontend/package.json missing. Scaffold the SvelteKit app first." >&2
  exit 1
fi

# Ensure openapi-typescript is installed locally
if ! npx --no-install openapi-typescript --version >/dev/null 2>&1; then
  echo "Installing openapi-typescript..."
  npm install --save-dev openapi-typescript
fi

mkdir -p src/lib/api

npx openapi-typescript ../contracts/openapi.yaml -o src/lib/api/schema.d.ts

echo "Generated frontend/src/lib/api/schema.d.ts from contracts/openapi.yaml"
echo "Import types like:"
echo "  import type { components } from '\$lib/api/schema';"
echo "  type AskResponse = components['schemas']['AskResponse'];"
