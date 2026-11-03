#!/usr/bin/env bash
# Load test against a local stack: fresh database with six months of data, the API on two
# uvicorn workers, one Celery worker, beat, then Locust headless.
#
#   ops/load/run.sh [users] [duration]      e.g. ops/load/run.sh 50 120s
set -euo pipefail
cd "$(dirname "$0")/../.."
USERS=${1:-50}
DURATION=${2:-120s}

PG_ADMIN_URL=${PG_ADMIN_URL:-postgresql://khataiq:khataiq@localhost:5432/postgres}
DB=khataiq_load
export KHATAIQ_MIGRATION_DATABASE_URL="postgresql+psycopg://khataiq:khataiq@localhost:5432/$DB"
export KHATAIQ_DATABASE_URL="postgresql+psycopg://khataiq_app:khataiq_app@localhost:5432/$DB"
export KHATAIQ_APP_DB_PASSWORD=khataiq_app
export KHATAIQ_REDIS_URL=${KHATAIQ_REDIS_URL:-redis://localhost:6379/13}
export KHATAIQ_STORAGE_BACKEND=local
export KHATAIQ_LOCAL_STORAGE_DIR="$(mktemp -d)"
export KHATAIQ_RATE_LIMIT_GENERAL_PER_MINUTE=1000000
export KHATAIQ_RATE_LIMIT_UPLOADS_PER_MINUTE=1000000
export KHATAIQ_LOG_LEVEL=WARNING
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"   # synthetic/ is not an installed package

psql "$PG_ADMIN_URL" -qc "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB"
alembic upgrade head >/dev/null
python scripts/seed_dev.py
python ops/load/prepare.py
python -c "import os, redis; redis.Redis.from_url(os.environ['KHATAIQ_REDIS_URL']).flushdb()"

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT
uvicorn khataiq.api.main:app --port 8000 --workers 2 --log-level warning & pids+=($!)
celery -A khataiq.pipeline.celery_app worker --concurrency 2 -Q pipeline -l warning & pids+=($!)
celery -A khataiq.pipeline.celery_app beat -l warning --schedule "$(mktemp -u)" & pids+=($!)
for _ in $(seq 1 60); do curl -sf http://localhost:8000/healthz >/dev/null && break; sleep 1; done

locust -f ops/load/locustfile.py --headless --host http://localhost:8000 \
  -u "$USERS" -r 10 --run-time "$DURATION" --csv ops/load/last-run --only-summary
