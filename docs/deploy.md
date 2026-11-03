# Deploying KhataIQ

The production layout is one host running `docker-compose.prod.yml`: PostgreSQL 16, Redis, MinIO,
a one-off `migrate` job, the API, a Celery worker, Celery beat and the web frontend. Prometheus and
Grafana are available under the `monitoring` profile.

## 1. Configure

```bash
cp .env.prod.example .env.prod
```

Fill in every value; generate each secret separately with `openssl rand -hex 32`. Compose refuses to
start if a required secret is missing. `.env.prod` is git-ignored — keep it out of the repository and
out of images.

| Variable | Used for |
| --- | --- |
| `POSTGRES_PASSWORD` | The owner role (`khataiq`): runs migrations only |
| `APP_DB_PASSWORD` | `khataiq_app`, the role the API and workers use; set by `migrate` on every deploy |
| `JWT_SECRET` | Signing access tokens; the app refuses to start in `prod` with the dev default |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | Statement storage |
| `PUBLIC_URL` | The browser-facing origin (CORS allow-list) |
| `LLM_API_KEY` | Optional: enables the copilot (otherwise it answers 503) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional: where traces go |

## 2. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

`migrate` runs `alembic upgrade head` and exits; the API, worker and beat start only after it
succeeds. Create the first organization and admin with a one-off command (there is no public sign-up):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api python scripts/seed_dev.py
```

That script creates a *demo* org with a known password — for a real deployment, write the first admin
directly and change the password immediately.

## 3. Put TLS in front

Run the stack behind a reverse proxy (Caddy, nginx, a cloud load balancer) that terminates TLS and
forwards to `web:3000`. The refresh cookie is `Secure`, so the app only works over HTTPS (or plain
`localhost` in development, with `KHATAIQ_COOKIE_SECURE=false`). The web server proxies `/v1/*` to the
API, so the API itself never needs a public port. Also set at the proxy:

- a request-body limit of ~11 MB (uploads are capped at 10 MB by the app too);
- `X-Forwarded-For` / `X-Forwarded-Proto` (the API runs uvicorn with `--proxy-headers`).

## 4. Operate

- **Health:** `/healthz` (process alive, no dependencies) for liveness; `/readyz` (database + Redis)
  for readiness. Don't restart containers on `/readyz` failures — a database blip would restart every
  healthy API process at once.
- **Metrics:** `/metrics` on the API and port 9100 on the worker, scraped by
  `ops/prometheus/prometheus.yml`. Keep both on the internal network only; don't proxy `/metrics`
  publicly. Dashboard: import `ops/grafana/khataiq.json`.
  `docker compose -f docker-compose.prod.yml --profile monitoring up -d` starts Prometheus and Grafana.
- **Logs:** JSON on stdout with `request_id` (and `trace_id` when tracing is on); account numbers are
  masked to the last 4 digits and narrations, tokens and passwords are redacted before rendering.
- **Dead letters:** stages that failed 5 times show in Admin → Dead letters, where they can be retried.
- **Backups:** `pg_dump` the database nightly and enable MinIO bucket versioning (or replicate to S3).
  Add a lifecycle rule that deletes objects older than a day with no `uploads` row — the harmless
  orphans an interrupted upload can leave (`khataiq/services/uploads.py`).

## 5. Upgrade

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Migrations run first, in one transaction each. Never edit a migration that has reached `main`; add a
new one. To roll back code, deploy the previous image tag (`KHATAIQ_VERSION`); roll back the schema
only with a tested `alembic downgrade`, because downgrades can drop data.

## What's not covered

- Multi-host or Kubernetes deployment, managed Postgres failover, Redis persistence tuning.
- Secrets in a secret manager instead of an env file.
- Image signing and pushing to a registry (CI builds the images but doesn't publish them).
