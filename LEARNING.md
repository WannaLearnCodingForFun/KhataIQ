# Learning log

One entry per session. Fill this in yourself, or have Claude Code draft it and you edit.

## YYYY-MM-DD — topic
- **Built:**
- **Concepts:**
- **Mistakes I made:**
- **Interview question I can now answer:**

## 2026-10-29 — core ledger: fingerprint, reconcile, self-transfer matching
_Drafted by Claude Code. Claude wrote all four functions, so this entry is about reading them;
edit it once you've worked through each one yourself._
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
