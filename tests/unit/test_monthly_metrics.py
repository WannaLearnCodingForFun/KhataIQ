"""M6.1: monthly metrics, by hand and as properties."""

from datetime import date, timedelta
from statistics import pstdev

from hypothesis import given, settings
from hypothesis import strategies as st

from khataiq.evidence.types import LedgerTxn, Link
from khataiq.metrics.monthly import monthly_metrics, volatility_bp
from khataiq.models.enums import EvidenceKind, EvidenceLevel
from tests.unit.evidence_helpers import lt

ST, REV, DUP, LOAN = (EvidenceKind.SELF_TRANSFER, EvidenceKind.REVERSAL, EvidenceKind.DUPLICATE,
                      EvidenceKind.LOAN_DISBURSAL)
VER, INF, UNR = EvidenceLevel.VERIFIED, EvidenceLevel.INFERRED, EvidenceLevel.UNRESOLVED


def link(kind, a, b, level):
    return Link(kind, a, b, level, kind.value.upper(), 1)


def test_net_inflow_removes_exclusions_and_reports_uncertainty():
    sale = lt(day=1, amount=100_000)
    transfer_in = lt(account=2, day=2, amount=50_000)
    transfer_out = lt(account=1, day=2, direction="debit", amount=50_000)
    refund = lt(day=3, amount=7_000)
    maybe_mine = lt(day=4, amount=20_000)
    loan = lt(day=5, amount=300_000, label="loan_in")
    rent = lt(day=6, direction="debit", amount=40_000, label="rent")
    links = [link(ST, transfer_out.id, transfer_in.id, VER),
             link(REV, refund.id, None, INF),
             link(ST, maybe_mine.id, None, INF),
             link(LOAN, loan.id, None, INF)]
    [m] = monthly_metrics([sale, transfer_in, transfer_out, refund, maybe_mine, loan, rent], links)
    assert m.gross_inflow_paise == 477_000
    assert m.excluded_verified_paise == 350_000          # transfer in + loan
    assert m.uncertain_paise == 27_000                   # refund + maybe_mine
    assert m.net_business_inflow_paise == 100_000        # just the sale
    assert m.outflow_paise == 40_000                     # the self-transfer debit isn't spending
    assert m.obligations_paise == 40_000


def test_a_credit_in_several_links_counts_once():
    c = lt(amount=10_000)
    d1, d2 = lt(direction="debit", amount=10_000), lt(direction="debit", amount=10_000)
    [m] = monthly_metrics([c, d1, d2], [link(REV, c.id, d1.id, UNR), link(REV, c.id, d2.id, UNR)])
    assert m.uncertain_paise == 10_000


def test_excluded_wins_over_uncertain():
    c = lt(account=2, amount=10_000)
    d = lt(direction="debit", amount=10_000)
    [m] = monthly_metrics([c, d], [link(ST, d.id, c.id, VER), link(REV, c.id, None, INF)])
    assert (m.excluded_verified_paise, m.uncertain_paise) == (10_000, 0)


def test_only_the_copy_of_a_duplicate_is_uncertain():
    a, b = lt(amount=5_000, upload=1), lt(amount=5_000, upload=2)
    [m] = monthly_metrics([a, b], [link(DUP, a.id, b.id, UNR)])
    assert (m.gross_inflow_paise, m.uncertain_paise) == (10_000, 5_000)


def test_months_are_contiguous_and_balances_carry_forward():
    oct_row = LedgerTxn(1, 1, 1, date(2026, 10, 5), 100, "credit", 900, "X", None, None, "a")
    dec_row = LedgerTxn(2, 2, 1, date(2026, 12, 5), 100, "credit", 50, "X", None, None, "b")
    months = monthly_metrics([oct_row, dec_row], [])
    assert [m.month for m in months] == [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)]
    assert [m.closing_balance_paise for m in months] == [900, 900, 950]
    assert months[1].gross_inflow_paise == 0


def test_volatility_matches_the_textbook_formula():
    flows = [1_000, -200, 3_000, 0, 500]
    expected = pstdev(flows) / abs(sum(flows) / len(flows)) * 10_000
    assert abs(volatility_bp(flows) - expected) < 1
    assert volatility_bp([]) == 0 and volatility_bp([5, -5]) == 0
    assert volatility_bp([700, 700, 700]) == 0


@st.composite
def ledger_and_links(draw):
    n = draw(st.integers(1, 40))
    txns = [LedgerTxn(i + 1, draw(st.integers(1, 2)), draw(st.integers(1, 2)),
                      date(2026, 9, 1) + timedelta(days=draw(st.integers(0, 90))),
                      draw(st.integers(1, 5_000_000)), draw(st.sampled_from(["debit", "credit"])),
                      draw(st.integers(0, 10**9)), "X", None, None, f"f{i}",
                      draw(st.sampled_from([None, "rent", "emi", "sales"])))
            for i in range(n)]
    ids = [t.id for t in txns]
    links = [link(draw(st.sampled_from([ST, REV, DUP, LOAN])), draw(st.sampled_from(ids)),
                  draw(st.sampled_from([None, *ids])), draw(st.sampled_from([VER, INF, UNR])))
             for _ in range(draw(st.integers(0, 15)))]
    return txns, links


@settings(max_examples=200)
@given(ledger_and_links())
def test_metric_invariants(data):
    txns, links = data
    months = monthly_metrics(txns, links)
    assert sum(m.gross_inflow_paise for m in months) == sum(
        t.amount_paise for t in txns if t.is_credit)
    for m in months:
        assert 0 <= m.uncertain_paise
        assert 0 <= m.excluded_verified_paise
        assert m.net_business_inflow_paise <= m.gross_inflow_paise
        assert m.excluded_verified_paise + m.uncertain_paise <= m.gross_inflow_paise
        assert 0 <= m.obligations_paise <= m.outflow_paise + sum(
            t.amount_paise for t in txns if not t.is_credit and t.txn_date.month == m.month.month
            and t.txn_date.year == m.month.year)
        assert isinstance(m.volatility_bp, int) and m.volatility_bp >= 0
    assert monthly_metrics(txns, links) == monthly_metrics(list(reversed(txns)), links)
