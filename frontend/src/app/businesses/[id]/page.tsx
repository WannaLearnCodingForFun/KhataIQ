"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";

import { CashflowChart } from "@/components/cashflow-chart";
import { CopilotPanel } from "@/components/copilot-panel";
import { RequireRole } from "@/components/guards";
import { Card, Empty, ErrorBox, Loading, Money, StatusPill } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { isOfficer, useAuth } from "@/lib/auth";
import { formatDate, formatMonth } from "@/lib/money";

function Overview({ id }: { id: number }) {
  const { me } = useAuth();
  const officer = isOfficer(me?.role);
  const path = { params: { path: { business_id: id } } };
  const business = useQuery({ queryKey: ["business", id], queryFn: async () => unwrap(await api.GET("/v1/businesses/{business_id}", path)) });
  const metrics = useQuery({ queryKey: ["metrics", id], queryFn: async () => unwrap(await api.GET("/v1/businesses/{business_id}/metrics", path)) });
  const uploads = useQuery({ queryKey: ["uploads", id], queryFn: async () => unwrap(await api.GET("/v1/businesses/{business_id}/uploads", path)) });
  const flags = useQuery({
    queryKey: ["flags", "open", id],
    enabled: officer,
    queryFn: async () => unwrap(await api.GET("/v1/flags", { params: { query: { status: "open", business_id: id, limit: 100 } } })),
  });

  if (business.isPending) return <Loading />;
  if (business.isError) return <ErrorBox error={business.error} />;
  const b = business.data;
  const tabs = [
    { href: `/businesses/${id}/transactions`, label: "Transactions", show: true },
    { href: `/businesses/${id}/upload`, label: "Upload statement", show: me?.role === "owner" },
    { href: `/businesses/${id}/evidence`, label: "Evidence graph", show: officer },
    { href: `/businesses/${id}/assessment`, label: "Assessment", show: officer },
  ].filter((t) => t.show);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">{b.name}</h1>
          <p className="text-sm text-[var(--muted)]">
            {b.category} · {b.accounts.length} account{b.accounts.length === 1 ? "" : "s"}:{" "}
            {b.accounts.map((a) => `${a.bank} ••${a.account_mask}`).join(", ") || "none yet"}
          </p>
        </div>
        <nav aria-label="Business" className="flex flex-wrap gap-2">
          {tabs.map((t) => (
            <Link key={t.href} href={t.href} className="rounded-md border border-[var(--line)] bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
              {t.label}
            </Link>
          ))}
        </nav>
      </div>

      <div className={officer ? "grid gap-6 lg:grid-cols-[1fr_22rem]" : ""}>
        <div className="flex flex-col gap-6">
          <Card title="Monthly cash flow">
            {metrics.isPending && <Loading />}
            {metrics.isError && <ErrorBox error={metrics.error} />}
            {metrics.data && metrics.data.months.length === 0 && <Empty>No processed statements yet.</Empty>}
            {metrics.data && metrics.data.months.length > 0 && (
              <>
                <CashflowChart months={metrics.data.months} />
                <table className="mt-4 w-full text-sm">
                  <caption className="sr-only">Monthly figures</caption>
                  <thead className="text-left text-[var(--muted)]">
                    <tr>
                      <th className="py-1">Month</th>
                      <th className="py-1 text-right">Gross inflow</th>
                      <th className="py-1 text-right">Net business inflow</th>
                      <th className="py-1 text-right">Uncertain</th>
                      <th className="py-1 text-right">Outflow</th>
                      <th className="py-1 text-right">Closing balance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.data.months.map((m) => (
                      <tr key={m.month} id={`month-${m.month.slice(0, 4)}${m.month.slice(5, 7)}`} className="border-t border-[var(--line)] target:bg-amber-50">
                        <td className="py-1">{formatMonth(m.month)}</td>
                        <td className="py-1 text-right"><Money paise={m.gross_inflow_paise} /></td>
                        <td className="py-1 text-right font-medium"><Money paise={m.net_business_inflow_paise} /></td>
                        <td className="py-1 text-right text-[var(--inferred)]"><Money paise={m.uncertain_paise} level="unresolved" /></td>
                        <td className="py-1 text-right"><Money paise={m.outflow_paise} /></td>
                        <td className="py-1 text-right">{m.closing_balance_paise === null ? "–" : <Money paise={m.closing_balance_paise} />}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </Card>

          <div className="grid gap-6 md:grid-cols-2">
            <Card title="Latest uploads">
              {uploads.isPending && <Loading />}
              {uploads.isError && <ErrorBox error={uploads.error} />}
              {uploads.data && uploads.data.items.length === 0 && <Empty>No statements uploaded.</Empty>}
              <ul className="divide-y divide-[var(--line)] text-sm">
                {uploads.data?.items.slice(0, 8).map((u) => (
                  <li key={u.id} className="flex items-center justify-between py-2">
                    <span>
                      #{u.id} · {u.period_start ? `${formatDate(u.period_start)} – ${formatDate(u.period_end ?? u.period_start)}` : "not parsed yet"}
                    </span>
                    <StatusPill status={u.status} />
                  </li>
                ))}
              </ul>
            </Card>
            {officer && (
              <Card title="Open flags">
                {flags.isPending && <Loading />}
                {flags.isError && <ErrorBox error={flags.error} />}
                {flags.data && (
                  <p className="text-sm">
                    <span className="text-3xl font-semibold">{flags.data.items.length}</span> open ·{" "}
                    <Link className="underline" href={`/flags?business=${id}`}>
                      review
                    </Link>
                  </p>
                )}
              </Card>
            )}
          </div>
        </div>
        {officer && <CopilotPanel businessId={id} />}
      </div>
    </div>
  );
}

export default function BusinessPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireRole>
      <Overview id={Number(id)} />
    </RequireRole>
  );
}
