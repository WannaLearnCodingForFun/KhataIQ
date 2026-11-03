"""M5 property tests: invariants every rule must keep on any ledger."""

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from khataiq.evidence.cycles import find_cycles
from khataiq.evidence.duplicate import duplicate_links
from khataiq.evidence.reversal import reversal_links
from khataiq.evidence.self_transfer import self_transfer_links
from khataiq.evidence.types import AccountInfo, LedgerTxn
from khataiq.models.enums import EvidenceLevel

ACCOUNTS = [AccountInfo(1, "1111", "own@okaxis"), AccountInfo(2, "2222", None),
            AccountInfo(3, "3333", None)]
NARRATIONS = ["UPI/A", "UPI REFUND", "NEFT REV", "TO XXXX2222", "UPI/OWN@OKAXIS", "CASH"]
COUNTERPARTIES = [None, "vpa:a@ybl", "vpa:b@ybl", "name:ALPHA"]


@st.composite
def ledgers(draw):
    n = draw(st.integers(0, 30))
    return [LedgerTxn(
        id=i + 1, account_id=draw(st.integers(1, 3)), upload_id=draw(st.integers(1, 3)),
        txn_date=date(2026, 10, 1) + timedelta(days=draw(st.integers(0, 40))),
        amount_paise=draw(st.sampled_from([50_000, 1_200_000, 2_000_000])),
        direction=draw(st.sampled_from(["debit", "credit"])), balance_after_paise=0,
        narration_norm=draw(st.sampled_from(NARRATIONS)), utr=draw(st.sampled_from([None, "U1"])),
        counterparty_key=draw(st.sampled_from(COUNTERPARTIES)),
        fingerprint=f"fp{draw(st.integers(0, 5))}-{i}") for i in range(n)]


@settings(max_examples=150)
@given(ledgers(), st.randoms(use_true_random=False))
def test_links_are_valid_and_input_order_does_not_matter(txns, rng):
    ids = {t.id for t in txns}
    shuffled = list(txns)
    rng.shuffle(shuffled)
    for rule in (lambda t: self_transfer_links(t, ACCOUNTS), reversal_links, duplicate_links):
        links = rule(txns)
        assert links == rule(shuffled)
        for link in links:
            assert link.txn_a in ids and (link.txn_b is None or link.txn_b in ids)


@settings(max_examples=150)
@given(ledgers())
def test_no_transaction_backs_two_verified_matches_of_one_rule(txns):
    for links in (self_transfer_links(txns, ACCOUNTS), reversal_links(txns)):
        used = [i for link in links if link.level == EvidenceLevel.VERIFIED
                for i in (link.txn_a, link.txn_b) if i is not None]
        assert len(used) == len(set(used))


@settings(max_examples=100)
@given(ledgers())
def test_cycle_findings_are_within_their_rules(txns):
    by_id = {t.id: t for t in txns}
    for finding in find_cycles(txns, []):
        assert finding.out_paise >= 1_000_000
        assert abs(finding.out_paise - finding.back_paise) * 10 <= max(finding.out_paise,
                                                                      finding.back_paise)
        assert (finding.window_end - finding.window_start).days == 30
        for i in finding.txn_ids:
            assert finding.window_start <= by_id[i].txn_date < finding.window_end
