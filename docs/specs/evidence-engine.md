# Evidence engine spec

The evidence engine decides which money is real business income. It is deterministic: the same ledger
gives the same evidence every time. Each rule has a `rule_id` and an integer `rule_version`, stored on
every `evidence_links` and `flags` row. Changing a rule's behaviour means bumping its version.

It runs per **business**, over all accounts of that business, after every successful reconcile. Each run
gets a new `run_id`. Earlier runs stay for history; the latest run is current.

## Evidence levels
| Level | Meaning |
| --- | --- |
| verified | Both legs of the event are in the ledger and the rule's conditions are fully met |
| inferred | Only one leg is in the ledger, but named evidence in the row supports the rule |
| unresolved | More than one explanation fits, or the evidence conflicts; goes to the review queue |

## Rules

### SELF_TRANSFER v1
Uses `khataiq.core.ledger.match_self_transfers` (window 2 days) over the business's transactions.
- verified / unresolved: exactly as `match_self_transfers` returns.
- **inferred** (added in the service, after matching): a transaction not in any match whose
  `narration_norm` contains the last 4 digits of another of the business's account masks, or the owner's
  registered UPI ID (`accounts.upi_id`, nullable). Stored with `txn_b = NULL`.

### REVERSAL v1
A credit `c` reverses a debit `d` when: same account; `c.amount_paise == d.amount_paise`;
`0 <= (c.date − d.date).days <= 7`; same `counterparty_key` (or both null); and `c.narration_norm`
contains one of `REV`, `REVERSAL`, `RETURN`, `REFUND`, `RTN`, `FAILED`.
- One candidate debit → verified. Several → unresolved (link to each). Keyword but no matching debit →
  inferred with `txn_b = NULL`.

### DUPLICATE v1
Two rows in **different uploads of the same account** with equal `(txn_date, amount_paise, direction,
narration_norm)` but different fingerprints (because balances differ) → unresolved duplicate link.
(Exact-fingerprint duplicates never reach the table thanks to the unique constraint.)

### LOAN_DISBURSAL v1
Credit whose `narration_norm` contains `LOAN`, `DISB`, or `NBFC` and whose label is `loan_in` → excluded
from business inflow at level inferred.

### CYCLE v1
1. Build a directed graph for each 30-day window (windows start on the 1st and 16th of each month,
   overlapping). Nodes = the business (`SELF`) and each `counterparty_key`. Edges: debit → `SELF → cp`,
   credit → `cp → SELF`, weighted by total paise.
2. Add edges between counterparties only when both legs are known (multi-account self-transfers make
   accounts nodes: `ACCT:<id>`).
3. Find strongly connected components with **iterative Tarjan**.
4. In each SCC with ≥ 2 nodes, enumerate simple cycles through `SELF` of length ≤ 4 (bounded DFS
   from `SELF`, nodes ordered by id to avoid duplicates), max 50 per SCC.
5. A cycle is flagged when money out and back are within 10% of each other **and** the total is ≥
   ₹10,000 (1,000,000 paise). Flag summary: path, total, dates. Evidence rows = every txn on the path.

## Dedupe
A flag's identity = `(rule_id, rule_version, sorted txn ids)`. If an open or dismissed flag with that
identity exists, don't create a new one. Dismissed stays dismissed.

## Net business inflow (per month)
```
gross_inflow      = Σ credits
excluded_verified = Σ credits in verified SELF_TRANSFER, verified REVERSAL, LOAN_DISBURSAL links
uncertain         = Σ credits in inferred or unresolved links (counted once even if in several)
net_business_inflow = gross_inflow − excluded_verified − uncertain
```
The UI shows `net_business_inflow` with `uncertain` as a band above it, never silently added or removed.

## Tests required
- Unit: each rule on hand-built ledgers, including edge windows (day 0, day 2, day 3).
- Property: no transaction counted in excluded_verified twice; `net ≤ gross`; re-run is identical.
- Evaluation on synthetic ground truth (see `synthetic-data.md`).
