# 3-minute demo

Setup before you start: run `scripts/demo.sh` and wait for "KhataIQ is running". Open two browser
windows, one normal and one private, so you can be the officer and an owner at once. For step 5, make a
copy of `frontend/e2e/fixtures/october.csv` and change one number in the `Balance` column. Every user's
password is `khataiq-dev-password`.

## 0:00 — The problem (20 s)

> "A lender's officer gets six months of a kirana store's bank statements and has to answer one
> question: how much real business income goes through this account? Statements overstate it. The
> owner moves money between their own accounts, payments bounce and come back, statements overlap, and
> some money just goes round in a circle. KhataIQ separates real income from the rest, and every
> number links to the rows behind it."

## 0:20 — Overview (40 s)

*Officer window: sign in as `officer1@demo.khataiq.dev` → Businesses → **Sharma Kirana Store**.*

- Point at the chart: gross inflow vs **net business inflow**, and the shaded **uncertain** band.
  > "Gross is what the bank shows. Net is after removing self-transfers, reversals, duplicates and
  > loans that the rules could *prove*. Uncertain is money the rules couldn't decide. We don't guess,
  > we show it as a range."
- Point at the table: monthly figures, closing balance.

## 1:00 — Evidence, not opinions (40 s)

*Click **Transactions**. Set **Evidence** to `verified`, then to `unresolved`.*

> "Each row carries what the evidence engine concluded about it: *verified self transfer* means rule
> `SELF_TRANSFER` matched this credit to a debit from the owner's other account, by UTR, or by exact
> amount within 2 days. *Unresolved* means more than one match was possible, so a human decides. Rules are
> deterministic and versioned. The label column is the ML model's suggestion, and changing it here is
> a human relabel, which always wins."

*Click **Evidence**.*

> "This is where the money goes, top 20 counterparties. A cycle shows up as money that leaves and comes
> back through the same parties."

## 1:40 — Review queue (30 s)

*Click **Review queue** in the header → open an open flag.*

> "Whatever the rules can't prove ends up here: an ambiguous transfer, a possible duplicate, a round
> trip. The officer confirms or dismisses it with a note, and that decision goes into an append-only
> audit log."

*Type a note → **Dismiss** (or **Confirm**).*

## 2:10 — The hard gate (30 s)

*Private window: sign in as `owner2@demo.khataiq.dev` → **Mehta Medicals** → **Upload statement**.*

- Upload the edited copy of `october.csv`.
  > "This statement doesn't add up. One balance is off. KhataIQ stops right there and shows the exact
  > line, with the expected and actual balances. Nothing after reconciliation runs on a statement that
  > doesn't reconcile."
- Upload the original `october.csv`. The stages tick through to **processed** in a couple of seconds.
  > "The upload is stored, queued through a transactional outbox, and processed by Celery workers.
  > Each stage is idempotent, so uploading the same file again adds nothing."

## 2:40 — Close (20 s)

*Officer window: **Mehta Medicals** now has October and a flag about RAVI TRADERS in the queue.
Optionally open **Assessment** and start one.*

> "Integer paise everywhere, Postgres row-level security per lender, every decision audited. And the
> copilot can answer questions, but the server rejects any ₹ figure that doesn't come from the rows it
> cites."

If an API key is set (`LLM_API_KEY`), ask the copilot on the overview: *"What was net business inflow
in August, and which transactions were excluded?"*

## Likely follow-up questions

- *Is this accurate on real statements?* Unknown. The evaluation uses synthetic data with planted ground
  truth (`docs/results/evidence_eval.md`), and that page says so.
- *Does it score borrowers?* No. It produces evidence and cash flow. The assessment is a human decision.
- *What happens if a worker dies mid-stage?* The job is redelivered, the stage takes over the stuck
  attempt, and because stages are idempotent the result is the same.
