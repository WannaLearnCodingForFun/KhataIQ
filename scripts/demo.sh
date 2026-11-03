#!/usr/bin/env bash
# The whole stack on http://localhost:3000 with demo data, using only Docker:
#
#   scripts/demo.sh           build, start, seed (first run takes a few minutes)
#   scripts/demo.sh down -v   stop and delete the demo data
#
# Sign in as owner1@demo.khataiq.dev or officer1@demo.khataiq.dev, password khataiq-dev-password.
# Set LLM_API_KEY in your shell to enable the copilot.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -p khataiq-demo -f docker-compose.prod.yml -f docker-compose.demo.yml
         --env-file ops/demo/demo.env)
if [ "$#" -gt 0 ]; then exec "${compose[@]}" "$@"; fi

"${compose[@]}" up -d --build
"${compose[@]}" wait seed
echo "KhataIQ is running at http://localhost:3000 (sign in as officer1@demo.khataiq.dev / khataiq-dev-password)"
