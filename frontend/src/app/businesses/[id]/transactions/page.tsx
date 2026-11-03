"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { use, useEffect, useMemo, useRef, useState } from "react";

import { RequireRole } from "@/components/guards";
import { Card, Empty, ErrorBox, Field, inputClass, LevelChip, Loading, Money } from "@/components/ui";
import { api, unwrap, type Schemas } from "@/lib/api";
import { isOfficer, useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/money";

type Txn = Schemas["TransactionOut"];
type Label = Schemas["TxnLabel"];
const LABELS: Label[] = ["sales", "supplier_payment", "rent", "salary_paid", "emi", "loan_in", "utilities", "cash_deposit",
  "cash_withdrawal", "tax", "bank_charges", "personal", "transfer", "refund", "other"];

type Filters = {
  from: string; to: string; label: "" | Label;
  evidence_level: "" | "verified" | "inferred" | "unresolved" | "none";
  direction: "" | "debit" | "credit";
};

function Relabel({ txn, businessId }: { txn: Txn; businessId: number }) {
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: async (label: Label) =>
      unwrap(await api.PATCH("/v1/transactions/{txn_id}/label", { params: { path: { txn_id: txn.id } }, body: { label } })),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["transactions", businessId] }),
  });
  return (
    <select
      aria-label={`Label for transaction ${txn.id}`}
      className={`${inputClass} py-0.5 text-xs`}
      value={txn.label ?? ""}
      disabled={save.isPending}
      onChange={(e) => save.mutate(e.target.value as Label)}
    >
      <option value="" disabled>unlabelled</option>
      {LABELS.map((l) => <option key={l}>{l}</option>)}
    </select>
  );
}

function Transactions({ businessId }: { businessId: number }) {
  const { me } = useAuth();
  const officer = isOfficer(me?.role);
  const [filters, setFilters] = useState<Filters>({ from: "", to: "", label: "", evidence_level: "", direction: "" });
  const query = useMemo(() => Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "")), [filters]);
  const pages = useInfiniteQuery({
    queryKey: ["transactions", businessId, query],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET("/v1/businesses/{business_id}/transactions", {
        params: { path: { business_id: businessId }, query: { ...query, limit: 100, cursor: pageParam } },
      })),
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = useMemo(() => pages.data?.pages.flatMap((p) => p.items) ?? [], [pages.data]);
  const scroller = useRef<HTMLDivElement>(null);
  const virtual = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => 44, overscan: 12 });
  const items = virtual.getVirtualItems();

  // Load the next page when the user scrolls near the end.
  const lastIndex = items.at(-1)?.index ?? 0;
  useEffect(() => {
    if (lastIndex >= rows.length - 10 && pages.hasNextPage && !pages.isFetchingNextPage) void pages.fetchNextPage();
  }, [lastIndex, rows.length, pages]);

  // A citation link (#txn-123) scrolls to that row once it's loaded.
  const [target, setTarget] = useState<number | null>(null);
  useEffect(() => {
    const match = window.location.hash.match(/^#txn-(\d+)$/);
    if (match?.[1]) setTarget(Number(match[1]));
  }, []);
  useEffect(() => {
    if (target === null) return;
    const index = rows.findIndex((r) => r.id === target);
    if (index >= 0) virtual.scrollToIndex(index, { align: "center" });
  }, [target, rows, virtual]);

  const set = (key: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setFilters((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Transactions</h1>
      <Card>
        <div className="flex flex-wrap gap-3">
          <Field label="From"><input type="date" className={inputClass} value={filters.from} onChange={set("from")} /></Field>
          <Field label="To"><input type="date" className={inputClass} value={filters.to} onChange={set("to")} /></Field>
          <Field label="Direction">
            <select className={inputClass} value={filters.direction} onChange={set("direction")}>
              <option value="">any</option><option value="credit">credit</option><option value="debit">debit</option>
            </select>
          </Field>
          <Field label="Label">
            <select className={inputClass} value={filters.label} onChange={set("label")}>
              <option value="">any</option>
              {LABELS.map((l) => <option key={l}>{l}</option>)}
            </select>
          </Field>
          <Field label="Evidence">
            <select className={inputClass} value={filters.evidence_level} onChange={set("evidence_level")}>
              <option value="">any</option><option value="verified">verified</option><option value="inferred">inferred</option>
              <option value="unresolved">unresolved</option><option value="none">none</option>
            </select>
          </Field>
        </div>
      </Card>
      <Card>
        {pages.isPending && <Loading />}
        {pages.isError && <ErrorBox error={pages.error} />}
        {pages.data && rows.length === 0 && <Empty>No transactions match these filters.</Empty>}
        {rows.length > 0 && (
          <div role="table" aria-label="Transactions" className="text-sm">
            <div role="row" className="grid grid-cols-[7rem_1fr_8rem_9rem_10rem] gap-2 border-b border-[var(--line)] pb-2 font-medium text-[var(--muted)]">
              <span role="columnheader">Date</span><span role="columnheader">Narration</span>
              <span role="columnheader" className="text-right">Amount</span><span role="columnheader">Evidence</span>
              <span role="columnheader">Label</span>
            </div>
            <div ref={scroller} className="h-[32rem] overflow-y-auto">
              <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
                {items.map((item) => {
                  const t = rows[item.index];
                  if (!t) return null;
                  return (
                    <div
                      role="row"
                      key={t.id}
                      id={`txn-${t.id}`}
                      className={`absolute left-0 grid w-full grid-cols-[7rem_1fr_8rem_9rem_10rem] items-center gap-2 border-b border-[var(--line)] py-2 ${t.id === target ? "bg-amber-50" : ""}`}
                      style={{ transform: `translateY(${item.start}px)`, height: item.size }}
                    >
                      <span role="cell">{formatDate(t.txn_date)}</span>
                      <span role="cell" className="truncate" title={t.narration}>{t.narration}</span>
                      <span role="cell" className={`text-right ${t.direction === "credit" ? "text-[var(--verified)]" : ""}`}>
                        {t.direction === "credit" ? "+" : "−"}<Money paise={t.amount_paise} level={t.evidence_level} />
                      </span>
                      <span role="cell" className="flex flex-wrap gap-1">
                        {t.evidence_level && <LevelChip level={t.evidence_level} />}
                        {t.evidence_kinds.map((k) => <span key={k} className="text-xs text-[var(--muted)]">{k.replace("_", " ")}</span>)}
                      </span>
                      <span role="cell">
                        {officer ? <Relabel txn={t} businessId={businessId} /> : (
                          <span className="text-xs">{t.label ?? "–"}{t.label_method ? ` (${t.label_method})` : ""}</span>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
            {pages.isFetchingNextPage && <Loading label="Loading more…" />}
          </div>
        )}
      </Card>
    </div>
  );
}

export default function TransactionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireRole>
      <Transactions businessId={Number(id)} />
    </RequireRole>
  );
}
