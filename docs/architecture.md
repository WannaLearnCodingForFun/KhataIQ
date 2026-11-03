# KhataIQ architecture

KhataIQ turns a small business's bank and UPI statements into a cash-flow picture a loan officer can
check, where every number traces back to the transactions behind it. The backend is the core; ML and the
copilot are clients of the clean ledger and never write to it.

## 1. Priorities, in order
1. **Correctness** — integer paise; reconciliation as a hard gate; re-uploading never adds rows.
2. **Traceability** — every metric, flag and score links to source rows; every decision is audited.
3. **Reliability** — async pipeline, retries, dead-letter queue, idempotent stages.
4. **Security** — tenant isolation via RLS, role-based access, masked logs.
5. **ML as a client** — label model, forecast and risk benchmark read the ledger only.

**Out of scope:** OCR for scanned PDFs, live bank / Account Aggregator integration, real lending
decisions, payments, mobile app.

## 2. Components
```
Next.js web ──HTTPS/JWT──▶ FastAPI ──tool calls──▶ LLM provider (copilot)
                             │  │  │
                 store file  │  │  └─ enqueue job (via outbox relay) ──▶ Redis ──▶ Celery workers
                             ▼  ▼ SQL                                               │
                    MinIO (raw files)   PostgreSQL 16 ◀── ledger, evidence, audit ────┘
```
- **API (FastAPI):** auth, RBAC, REST `/v1`, uploads. Stores files and queues jobs; does no heavy work.
- **Workers (Celery):** one pipeline per upload: parse → normalize → reconcile → classify → evidence → metrics.
- **PostgreSQL 16:** system of record. RLS on every tenant table.
- **Redis:** Celery broker, rate-limit buckets, short-lived cache.
- **MinIO:** raw statement files, keyed `org/{org_id}/upload/{upload_id}/{sha256}`.
- **LLM provider:** used only by the copilot, only through typed read-only tools.

A modular monolith plus a worker pool is deliberate: right for this scale and easy to reason about.

## 3. Roles
| Role | Can do |
| --- | --- |
| owner | Manage own business and accounts, upload statements, see own metrics |
| officer | See all businesses in the org, review flags, create and move assessments, use the copilot |
| admin | Everything an officer can, plus users, dead-letter retries, audit log read |

## 4. Data model
Money columns are `BIGINT` paise. All tables have `created_at timestamptz default now()`.
`org_id` is denormalised onto every tenant table so RLS policies are a simple equality check.

| Table | Key columns | Constraints and notes |
| --- | --- | --- |
| organizations | id, name | One lender = one tenant |
| users | id, org_id, email, password_hash, role | `UNIQUE(email)`; role enum owner/officer/admin; argon2 hashes |
| businesses | id, org_id, owner_user_id, name, category | |
| accounts | id, org_id, business_id, bank, format, account_mask, type, upi_id | `UNIQUE(business_id, bank, account_mask)`; mask = last 4 digits only |
| uploads | id, org_id, account_id, storage_key, sha256, status, parser_version, period_start, period_end, opening_paise, closing_paise, recon_reason, recon_break_line, created_by | `UNIQUE(account_id, sha256)`; status enum received/parsing/parsed/reconciled/needs_review/processed/failed |
| idempotency_keys | key, org_id, user_id, request_hash, response_status, response_body, created_at | `PK(org_id, key)`; expires after 24 h |
| outbox | id, org_id, topic, payload, created_at, published_at | Written in the same transaction as the upload |
| pipeline_runs | id, org_id, upload_id, stage, status, attempts, error, started_at, finished_at | `UNIQUE(upload_id, stage, attempt_no)`; status queued/running/succeeded/failed/dead |
| transactions | id, org_id, account_id, upload_id, txn_date, amount_paise, direction, balance_after_paise, narration, narration_norm, channel, utr, counterparty_key, fingerprint, source_line | `UNIQUE(account_id, fingerprint)`; `CHECK(amount_paise > 0)`; indexes below |
| txn_labels | id, org_id, txn_id, label, method, model_version, confidence, created_by, created_at | Append-only; method rule/model/human; view `current_txn_labels` picks latest, human > rule > model |
| evidence_links | id, org_id, business_id, kind, txn_a, txn_b, level, rule_id, rule_version, details, run_id | kind self_transfer/reversal/duplicate; level verified/inferred/unresolved |
| flags | id, org_id, business_id, kind, status, summary, total_paise, rule_id, rule_version, resolved_by, resolved_at, resolution_note | kind cycle/unresolved_transfer/needs_review_upload; status open/confirmed/dismissed |
| flag_evidence | flag_id, txn_id | Many-to-many; a flag must have ≥ 1 row (enforced in the service + a deferred constraint trigger) |
| monthly_metrics | org_id, business_id, month, run_id, gross_inflow_paise, net_business_inflow_paise, uncertain_paise, outflow_paise, obligations_paise, closing_balance_paise, volatility_bp | `PK(business_id, month, run_id)`; volatility in basis points (int) |
| metric_runs | id, org_id, business_id, created_at, evidence_run_id | Latest run per business = current metrics |
| assessments | id, org_id, business_id, status, score, model_version, reasons, reviewer_id, decided_at, note | status draft/in_review/approved/rejected; transitions enforced in service and by trigger |
| audit_log | id, org_id, actor_id, action, entity_type, entity_id, before, after, at | INSERT only for the app role |

