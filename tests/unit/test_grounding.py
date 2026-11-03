"""M9.2: the grounding checker."""

import pytest

from khataiq.copilot.grounding import Citation, Evidence, check, rupee_amounts


def evidence() -> Evidence:
    ev = Evidence()
    ev.add("txn", 11, [2_500_000])        # ₹25,000
    ev.add("txn", 12, [1_234_550])        # ₹12,345.50
    ev.add("metric", 202610, [9_000_000, 450_000])  # net ₹90,000, uncertain ₹4,500
    return ev


def test_parses_rupee_amounts():
    assert rupee_amounts("₹12,345.50 and ₹1,23,456 then ₹5") == [
        ("₹12,345.50", 1_234_550, True), ("₹1,23,456", 12_345_600, False), ("₹5", 500, False)]


def test_a_clean_answer_passes():
    r = check("Net business inflow in October was ₹90,000, of which ₹4,500 is uncertain.",
              [Citation("metric", 202610)], evidence())
    assert r.ok, r.problems


def test_sums_and_differences_of_up_to_three_cited_values_pass():
    cites = [Citation("txn", 11), Citation("txn", 12), Citation("metric", 202610)]
    assert check("Together ₹37,345.50.", cites, evidence()).ok           # 25,000 + 12,345.50
    assert check("A gap of ₹12,654.50.", cites, evidence()).ok           # 25,000 - 12,345.50
    assert check("₹1,02,345.50 in all.", cites, evidence()).ok           # 90,000 + 12,345.50
    assert check("₹1,27,345.50 in all.", cites, evidence()).ok           # three values


def test_rounded_rupees_are_accepted_but_wrong_paise_are_not():
    cites = [Citation("txn", 12)]
    assert check("About ₹12,346.", cites, evidence()).ok
    assert not check("Exactly ₹12,345.00.", cites, evidence()).ok


def test_citing_an_id_no_tool_returned_is_rejected():
    r = check("₹25,000 was paid.", [Citation("txn", 99)], evidence())
    assert not r.ok and "txn:99" in r.problems[0]


def test_wrong_citation_type_is_rejected():
    assert not check("x", [Citation("metric", 11)], evidence()).ok


def test_a_figure_not_in_the_cited_rows_is_rejected():
    r = check("Revenue was ₹50,000.", [Citation("txn", 11)], evidence())
    assert not r.ok and "₹50,000" in r.problems[0]


def test_a_figure_with_no_citation_is_rejected():
    r = check("Revenue was ₹25,000.", [], evidence())
    assert not r.ok and "nothing is cited" in r.problems[0]


def test_one_value_cannot_be_counted_twice():
    assert not check("₹50,000.", [Citation("txn", 11)], evidence()).ok


def test_values_in_rows_that_were_returned_but_not_cited_do_not_count():
    r = check("₹25,000.", [Citation("txn", 12)], evidence())
    assert not r.ok


@pytest.mark.parametrize("text", ["No amounts here.", "The business has 3 accounts."])
def test_answers_without_figures_need_no_citations(text):
    assert check(text, [], evidence()).ok
