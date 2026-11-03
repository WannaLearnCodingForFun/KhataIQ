"""Run the full pipeline on generated businesses and score each evidence rule.

    KHATAIQ_STORAGE_BACKEND=local python -m synthetic.evaluate --n 200 --seed 1000 \\
        --out docs/results/evidence_eval.md

Every business is loaded into its own org (through the migration role), its statements are
uploaded in order and processed in-process (InlineDispatcher, no Celery), and the current
evidence run is mapped back to ground-truth references through upload ids and source lines.

Scoring, per rule:
  precision  correct verified predictions / all verified predictions
  recall     true events found as verified / all true events expected to be verified
  unresolved and inferred predictions are neither hits nor false positives; they are counted
  separately, because sending a case to a human is the designed outcome for ambiguity.
DUPLICATE links are always unresolved by design, so for that rule detection (any link) is
scored. CYCLE: a flag is a hit when its evidence contains every row of a planted cycle.
"""

from __future__ import annotations

import argparse
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import khataiq.pipeline.stages  # noqa: F401  (registers the stages)
from khataiq.config import get_settings
from khataiq.db import tenant_session
from khataiq.models import (
    Account,
    Business,
    Flag,
    FlagEvidence,
    Organization,
    Transaction,
    User,
)
from khataiq.models.enums import EvidenceKind, EvidenceLevel, FlagKind, FlagStatus, UserRole
from khataiq.pipeline.outbox import pipeline_publisher, relay_once
from khataiq.pipeline.runner import PIPELINE, InlineDispatcher
from khataiq.principal import Principal
from khataiq.services.evidence import current_links
from khataiq.services.uploads import create_upload
from synthetic.generator import GenConfig, GeneratedBusiness, generate


@dataclass
class RuleScore:
    rule: str
    truth: int = 0
    predicted: int = 0
    correct: int = 0
    found: int = 0
    unresolved: int = 0
    inferred: int = 0
    note: str = ""

    @property
    def precision(self) -> float | None:
        return self.correct / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.found / self.truth if self.truth else None


@dataclass
class Report:
    n: int
    seed: int
    config: GenConfig
    seconds: float = 0.0
    transactions: int = 0
    scores: dict[str, RuleScore] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)

    def score(self, rule: str) -> RuleScore:
        return self.scores.setdefault(rule, RuleScore(rule))


# Hooks later milestones use to add their own measurements (e.g. label macro-F1).
BusinessHook = Callable[[Session, GeneratedBusiness, dict[int, str], Report, int], None]
HOOKS: list[BusinessHook] = []
FINALIZERS: list[Callable[[Report], None]] = []


def load_business(owner_session: Session, biz: GeneratedBusiness) -> tuple[Principal, int,
                                                                           list[int]]:
    org = Organization(name=f"synthetic-{biz.seed}-{uuid.uuid4().hex[:6]}")
    owner_session.add(org)
    owner_session.flush()
    user = User(org_id=org.id, email=f"owner-{uuid.uuid4().hex[:10]}@synthetic.example.com",
                password_hash="!", role=UserRole.OWNER)
    owner_session.add(user)
    owner_session.flush()
    business = Business(org_id=org.id, owner_user_id=user.id, name=biz.name,
                        category=biz.business_type)
    owner_session.add(business)
    owner_session.flush()
    account_ids = []
    for spec in biz.accounts:
        account = Account(org_id=org.id, business_id=business.id, bank="demo", format="csv",
                          account_mask=spec.mask, account_type="current", upi_id=spec.upi_id)
        owner_session.add(account)
        owner_session.flush()
        account_ids.append(account.id)
    owner_session.commit()
    return Principal(user.id, org.id, UserRole.OWNER), business.id, account_ids


def process(principal: Principal, account_ids: list[int],
            biz: GeneratedBusiness) -> dict[int, tuple[int, int]]:
    """Upload every statement in order and run the pipeline after each one.
    Returns upload id -> (account index, statement index)."""
    uploads = {}
    order = sorted(biz.statements, key=lambda s: (s.statement_index, s.account_index))
    for st in order:
        result = create_upload(principal, account_ids[st.account_index], str(uuid.uuid4()),
                               st.csv)
        uploads[result.upload.id] = (st.account_index, st.statement_index)
        dispatcher = InlineDispatcher()
        relay_once(pipeline_publisher(dispatcher))
        dispatcher.drain()
    return uploads


