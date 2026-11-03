"""The copilot's tools: typed, read-only, scoped to one org (RLS) and one business (injected
by the server, never chosen by the model).

Each tool returns (result for the model, citable rows). Citable rows feed the grounding
checker: ('txn', id) -> amount_paise, ('metric', yyyymm) -> that month's paise figures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq.copilot.grounding import Evidence
from khataiq.models import Transaction, Upload
from khataiq.models.enums import EvidenceKind, EvidenceLevel, FlagStatus, TxnLabel
from khataiq.principal import Principal
from khataiq.services import evidence, flags, ledger, metrics, uploads


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricsArgs(_Args):
    from_month: date | None = Field(default=None, description="First day of the first month")
    to_month: date | None = Field(default=None, description="First day of the last month")


class TransactionsArgs(_Args):
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    label: TxnLabel | None = None
    direction: Literal["debit", "credit"] | None = None
    min_paise: int | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=50)


class FlagsArgs(_Args):
    status: FlagStatus | None = None


class EvidenceArgs(_Args):
    kind: EvidenceKind | None = None
    level: EvidenceLevel | None = None


class NoArgs(_Args):
    pass


@dataclass
class ToolContext:
    session: Session
    principal: Principal
    business_id: int
    evidence: Evidence


def metric_id(month: date) -> int:
    return month.year * 100 + month.month


def _txn_row(t: Transaction, label: str | None = None) -> dict[str, Any]:
    return {"id": t.id, "date": t.txn_date.isoformat(), "amount_paise": t.amount_paise,
            "direction": t.direction.value, "narration": t.narration, "label": label}


def get_monthly_metrics(ctx: ToolContext, args: MetricsArgs) -> dict[str, Any]:
    run, months = metrics.latest(ctx.session, ctx.business_id)
    rows = []
    for m in months:
        if args.from_month and m.month < args.from_month.replace(day=1):
            continue
        if args.to_month and m.month > args.to_month.replace(day=1):
            continue
        values = {"gross_inflow_paise": m.gross_inflow_paise,
                  "net_business_inflow_paise": m.net_business_inflow_paise,
                  "uncertain_paise": m.uncertain_paise, "outflow_paise": m.outflow_paise,
                  "obligations_paise": m.obligations_paise,
                  "closing_balance_paise": m.closing_balance_paise}
        ctx.evidence.add("metric", metric_id(m.month),
                         [v for v in values.values() if v is not None])
        rows.append({"id": metric_id(m.month), "month": m.month.isoformat(), **values,
                     "volatility_bp": m.volatility_bp})
    return {"metric_run_id": run.id if run else None, "months": rows}


def list_transactions(ctx: ToolContext, args: TransactionsArgs) -> dict[str, Any]:
    filters = ledger.TxnFilters(since=args.from_, until=args.to, label=args.label,
                                direction=args.direction, min_paise=args.min_paise)
    rows, _ = ledger.list_transactions(ctx.session, ctx.principal, ctx.business_id, filters,
                                       None, args.limit)
    result = []
    for r in rows:
        ctx.evidence.add("txn", r.txn.id, [r.txn.amount_paise])
        row = _txn_row(r.txn, r.label)
        row["evidence_level"] = r.evidence.level.value if r.evidence else None
        result.append(row)
    return {"transactions": result}


def get_flags(ctx: ToolContext, args: FlagsArgs) -> dict[str, Any]:
    rows = flags.list_flags(ctx.session, args.status, None, ctx.business_id, None, 50)[:50]
    result = []
    for flag in rows:
        txns = flags.flag_transactions(ctx.session, flag.id)
        for t in txns:
            ctx.evidence.add("txn", t.id, [t.amount_paise])
        result.append({"id": flag.id, "kind": flag.kind.value, "status": flag.status.value,
                       "summary": flag.summary, "total_paise": flag.total_paise,
                       "evidence": [_txn_row(t) for t in txns]})
    return {"flags": result}


def get_evidence(ctx: ToolContext, args: EvidenceArgs) -> dict[str, Any]:
    run_id, links = evidence.current_links(ctx.session, ctx.business_id, args.kind, args.level)
    ids = {i for link in links for i in (link.txn_a, link.txn_b) if i is not None}
    txns = {t.id: t for t in ctx.session.scalars(select(Transaction)
                                                 .where(Transaction.id.in_(ids)))}
    for t in txns.values():
        ctx.evidence.add("txn", t.id, [t.amount_paise])
    return {"evidence_run_id": run_id, "links": [
        {"kind": link.kind.value, "level": link.level.value, "rule": link.rule_id,
         "transactions": [_txn_row(txns[i]) for i in (link.txn_a, link.txn_b)
                          if i is not None and i in txns]}
        for link in links[:100]]}


def get_upload_status(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    rows: list[Upload] = uploads.list_uploads(ctx.session, ctx.principal, ctx.business_id,
                                              None, 50)
    return {"uploads": [
        {"id": u.id, "account_id": u.account_id, "status": u.status.value,
         "period_start": u.period_start.isoformat() if u.period_start else None,
         "period_end": u.period_end.isoformat() if u.period_end else None,
         "reconciliation": None if u.recon_reason is None else {
             "reason": u.recon_reason, "break_line": u.recon_break_line}}
        for u in rows]}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[_Args]
    run: Callable[[ToolContext, Any], dict[str, Any]]

    def definition(self) -> dict[str, Any]:
        """The tool's JSON schema, trimmed for strict tool use: no titles or defaults (not
        needed by the model, and not part of the strict-schema subset), and no extra keys."""
        schema = _strip(self.args.model_json_schema(by_alias=True))
        schema["additionalProperties"] = False
        return {"name": self.name, "description": self.description, "input_schema": schema}


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("title", "default")}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in [
    ToolSpec("get_monthly_metrics",
             "Monthly cash-flow metrics for this business from the latest metric run. Each "
             "month has an id (cite it as type 'metric').", MetricsArgs, get_monthly_metrics),
    ToolSpec("list_transactions",
             "Ledger transactions for this business, newest first, with current label and "
             "evidence level. Cite rows as type 'txn'.", TransactionsArgs, list_transactions),
    ToolSpec("get_flags", "Review flags for this business with their evidence transactions.",
             FlagsArgs, get_flags),
    ToolSpec("get_evidence",
             "Evidence links (self-transfers, reversals, duplicates, loan disbursals) of the "
             "current evidence run, with their transactions.", EvidenceArgs, get_evidence),
    ToolSpec("get_upload_status", "Uploaded statements and their reconciliation results.",
             NoArgs, get_upload_status),
]}


class ToolError(Exception):
    pass


def run_tool(ctx: ToolContext, name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(f"unknown tool {name!r}")
    try:
        args = spec.args.model_validate(raw_input)
    except ValidationError as exc:
        raise ToolError(f"invalid arguments: {exc.errors(include_input=False)}") from exc
    return spec.run(ctx, args)
