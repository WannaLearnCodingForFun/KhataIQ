"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";

import { RequireRole } from "@/components/guards";
import { Button, Card, ErrorBox, Field, inputClass, Loading, Money, StatusPill } from "@/components/ui";
import { api, ApiError, authFetch, unwrap, type Schemas } from "@/lib/api";

type Upload = Schemas["UploadOut"];
const FINAL = new Set(["processed", "needs_review", "failed"]);

async function postStatement(accountId: number, file: File): Promise<{ upload: Upload; duplicate: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const response = await authFetch(`/v1/accounts/${accountId}/uploads`, {
    method: "POST",
    body: form,
    // A fresh key per file: a retried request (e.g. a flaky network) can't create a duplicate.
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
  const body: unknown = await response.json();
  if (!response.ok) throw new ApiError(response.status, body as ApiError["problem"]);
  // 201 = a new upload; 200 = this exact file was uploaded before (or a replayed request).
  return { upload: body as Upload, duplicate: response.status === 200 };
}

function Progress({ uploadId, businessId }: { uploadId: number; businessId: number }) {
  const client = useQueryClient();
  const status = useQuery({
    queryKey: ["upload", uploadId],
    queryFn: async () => unwrap(await api.GET("/v1/uploads/{upload_id}", { params: { path: { upload_id: uploadId } } })),
    refetchInterval: (query) => (query.state.data && FINAL.has(query.state.data.status) ? false : 2_000),
  });
  // Once the pipeline is done, everything derived from the ledger may have changed.
  const finished = status.data !== undefined && FINAL.has(status.data.status);
  useEffect(() => {
    if (!finished) return;
    for (const key of ["metrics", "uploads", "transactions", "graph"]) {
      void client.invalidateQueries({ queryKey: [key, businessId] });
    }
    void client.invalidateQueries({ queryKey: ["flags"] });
  }, [finished, businessId, client]);
  if (status.isPending) return <Loading label="Waiting for the pipeline…" />;
  if (status.isError) return <ErrorBox error={status.error} />;
  const u = status.data;
  return (
    <div aria-live="polite" className="flex flex-col gap-3 text-sm">
      <p>
        Upload #{u.id}: <StatusPill status={u.status} />
      </p>
      <ol className="flex flex-wrap gap-2">
        {u.stages.map((s) => (
          <li key={s.stage} className="flex items-center gap-1 rounded border border-[var(--line)] px-2 py-1">
            {s.stage} <StatusPill status={s.status} />
            {s.attempts > 1 && <span className="text-xs text-[var(--muted)]">×{s.attempts}</span>}
          </li>
        ))}
      </ol>
      {u.recon && (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3">
          The statement doesn&apos;t add up{" "}
          {u.recon.break_line !== null ? <>at <strong>line {u.recon.break_line}</strong></> : "at the closing balance"}: expected{" "}
          <Money paise={u.recon.expected_paise ?? 0} />, the statement shows <Money paise={u.recon.actual_paise ?? 0} />. Nothing after
          reconciliation ran; an officer will review it.
        </div>
      )}
      {u.error && <ErrorBox error={new Error(u.error)} />}
    </div>
  );
}

function AddAccount({ businessId }: { businessId: number }) {
  const client = useQueryClient();
  const parsers = useQuery({ queryKey: ["parsers"], queryFn: async () => unwrap(await api.GET("/v1/parsers")) });
  const [choice, setChoice] = useState("demo|csv");
  const [number, setNumber] = useState("");
  const add = useMutation({
    mutationFn: async () => {
      const [bank = "", format = ""] = choice.split("|");
      return unwrap(
        await api.POST("/v1/businesses/{business_id}/accounts", {
          params: { path: { business_id: businessId } },
          body: { bank, format, account_number: number, type: "current" },
        }),
      );
    },
    onSuccess: () => {
      setNumber("");
      void client.invalidateQueries({ queryKey: ["business", businessId] });
    },
  });
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
      <Field label="Bank and format">
        <select className={inputClass} value={choice} onChange={(e) => setChoice(e.target.value)}>
          {parsers.data?.map((p) => (
            <option key={`${p.bank}|${p.format}`} value={`${p.bank}|${p.format}`}>
              {p.bank} ({p.format})
            </option>
          ))}
        </select>
      </Field>
      <Field label="Account number (only the last 4 digits are stored)">
        <input className={inputClass} inputMode="numeric" required value={number} onChange={(e) => setNumber(e.target.value)} />
      </Field>
      <Button type="submit" variant="secondary" disabled={add.isPending}>
        Add account
      </Button>
      {add.isError && <ErrorBox error={add.error} />}
    </form>
  );
}

function UploadForm({ businessId }: { businessId: number }) {
  const business = useQuery({
    queryKey: ["business", businessId],
    queryFn: async () => unwrap(await api.GET("/v1/businesses/{business_id}", { params: { path: { business_id: businessId } } })),
  });
  const [accountId, setAccountId] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadId, setUploadId] = useState<number | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const send = useMutation({
    mutationFn: async (file: File) => postStatement(accountId ?? business.data?.accounts[0]?.id ?? 0, file),
    onSuccess: ({ upload, duplicate: seenBefore }) => {
      setDuplicate(seenBefore);
      setUploadId(upload.id);
    },
  });

  function pick(files: FileList | null) {
    const file = files?.[0];
    if (file) send.mutate(file);
  }

  if (business.isPending) return <Loading />;
  if (business.isError) return <ErrorBox error={business.error} />;
  const accounts = business.data.accounts;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Upload a statement · {business.data.name}</h1>
      <Card title="Accounts">
        <AddAccount businessId={businessId} />
      </Card>
      <Card title="Statement">
        {accounts.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">Add an account first.</p>
        ) : (
          <div className="flex flex-col gap-4">
            <Field label="Account">
              <select className={inputClass} value={accountId ?? accounts[0]?.id} onChange={(e) => setAccountId(Number(e.target.value))}>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.bank} ••{a.account_mask} ({a.format})
                  </option>
                ))}
              </select>
            </Field>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files); }}
              className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-sm ${dragging ? "border-[var(--brand)] bg-emerald-50" : "border-[var(--line)]"}`}
            >
              <p>Drop a CSV or PDF statement here (10 MB max), or</p>
              <Button type="button" variant="secondary" onClick={() => fileInput.current?.click()} disabled={send.isPending}>
                Choose a file
              </Button>
              <input ref={fileInput} type="file" accept=".csv,.pdf,text/csv,application/pdf" className="sr-only" aria-label="Statement file" onChange={(e) => pick(e.target.files)} />
            </div>
            {send.isPending && <Loading label="Uploading…" />}
            {send.isError && <ErrorBox error={send.error} />}
            {duplicate && <p className="text-sm">This file was already uploaded; showing the existing upload.</p>}
            {uploadId !== null && <Progress uploadId={uploadId} businessId={businessId} />}
          </div>
        )}
      </Card>
      <Link className="text-sm underline" href={`/businesses/${businessId}`}>
        Back to overview
      </Link>
    </div>
  );
}

export default function UploadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireRole roles={["owner"]}>
      <UploadForm businessId={Number(id)} />
    </RequireRole>
  );
}
