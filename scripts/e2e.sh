#!/usr/bin/env bash
# End-to-end smoke test: fresh database, API, Celery worker + beat, the built frontend, then
# Playwright. Needs Postgres and Redis running locally (docker compose up -d postgres redis).
#
#   scripts/e2e.sh                                   the smoke test
#   E2E_DEMO_DATA=1 scripts/e2e.sh screenshots.spec.ts   six months of demo data + screenshots
set -euo pipefail
cd "$(dirname "$0")/.."

PG_ADMIN_URL=${PG_ADMIN_URL:-postgresql://khataiq:khataiq@localhost:5432/postgres}
DB=khataiq_e2e
export KHATAIQ_MIGRATION_DATABASE_URL="postgresql+psycopg://khataiq:khataiq@localhost:5432/$DB"
export KHATAIQ_DATABASE_URL="postgresql+psycopg://khataiq_app:khataiq_app@localhost:5432/$DB"
export KHATAIQ_APP_DB_PASSWORD=khataiq_app
export KHATAIQ_REDIS_URL=${KHATAIQ_REDIS_URL:-redis://localhost:6379/14}
export KHATAIQ_STORAGE_BACKEND=local
export KHATAIQ_LOCAL_STORAGE_DIR="$(mktemp -d)"
export KHATAIQ_COOKIE_SECURE=false   # plain http on localhost
export KHATAIQ_ENVIRONMENT=test
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"   # synthetic/ is not an installed package

psql "$PG_ADMIN_URL" -qc "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB"
alembic upgrade head
python scripts/seed_dev.py
if [ "${E2E_DEMO_DATA:-}" = "1" ]; then python ops/load/prepare.py; fi
python -c "import os, redis; redis.Redis.from_url(os.environ['KHATAIQ_REDIS_URL']).flushdb()"

for port in 8000 3000; do
  if curl -s -o /dev/null "http://localhost:$port"; then
    echo "port $port is already in use; stop whatever is running there first" >&2
    exit 1
  fi
done

# Each service runs in its own process group (setsid), so cleanup can stop it with every child
# it started: npm starts node, which renames itself 'next-server'.
pgids=()
cleanup() {
  for pgid in "${pgids[@]}"; do kill -- "-$pgid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT

setsid uvicorn khataiq.api.main:app --port 8000 --log-level warning & pgids+=($!)
setsid celery -A khataiq.pipeline.celery_app worker --pool=solo -Q pipeline -l warning & pgids+=($!)
setsid celery -A khataiq.pipeline.celery_app beat -l warning --schedule "$(mktemp -u)" & pgids+=($!)
(cd frontend && npm run build >/dev/null) || exit 1
(cd frontend && exec setsid npm run start) & pgids+=($!)

for url in http://localhost:8000/healthz http://localhost:3000/login; do
  for _ in $(seq 1 120); do curl -sf "$url" >/dev/null && break; sleep 1; done
done
(cd frontend && npx playwright test "$@")