def evaluate(n: int, seed: int, config: GenConfig | None = None) -> Report:
    config = config or GenConfig()
    report = Report(n, seed, config)
    owner_engine = create_engine(get_settings().migration_database_url)
    started = time.perf_counter()
    for i in range(n):
        biz = generate(seed + i, config)
        with Session(owner_engine) as owner_session:
            principal, business_id, account_ids = load_business(owner_session, biz)
        uploads = process(principal, account_ids, biz)
        with tenant_session(principal.org_id) as s:
            refs = _refs(s, account_ids, uploads)
            report.transactions += len(refs)
            _score_business(s, business_id, biz, refs, report)
            for hook in HOOKS:
                hook(s, biz, refs, report, business_id)
    owner_engine.dispose()
    for finalize in FINALIZERS:
        finalize(report)
    report.seconds = time.perf_counter() - started
    return report


def _refs(s: Session, account_ids: list[int],
          uploads: dict[int, tuple[int, int]]) -> dict[int, str]:
    index = {account_id: i for i, account_id in enumerate(account_ids)}
    rows = s.execute(select(Transaction.id, Transaction.account_id, Transaction.upload_id,
                            Transaction.source_line)
                     .where(Transaction.account_id.in_(account_ids))).all()
    return {r.id: f"a{index[r.account_id]}:s{uploads[r.upload_id][1]}:{r.source_line}"
            for r in rows}


def _score_business(s: Session, business_id: int, biz: GeneratedBusiness,
                    refs: dict[int, str], report: Report) -> None:
    truth = biz.ground_truth
    _, links = current_links(s, business_id)

    def pairs(kind: EvidenceKind, level: EvidenceLevel | None) -> set[tuple[str, str]]:
        return {(refs[link.txn_a], refs[link.txn_b]) for link in links
                if link.kind == kind and link.txn_b is not None
                and (level is None or link.level == level)}

    def singles(kind: EvidenceKind, level: EvidenceLevel) -> int:
        return sum(1 for link in links if link.kind == kind and link.level == level)

    # SELF_TRANSFER: true pairs expected verified; ambiguous ones expected unresolved.
    st = report.score("SELF_TRANSFER")
    expected = {(d, c) for d, c, level in truth["self_transfers"] if level == "verified"}
    every_true = {(d, c) for d, c, _ in truth["self_transfers"]}
    predicted = pairs(EvidenceKind.SELF_TRANSFER, EvidenceLevel.VERIFIED)
    st.truth += len(expected)
    st.predicted += len(predicted)
    st.correct += len(predicted & every_true)
    st.found += len(predicted & expected)
    st.unresolved += len(pairs(EvidenceKind.SELF_TRANSFER, EvidenceLevel.UNRESOLVED))
    st.inferred += singles(EvidenceKind.SELF_TRANSFER, EvidenceLevel.INFERRED)

    rv = report.score("REVERSAL")
    expected = {(c, d) for c, d in truth["reversals"]}
    predicted = pairs(EvidenceKind.REVERSAL, EvidenceLevel.VERIFIED)
    rv.truth += len(expected)
    rv.predicted += len(predicted)
    rv.correct += len(predicted & expected)
    rv.found += len(predicted & expected)
    rv.unresolved += len(pairs(EvidenceKind.REVERSAL, EvidenceLevel.UNRESOLVED))
    rv.inferred += singles(EvidenceKind.REVERSAL, EvidenceLevel.INFERRED)

    dup = report.score("DUPLICATE")
    dup.note = "always unresolved by design; scored as detection"
    expected = {(a, b) for a, b in truth["duplicates"]}
    predicted = pairs(EvidenceKind.DUPLICATE, None)
    dup.truth += len(expected)
    dup.predicted += len(predicted)
    dup.correct += len(predicted & expected)
    dup.found += len(predicted & expected)
    dup.unresolved += len(predicted)

    loan = report.score("LOAN_DISBURSAL")
    loan.note = "needs the loan_in label (M8 classifier)"
    expected_loans = set(truth["loans"])
    predicted_loans = {refs[link.txn_a] for link in links
                       if link.kind == EvidenceKind.LOAN_DISBURSAL}
    loan.truth += len(expected_loans)
    loan.predicted += len(predicted_loans)
    loan.correct += len(predicted_loans & expected_loans)
    loan.found += len(predicted_loans & expected_loans)
    loan.inferred += len(predicted_loans)

    cyc = report.score("CYCLE")
    cyc.note = ("open flags; correct = about a planted flow (shares 2+ of its rows); "
                "found = one flag covers every counterparty leg of the flow")
    flagged = []
    for flag_id in s.scalars(select(Flag.id).where(Flag.business_id == business_id,
                                                   Flag.kind == FlagKind.CYCLE,
                                                   Flag.status == FlagStatus.OPEN)):
        txn_ids = s.scalars(select(FlagEvidence.txn_id).where(FlagEvidence.flag_id == flag_id))
        flagged.append({refs[t] for t in txn_ids})
    planted = [set(c) for c in truth["cycles"]]
    # A flow's identity is its legs to and from counterparties; a closing hop between the
    # business's own accounts can be any of several internal transfers in the window.
    legs = [{r for r in c if truth["labels"].get(r) != "transfer"} for c in planted]
    cyc.truth += len(planted)
    cyc.predicted += len(flagged)
    cyc.correct += sum(1 for f in flagged if any(len(p & f) >= 2 for p in planted))
    cyc.found += sum(1 for leg in legs if any(leg <= f for f in flagged))


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.3f}"


