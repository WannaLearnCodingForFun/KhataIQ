"""M5.1/M5.2: each evidence rule on hand-built ledgers, including window edges."""

import pytest

from khataiq.evidence.duplicate import duplicate_links
from khataiq.evidence.loan import loan_links
from khataiq.evidence.reversal import reversal_links
from khataiq.evidence.self_transfer import self_transfer_links
from khataiq.evidence.types import AccountInfo
from khataiq.models.enums import EvidenceKind, EvidenceLevel
from tests.unit.evidence_helpers import lt

VER, INF, UNR = EvidenceLevel.VERIFIED, EvidenceLevel.INFERRED, EvidenceLevel.UNRESOLVED
ACCOUNTS = [AccountInfo(1, "1234", "shop@okaxis"), AccountInfo(2, "5678", None)]


def triples(links):
    return [(link.txn_a, link.txn_b, link.level) for link in links]


# ------------------------------------------------------------------ SELF_TRANSFER

@pytest.mark.parametrize("gap, matched", [(0, True), (2, True), (3, False)])
def test_self_transfer_window_edges(gap, matched):
    d = lt(account=1, direction="debit", amount=500_000)
    c = lt(account=2, day=gap, amount=500_000)
    links = self_transfer_links([d, c], ACCOUNTS)
    assert triples(links) == ([(d.id, c.id, VER)] if matched else [])


def test_self_transfer_ambiguity_is_unresolved():
    d = lt(account=1, direction="debit", amount=500_000)
    c1, c2 = lt(account=2, amount=500_000), lt(account=2, day=1, amount=500_000)
    assert triples(self_transfer_links([d, c1, c2], ACCOUNTS)) == [(d.id, c1.id, UNR),
                                                                   (d.id, c2.id, UNR)]


def test_inferred_from_another_accounts_mask_or_own_upi():
    # Distinct amounts, so none of these can pair up as a verified transfer.
    to_other = lt(account=1, direction="debit", amount=1_001,
                  narration="NEFT DR TO A/C XXXX5678 SELF")
    own_mask = lt(account=1, direction="debit", amount=1_002, narration="NEFT DR TO A/C XXXX1234")
    from_upi = lt(account=2, amount=1_003, narration="UPI/SHOP@OKAXIS/412300000001")
    invoice = lt(account=1, direction="debit", amount=1_004,
                 narration="NEFT INV 156789 SUPPLIER")
    links = self_transfer_links([to_other, own_mask, from_upi, invoice], ACCOUNTS)
    assert triples(links) == [(to_other.id, None, INF), (from_upi.id, None, INF)]
    assert links[0].details == {"evidence": "account_mask:5678"}
    assert links[1].details == {"evidence": "upi_id:shop@okaxis"}


def test_matched_rows_are_not_also_inferred():
    d = lt(account=1, direction="debit", amount=9_000, narration="TO A/C XXXX5678")
    c = lt(account=2, amount=9_000)
    assert triples(self_transfer_links([d, c], ACCOUNTS)) == [(d.id, c.id, VER)]


# ------------------------------------------------------------------ REVERSAL

@pytest.mark.parametrize("gap, level", [(0, VER), (7, VER), (8, INF)])
def test_reversal_window_edges(gap, level):
    d = lt(direction="debit", amount=40_000, cp="vpa:shop@ybl", narration="UPI/SHOP@YBL")
    c = lt(day=gap, amount=40_000, cp="vpa:shop@ybl", narration="UPI/REV/SHOP@YBL")
    expected = (c.id, d.id, VER) if level == VER else (c.id, None, INF)
    assert triples(reversal_links([d, c])) == [expected]


def test_reversal_needs_a_keyword_same_account_and_counterparty():
    d = lt(direction="debit", amount=40_000, cp="vpa:a@ybl")
    no_keyword = lt(amount=40_000, cp="vpa:a@ybl", narration="UPI/A@YBL")
    other_cp = lt(amount=40_000, cp="vpa:b@ybl", narration="UPI REFUND")
    other_acct = lt(account=2, amount=40_000, cp="vpa:a@ybl", narration="UPI REFUND")
    links = reversal_links([d, no_keyword, other_cp, other_acct])
    assert triples(links) == [(other_cp.id, None, INF), (other_acct.id, None, INF)]


def test_keyword_is_a_whole_word():
    c = lt(amount=1_000, narration="NEFT REVENUE SHARE")
    assert reversal_links([c]) == []


def test_several_candidate_debits_are_unresolved():
    d1 = lt(direction="debit", amount=40_000, cp=None)
    d2 = lt(day=1, direction="debit", amount=40_000, cp=None)
    c = lt(day=2, amount=40_000, cp=None, narration="IMPS FAILED TXN RETURN")
    assert triples(reversal_links([d1, d2, c])) == [(c.id, d1.id, UNR), (c.id, d2.id, UNR)]


def test_one_debit_claimed_by_two_reversals_is_unresolved():
    d = lt(direction="debit", amount=40_000)
    c1 = lt(day=1, amount=40_000, narration="REFUND")
    c2 = lt(day=2, amount=40_000, narration="REFUND")
    assert triples(reversal_links([d, c1, c2])) == [(c1.id, d.id, UNR), (c2.id, d.id, UNR)]


# ------------------------------------------------------------------ DUPLICATE

def test_near_duplicate_across_uploads_is_unresolved():
    a = lt(upload=1, fp="x", narration="UPI/CHAI")
    b = lt(upload=2, fp="y", narration="UPI/CHAI")
    assert triples(duplicate_links([a, b])) == [(a.id, b.id, UNR)]
    assert duplicate_links([a, b])[0].kind == EvidenceKind.DUPLICATE


def test_repeated_payment_within_one_statement_is_not_a_duplicate():
    a = lt(upload=1, fp="x", narration="UPI/CHAI")
    b = lt(upload=1, fp="y", narration="UPI/CHAI")
    assert duplicate_links([a, b]) == []


def test_duplicate_needs_every_field_equal():
    a = lt(upload=1, narration="UPI/CHAI")
    assert duplicate_links([a, lt(upload=2, narration="UPI/TEA")]) == []
    assert duplicate_links([a, lt(upload=2, day=1, narration="UPI/CHAI")]) == []
    assert duplicate_links([a, lt(upload=2, account=2, narration="UPI/CHAI")]) == []


# ------------------------------------------------------------------ LOAN_DISBURSAL

def test_loan_needs_keyword_and_label():
    both = lt(narration="NEFT CR BAJAJ FIN LOAN DISB", label="loan_in")
    keyword_only = lt(narration="NEFT CR BAJAJ FIN LOAN DISB", label="sales")
    label_only = lt(narration="NEFT CR SHARMA", label="loan_in")
    debit = lt(direction="debit", narration="LOAN EMI", label="loan_in")
    assert triples(loan_links([both, keyword_only, label_only, debit])) == [(both.id, None, INF)]


def test_rules_are_deterministic_whatever_the_input_order():
    import random

    rows = [lt(account=1 + i % 2, day=i % 5, amount=1_000 * (i % 3 + 1),
               direction="debit" if i % 2 else "credit", narration="UPI REFUND",
               upload=1 + i % 2) for i in range(40)]
    shuffled = rows[:]
    random.Random(1).shuffle(shuffled)
    for rule in (reversal_links, duplicate_links, loan_links,
                 lambda t: self_transfer_links(t, ACCOUNTS)):
        assert triples(rule(rows)) == triples(rule(shuffled))
