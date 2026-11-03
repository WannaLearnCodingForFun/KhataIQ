"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { RequireRole } from "@/components/guards";
import { Button, Card, Empty, ErrorBox, Field, inputClass, Loading } from "@/components/ui";
import { api, unwrap } from "@/lib/api";

function DeadLetters() {
  const client = useQueryClient();
  const dead = useQuery({ queryKey: ["dead-letters"], queryFn: async () => unwrap(await api.GET("/v1/admin/dead-letters")) });
  const retry = useMutation({
    mutationFn: async (runId: number) => unwrap(await api.POST("/v1/admin/dead-letters/{run_id}/retry", { params: { path: { run_id: runId } } })),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["dead-letters"] }),
  });
  return (
    <Card title="Dead letters">
      {dead.isPending && <Loading />}
      {dead.isError && <ErrorBox error={dead.error} />}
      {dead.data && dead.data.items.length === 0 && <Empty>No failed pipeline stages.</Empty>}
      <ul className="divide-y divide-[var(--line)] text-sm">
        {dead.data?.items.map((d) => (
          <li key={d.run_id} className="flex items-center gap-4 py-2">
            <span>Upload #{d.upload_id} · {d.stage} · attempt {d.attempt_no}</span>
            <span className="flex-1 truncate text-[var(--muted)]" title={d.error ?? ""}>{d.error}</span>
            <Button variant="secondary" disabled={retry.isPending} onClick={() => retry.mutate(d.run_id)}>Retry</Button>
          </li>
        ))}
      </ul>
      {retry.isError && <ErrorBox error={retry.error} />}
    </Card>
  );
}

function Audit() {
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");
  const query = { ...(entityType ? { entity_type: entityType } : {}), ...(entityId ? { entity_id: Number(entityId) } : {}), limit: 100 };
  const audit = useQuery({ queryKey: ["audit", query], queryFn: async () => unwrap(await api.GET("/v1/admin/audit", { params: { query } })) });
  return (
    <Card title="Audit log">
      <div className="mb-3 flex gap-3">
        <Field label="Entity type">
          <select className={inputClass} value={entityType} onChange={(e) => setEntityType(e.target.value)}>
            <option value="">any</option>
            {["upload", "business", "account", "flag", "assessment", "transaction", "user", "pipeline_run"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Entity id">
          <input className={inputClass} inputMode="numeric" value={entityId} onChange={(e) => setEntityId(e.target.value.replace(/\D/g, ""))} />
        </Field>
      </div>
      {audit.isPending && <Loading />}
      {audit.isError && <ErrorBox error={audit.error} />}
      <table className="w-full text-sm">
        <thead className="text-left text-[var(--muted)]">
          <tr><th>When</th><th>Action</th><th>Entity</th><th>Actor</th><th>Request</th></tr>
        </thead>
        <tbody>
          {audit.data?.items.map((a) => (
            <tr key={a.id} className="border-t border-[var(--line)]">
              <td className="py-1">{new Date(a.at).toLocaleString("en-IN")}</td>
              <td className="py-1">{a.action}</td>
              <td className="py-1">{a.entity_type} {a.entity_id ?? ""}</td>
              <td className="py-1">{a.actor_id ?? "system"}</td>
              <td className="py-1 font-mono text-xs">{a.request_id?.slice(0, 8)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function AdminPage() {
  return (
    <RequireRole roles={["admin"]}>
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-semibold">Admin</h1>
        <DeadLetters />
        <Audit />
      </div>
    </RequireRole>
  );
}
