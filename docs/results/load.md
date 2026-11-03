# Load test

Run with `ops/load/run.sh 50 120s` (Locust, `ops/load/locustfile.py`) on 2026-11-03.

## Scenario

- **50 concurrent users for 120 s**, ramped at 10/s: 40 officers (overview + metrics, transaction pages,
  review queue + a flag, the money-flow graph; 0.5–2 s think time) and 10 owners (each uploads a
  freshly generated one-week statement every 5–15 s and polls its status every 2 s, like the UI).
- Data: the seeded dev org plus six months of synthetic history (≈ 1,100 transactions, 2 accounts)
  for the business the officers read.
- **Rate limits were raised for this run** so it measures the application, not the limiter. With the
  production limits (60 req/min per user) these users would be throttled long before the server is.

## Hardware and setup

One VM: 4 vCPU (Intel Xeon @ 2.80 GHz), 15 GB RAM. PostgreSQL 16, Redis 7, the API on 2 uvicorn
workers, one Celery worker (concurrency 2) and beat, Locust — **all on the same machine**, so the load
generator competes with the system under test for CPU.

## Target

p95 under **300 ms** for every read endpoint officers use; zero errors; uploads processed within a few
seconds while the read load runs.

## Measured

| Endpoint | Requests | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| `GET /v1/businesses/{id}` | 1,460 | 15 ms | 73 ms | 250 ms |
| `GET /v1/businesses/{id}/metrics` | 1,459 | 18 ms | 72 ms | 280 ms |
| `GET /v1/businesses/{id}/transactions` (100 rows) | 1,081 | 46 ms | 170 ms | 350 ms |
| `GET /v1/businesses/{id}/graph` | 332 | 65 ms | **290 ms** | 790 ms |
| `GET /v1/flags` | 698 | 13 ms | 67 ms | 280 ms |
| `GET /v1/flags/{id}` | 698 | 14 ms | 67 ms | 320 ms |
| `GET /v1/uploads/{id}` | 224 | 17 ms | 160 ms | 490 ms |
| `POST /v1/accounts/{id}/uploads` | 100 | 41 ms | 450 ms | 700 ms |
| `POST /v1/auth/login` | 50 | 1,000 ms | 1,500 ms | 1,500 ms |
| **All requests** | **6,102** | **19 ms** | **130 ms** | **790 ms** |

- **Throughput:** 50.8 requests/s, **0 failures**.
- **Pipeline:** 100 statements uploaded during the run; 97 finished all seven stages, the other 3 were
  still queued when the run stopped. Upload-to-processed time: **p50 1.6 s, p95 2.6 s**.

## Reading the result

- Every officer read endpoint met the 300 ms p95 target; the graph endpoint only just (290 ms), because
  it loads the whole ledger and rebuilds the graph and its cycles on every request. Caching it per
  evidence run is the obvious next step.
- p99 is 3–5× p95 on most endpoints: with Locust, Postgres, two API workers and the pipeline worker
  sharing 4 vCPUs, tail latency is mostly CPU contention. A run with the load generator on another
  machine would tell the two apart.
- Login p95 is 1.5 s. That is argon2 doing its job (deliberately slow hashing, ~64 MB per hash) and 50
  users logging in within 5 s on 4 cores; it isn't on any page's hot path.