def render(report: Report) -> str:
    c = report.config
    lines = [
        "# Evidence engine evaluation on synthetic data",
        "",
        "Generated by `python -m synthetic.evaluate`. **These numbers show the pipeline finds "
        "what was planted in generated data. They do not measure accuracy on real Indian "
        "small-business statements**, which nobody has labelled for this project.",
        "",
        "## Setup",
        "",
        f"- Businesses: **{report.n}** (seeds {report.seed}–{report.seed + report.n - 1}), "
        f"{report.transactions:,} stored transactions, {report.seconds:.0f} s end to end "
        f"(upload → {' → '.join(PIPELINE)}, in-process).",
        f"- Config: {c.months} months from {c.start.isoformat()}, {c.min_accounts}–"
        f"{c.max_accounts} accounts, {c.self_transfers_per_month} self-transfers/month "
        f"({c.utr_share_pct}% with UTR, {c.next_day_pct}% next day), ambiguous transfer every "
        f"{c.ambiguous_every_months} months, {c.reversals_per_month} reversals/month, "
        f"near-duplicates every {c.near_duplicates_every_months} months, a circular flow in "
        f"~1 of {c.cycle_one_in} businesses, one loan disbursal each.",
        "",
        "## Results per rule",
        "",
        "| Rule | Planted | Predicted | Correct | Precision | Recall | Unresolved | Inferred "
        "| Note |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for s in report.scores.values():
        lines.append(f"| {s.rule} | {s.truth} | {s.predicted} | {s.correct} | "
                     f"{_pct(s.precision)} | {_pct(s.recall)} | {s.unresolved} | "
                     f"{s.inferred} | {s.note} |")
    if report.extra:
        lines += ["", "## Other measurements", ""]
        lines += [f"- **{k}:** {v}" for k, v in report.extra.items()]
    lines += [
        "",
        "## How to read this",
        "",
        "- *Precision* counts only `verified` predictions; *unresolved* and *inferred* ones go "
        "to a human or into the uncertain band, so they are neither hits nor false positives.",
        "- *Recall* is against events the rule is meant to prove (ambiguous self-transfers are "
        "planted so that `unresolved` is the right answer, and are not in the denominator).",
        "",
        "## Known ways the CYCLE rule misses a planted flow",
        "",
        "- **Window boundaries.** Windows are 30 days long but start every 15 days, so only "
        "round trips that complete within ~15 days are guaranteed to sit inside one window. "
        "A flow that returns 16–30 days later can straddle two windows and be missed.",
        "- **Duplicated rows.** If a near-duplicate statement row copies one leg of a flow, the "
        "ledger holds that leg twice, money back no longer matches money out within 10%, and "
        "the flow isn't reported. (The duplicate itself is flagged as unresolved.)",
        "",
        "## Limitations",
        "",
        "- The generator and the rules were written by the same people; narration formats, "
        "windows and amounts follow the spec the rules were built from. Real statements will "
        "have formats and edge cases this data never exercises.",
        "- Only the `demo_bank` CSV format is generated.",
        "- Counterparties in cycles are unique firms; real circular trading often reuses known "
        "suppliers and customers, which makes it harder to see.",
        "- This says nothing about creditworthiness. KhataIQ measures cash flow and evidence; it "
        "does not score borrowers.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the evidence engine on synthetic data")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--out", type=Path, default=Path("docs/results/evidence_eval.md"))
    args = parser.parse_args()
    report = evaluate(args.n, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report))
    for s in report.scores.values():
        print(f"{s.rule:16} precision={_pct(s.precision)} recall={_pct(s.recall)}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
