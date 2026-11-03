# Synthetic data spec

Real Indian small-business statements aren't available, so the pipeline is evaluated on generated data
with known ground truth. This proves the **pipeline** works; it does not prove real-world lending accuracy.
Every results doc must say so.

## Generator (`synthetic/generator.py`)
`generate(seed: int, config: GenConfig) -> GeneratedBusiness` — same seed, same output, byte for byte.

**GenConfig defaults:** 1–3 accounts per business · 6 months · business type one of
`kirana, pharmacy, salon, hardware, tiffin` · daily sales via UPI with weekly seasonality (weekend +20%)
and a festival bump (Oct–Nov +35%) · monthly rent, EMI, salary, supplier payments · noise:
cash deposits, small personal spends.

**Planted events (each recorded in ground truth):**
| Event | Rate | Notes |
| --- | --- | --- |
| self-transfer between own accounts | 4 per month | 70% with matching UTR, 30% without; 10% posted next day |
| ambiguous self-transfer | 1 per 2 months | two same-amount credits in the window |
| reversal | 2 per month | narration from the reversal keyword list |
| overlapping upload | 1 per business | second statement overlaps 10–20 days |
| near-duplicate row | 1 per 3 months | same date/amount/narration, different balance |
| circular flow | 1 per 3 businesses | 3–4 hops through counterparties, returns within 30 days, ±5% |
| loan disbursal | 1 per business | narration contains `LOAN DISB` |

Narrations follow realistic patterns: `UPI/<name>/<vpa>/<12-digit UTR>`, `NEFT/<IFSC-like>/<name>`,
`IMPS/P2A/<ref>`, `ATM WDL`, `CASH DEP`, `ACH D- <lender> EMI`.

**Output:** for each account a CSV in the `demo_bank` format (and optionally `hdfc_like` / `sbi_like`),
plus `ground_truth.json`: `{self_transfers:[[debit_ref, credit_ref, level]], reversals:[...],
duplicates:[...], cycles:[[refs...]], labels:{ref: label}}`. A `ref` is `account_index:line_no`.

## Evaluation (`synthetic/evaluate.py`)
- Generate N businesses (default 200, CI uses 20), run the full pipeline (in-process, no Celery),
  map DB rows back to refs via `source_line`, and compute per rule: precision, recall, and count of
  unresolved (unresolved is neither a hit nor a false positive; report it separately).
- Label model: macro-F1 on a held-out 20% of businesses (split by business, never by row).
- Write `docs/results/evidence_eval.md` with the config, seed, a table per rule, and the limitations note.
