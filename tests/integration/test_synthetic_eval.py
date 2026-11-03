"""M7.2: a small evaluation run in CI. The full 200-business run writes
docs/results/evidence_eval.md; this guards the acceptance bar on every push."""

import pytest

from synthetic.evaluate import evaluate, render

pytestmark = pytest.mark.usefixtures("migrated", "local_store")


def test_small_evaluation_meets_the_acceptance_bar():
    report = evaluate(n=6, seed=500)
    st = report.scores["SELF_TRANSFER"]
    assert st.precision is None or st.precision >= 0.98
    rv = report.scores["REVERSAL"]
    assert rv.precision is not None and rv.precision >= 0.95
    assert rv.recall is not None and rv.recall >= 0.9
    dup = report.scores["DUPLICATE"]
    assert dup.recall == 1.0
    assert "Limitations" in render(report)
