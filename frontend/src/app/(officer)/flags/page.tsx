"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { RequireRole } from "@/components/guards";
import { Button, Card, Empty, ErrorBox, Field, inputClass, Loading, Money, StatusPill } from "@/components/ui";
import { api, unwrap, type Schemas } from "@/lib/api";
import { formatDate } from "@/lib/money";

type Status = Schemas["FlagStatus"];

function Drawer({ flagId, onClose }: { flagId: number; onClose: () => void }) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const flag = useQuery({
    queryKey: ["flag", flagId],
    queryFn: async () => unwrap(await api.GET("/v1/flags/{flag_id}", { params: { path: { flag_id: flagId } } })),
  });
  const resolve = useMutation({
    mutationFn: async (status: "confirmed" | "dismissed") =>
      unwrap(await api.PATCH("/v1/flags/{flag_id}", { params: { path: { flag_id: flagId } }, body: { status, note } })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["flags"] });
      onClose();
    },
  });
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="flag-title" className="fixed inset-y-0 right-0 z-10 flex w-full max-w-xl flex-col gap-4 overflow-y-auto border-l border-[var(--line)] bg-white p-6 shadow-xl">
      <div className="flex items-center justify-between">
        <h2 id="flag-title" className="text-lg font-semibold">Flag #{flagId}</h2>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
      {flag.isPending && <Loading />}
      {flag.isError && <ErrorBox error={flag.error} />}
      {flag.data && (
        <>
          <p className="text-sm">{flag.data.summary}</p>
          <p className="text-sm text-[var(--muted)]">
            {flag.data.kind.replace(/_/g, " ")} · rule {flag.data.rule_id} v{flag.data.rule_version} · <StatusPill status={flag.data.status} />
          </p>
          <table className="w-full text-sm">
            <caption className="mb-1 text-left font-medium">Evidence</caption>
            <tbody>
              {flag.data.evidence.map((t) => (
                <tr key={t.id} className="border-t border-[var(--line)]">
                  <td className="py-1">{formatDate(t.txn_date)}</td>
                  <td className="py-1">{t.narration}</td>
                  <td className="py-1 text-right">{t.direction === "credit" ? "+" : "−"}<Money paise={t.amount_paise} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {flag.data.status === "open" ? (
            <form className="flex flex-col gap-3" onSubmit={(e) => e.preventDefault()}>
              <Field label="Note (required)">
                <textarea className={inputClass} required minLength={3} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button variant="danger" disabled={note.trim().length < 3 || resolve.isPending} onClick={() => resolve.mutate("confirmed")}>Confirm</Button>
                <Button variant="secondary" disabled={note.trim().length < 3 || resolve.isPending} onClick={() => resolve.mutate("dismissed")}>Dismiss</Button>
              </div>
              {resolve.isError && <ErrorBox error={resolve.error} />}
            </form>
          ) : (
            <p className="text-sm">Resolved: {flag.data.resolution_note}</p>
          )}
        </>
      )}
    </div>
  );
}

function Queue() {
  const business = useSearchParams().get("business");
  const [status, setStatus] = useState<Status>("open");
  const [open, setOpen] = useState<number | null>(null);
  const flags = useQuery({
    queryKey: ["flags", status, business],
    queryFn: async () =>
      unwrap(await api.GET("/v1/flags", {
        params: { query: { status, limit: 100, ...(business ? { business_id: Number(business) } : {}) } },
      })),
  });
  // Biggest amounts first: that's where an officer's time matters most.
  const items = [...(flags.data?.items ?? [])].sort((a, b) => b.total_paise - a.total_paise);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between">
        <h1 className="text-2xl font-semibold">Review queue</h1>
        <Field label="Status">
          <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as Status)}>
            <option value="open">open</option><option value="confirmed">confirmed</option><option value="dismissed">dismissed</option>
          </select>
        </Field>
      </div>
      <Card>
        {flags.isPending && <Loading />}
        {flags.isError && <ErrorBox error={flags.error} />}
        {flags.data && items.length === 0 && <Empty>Nothing here.</Empty>}
        <ul className="divide-y divide-[var(--line)]">
          {items.map((f) => (
            <li key={f.id}>
              <button className="flex w-full items-center gap-4 py-3 text-left hover:bg-slate-50" onClick={() => setOpen(f.id)}>
                <span className="w-32 text-right font-medium"><Money paise={f.total_paise} whole /></span>
                <span className="flex-1 text-sm">{f.summary}</span>
                <span className="text-xs text-[var(--muted)]">{f.kind.replace(/_/g, " ")}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {open !== null && <Drawer flagId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

export default function FlagsPage() {
  return (
    <RequireRole roles={["officer", "admin"]}>
      <Suspense fallback={<Loading />}>
        <Queue />
      </Suspense>
    </RequireRole>
  );
}