**Indexes:** `transactions(account_id, txn_date)`, `transactions(org_id, amount_paise, txn_date)`,
`transactions(utr) WHERE utr IS NOT NULL`, `flags(org_id, status) WHERE status = 'open'`,
`pipeline_runs(upload_id, stage)`.

**RLS:** every tenant table has `ENABLE ROW LEVEL SECURITY` and a policy
`org_id = current_setting('app.org_id')::bigint`. The API sets `SET LOCAL app.org_id` at the start of each
request transaction; workers set it per job. The migration role owns tables; the app connects as
`khataiq_app`, which is not the owner and does not have `BYPASSRLS`.

## 5. Ingestion pipeline
1. **Upload (API):** client sends `Idempotency-Key`. API hashes the file (SHA-256), streams it to MinIO,
   and in **one DB transaction** inserts `uploads` + an `outbox` row (topic `pipeline.start`). A duplicate
   `(account_id, sha256)` returns the existing upload with **200** (new = **201**). Same key + different
   body → **409**.
2. **Outbox relay:** a Celery beat task every 2 s publishes unpublished outbox rows
   (`SELECT … FOR UPDATE SKIP LOCKED`), then sets `published_at`. A crash never loses a job; a double
   publish is harmless because stages are idempotent.
3. **Parse:** `get_parser(bank, format)` → `ParsedStatement`. Parser errors → upload `failed` with line no.
4. **Normalize + persist:** each row → `transactions` with fingerprint; `INSERT … ON CONFLICT
   (account_id, fingerprint) DO NOTHING`.
5. **Reconcile (gate):** `core.ledger.reconcile` on this upload's rows in statement order. Fail → upload
   `needs_review`, store reason + break line, open a `needs_review_upload` flag, stop.
6. **Classify:** rule labels, then model labels for rows rules didn't cover.
7. **Evidence:** runs per **business** (all its accounts), not per upload: self-transfers, reversals,
   duplicates, cycles. Writes a new `run_id`; earlier runs stay for history.
8. **Metrics:** recompute monthly metrics for the business under a new `metric_runs` row.

Each stage records a `pipeline_runs` row. Retries: exponential backoff (2, 4, 8, 16, 32 s), max 5 attempts,
then status `dead` and the upload shows in the admin dead-letter list. Every status change → `audit_log`.

## 6. Evidence engine
Full rules in `docs/specs/evidence-engine.md`. Summary:
- **Levels:** verified (both legs proven) · inferred (one leg, named evidence) · unresolved (ambiguous → review).
- **Self-transfers:** `core.ledger.match_self_transfers` (UTR pass → uniqueness pass → unresolved).
- **Reversals, duplicates:** deterministic rules with fixed windows.
- **Cycles:** directed counterparty graph per 30-day window; Tarjan SCC, then simple cycles ≤ 4 hops
  inside each SCC. A cycle is a flag for review, never a fraud verdict.
- **Net business inflow** = credits − verified exclusions (self-transfers, reversals, loan
  disbursals) − uncertain credits. Inferred + unresolved credits are reported as `uncertain_paise`, shown
  as a band, never silently counted either way. Exact formula in the spec.

## 7. API
REST, `/v1`, JSON, cursor pagination (`?cursor=&limit=`, max 100). Errors use RFC 9457 problem+json.
Full list in `docs/specs/api.md`.

**Auth:** `POST /v1/auth/login` returns a 15-minute access JWT (HS256, `sub`, `org_id`, `role`, `exp`) and
sets a rotating 7-day refresh token in an httpOnly, Secure, SameSite=Strict cookie. Refresh tokens are
stored hashed; reuse of a rotated token revokes the whole family. Rate limits: Redis token bucket per user
(60 req/min general, 10 uploads/min, 20 copilot calls/hour).

## 8. ML (supporting, never authoritative)
Details in `docs/specs/ml.md`.
- **Label model:** TF-IDF + logistic regression baseline; a small transformer only if it beats the
  baseline on the held-out synthetic set. Only labels rows that rules didn't.
- **Forecast:** 3-month cash-flow forecast with rolling-origin evaluation vs seasonal-naive baseline.
  Lives in `experiments/`; the app shows it only with its error band.
- **Risk benchmark:** public credit-risk dataset (Home Credit Default Risk) in `experiments/`, clearly
  labelled as a benchmark on a different population, **not** a score for KhataIQ businesses. Assessments
  in the app are human decisions; the app shows cash-flow evidence, not a model's approval.

## 9. Copilot
Details in `docs/specs/copilot.md`. The LLM sees only typed, read-only, org-scoped tools. Every answer
must cite transaction IDs or metric rows returned by those tools in this conversation; the server rejects
answers with uncited figures or citations it didn't return, and retries once, then returns a refusal.

## 10. Observability and operations
- Structured JSON logs (`structlog`) with `request_id` propagated API → outbox payload → worker.
- OpenTelemetry traces for API requests and each pipeline stage.
- Prometheus metrics at `/metrics`: request latency, queue depth, stage duration, stage failures, DLQ size.
- `/healthz` = process alive (no dependencies). `/readyz` = DB + Redis reachable.
- Deploy: Docker images for api, worker, beat, frontend; `docker-compose.prod.yml`; GitHub Actions CI/CD.

## 11. Security checklist
argon2 password hashing · JWT secret from env · RLS + app-level checks · upload size limit 10 MB and
content-type sniffing · CSV/PDF only · masked logs · CORS limited to the frontend origin · dependency
audit (`pip-audit`) in CI · no PII in error responses.
