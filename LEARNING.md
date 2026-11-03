# Learning log

One entry per session.

## YYYY-MM-DD — topic
- **Built:**
- **Concepts:**
- **Mistakes I made:**
- **Interview question I can now answer:**

## 2026-10-29 — core ledger: fingerprint, reconcile, self-transfer matching
- **Built:** `normalize_narration`, `fingerprint`, `reconcile`, `match_self_transfers` in
  `khataiq/core/ledger.py`; Hypothesis property tests in `tests/test_ledger_properties.py`; CI.
- **Concepts:**
  - Canonicalize-then-hash for dedup. The normalization rules become part of the stored data
    format, so changing them changes every stored fingerprint.
  - Field separators in hash input (`1|23` vs `12|3`); encoding text to bytes before hashing.
  - Running-balance reconciliation: one accumulator, fail fast on the first break.
  - Bipartite candidate graph: group by amount (hash map), then sort + `bisect` for the date window
    → O(n log n + k) instead of O(n²).
  - Degree counting (`Counter`) to find pairs where each side has exactly one option.
  - Property-based testing: invariants (idempotence, disjointness, order-independence) instead of
    hand-picked examples; Hypothesis shrinks failures to minimal inputs.
- **Mistakes I made:** _(fill in after re-implementing a function from memory without looking)_
- **Interview question I can now answer:** "Two systems both record a transfer, with no shared
  key. How do you match them safely, and what do you do when the match is ambiguous?"

## 2026-11-03 — dev environment + parser spec
- **Built (boilerplate):** docker-compose (Postgres 16, Redis, MinIO), settings via
  pydantic-settings, SQLAlchemy engine/session, FastAPI `/healthz`, Alembic wired to settings.
- **Next:** `khataiq/pipeline/normalize.py`, `parsers/__init__.py`, `parsers/demo_csv.py`.
  Spec: `tests/test_normalize.py`, `tests/test_parsers.py`, golden file in `tests/fixtures/`.
- **Concepts to look for while implementing:** why float can't hold 0.29 exactly; Decimal accepting
  'NaN' and '1e3'; strict date formats vs guessing; regex lookarounds `(?<!\d)`; the csv module
  vs `split(',')`; UTF-8 BOM; exception chaining (`raise ... from exc`); golden-file testing.
- **Mistakes I made:** _(fill in as you go)_
- **Interview question I can now answer:** "How do you parse money from user-supplied text
  without losing precision, and how do you test a parser so a refactor can't silently change it?"
