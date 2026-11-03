"""Monthly cash-flow metrics, versioned by run so a recompute never overwrites history."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from khataiq.db import Base
from khataiq.models.base import created_at_column, id_column, org_id_column


class MetricRun(Base):
    __tablename__ = "metric_runs"

    id: Mapped[int] = id_column()
    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    evidence_run_id: Mapped[int | None]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_metric_runs_business", "business_id", "id"),)


class MonthlyMetric(Base):
    __tablename__ = "monthly_metrics"

    org_id: Mapped[int] = org_id_column()
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    month: Mapped[date]  # first day of the month
    run_id: Mapped[int] = mapped_column(ForeignKey("metric_runs.id"))
    gross_inflow_paise: Mapped[int]
    net_business_inflow_paise: Mapped[int]
    uncertain_paise: Mapped[int]
    outflow_paise: Mapped[int]
    obligations_paise: Mapped[int]
    closing_balance_paise: Mapped[int | None]
    volatility_bp: Mapped[int]
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (PrimaryKeyConstraint("business_id", "month", "run_id"),)
