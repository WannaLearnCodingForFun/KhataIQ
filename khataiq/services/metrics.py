"""Recompute and read monthly metrics. Each recompute is a new metric run; history is kept."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from khataiq.evidence.types import Link
from khataiq.metrics.monthly import monthly_metrics
from khataiq.models import Business, MetricRun, MonthlyMetric
from khataiq.services.evidence import current_links, load_ledger


def recompute(s: Session, business_id: int) -> MetricRun:
    business = s.get(Business, business_id)
    assert business is not None
    txns, _ = load_ledger(s, business_id)
    evidence_run_id, rows = current_links(s, business_id)
    links = [Link(r.kind, r.txn_a, r.txn_b, r.level, r.rule_id, r.rule_version) for r in rows]
    run = MetricRun(org_id=business.org_id, business_id=business_id,
                    evidence_run_id=evidence_run_id)
    s.add(run)
    s.flush()
    s.add_all(MonthlyMetric(
        org_id=business.org_id, business_id=business_id, month=m.month, run_id=run.id,
        gross_inflow_paise=m.gross_inflow_paise,
        net_business_inflow_paise=m.net_business_inflow_paise,
        uncertain_paise=m.uncertain_paise, outflow_paise=m.outflow_paise,
        obligations_paise=m.obligations_paise, closing_balance_paise=m.closing_balance_paise,
        volatility_bp=m.volatility_bp,
    ) for m in monthly_metrics(txns, links))
    return run


def latest(s: Session, business_id: int) -> tuple[MetricRun | None, list[MonthlyMetric]]:
    run_id = s.scalar(select(func.max(MetricRun.id)).where(MetricRun.business_id == business_id))
    if run_id is None:
        return None, []
    rows = s.scalars(select(MonthlyMetric).where(MonthlyMetric.run_id == run_id)
                     .order_by(MonthlyMetric.month)).all()
    return s.get(MetricRun, run_id), list(rows)
