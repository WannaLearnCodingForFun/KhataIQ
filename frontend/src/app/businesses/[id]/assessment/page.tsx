"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { use, useState } from "react";

import { RequireRole } from "@/components/guards";
import { Button, Card, Empty, ErrorBox, Field, inputClass, Loading, StatusPill } from "@/components/ui";
import { api, unwrap, type Schemas } from "@/lib/api";

type Status = Schemas["AssessmentStatus"];
const verbs: Record<Status, string> = { draft: "Back to draft", in_review: "Send for review", approved: "Approve", rejected: "Reject" };

function Detail({ assessmentId }: { assessmentId: number }) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const assessment = useQuery({
    queryKey: ["assessment", assessmentId],
    queryFn: async () => unwrap(await api.GET("/v1/assessments/{assessment_id}", { params: { path: { assessment_id: assessmentId } } })),
  });
  const move = useMutation({
    mutationFn: async (to: Status) =>
      unwrap(await api.POST("/v1/assessments/{assessment_id}/transitions", {
        params: { path: { assessment_id: assessmentId } }, body: { to, note: note || null },
      })),
    onSuccess: () => {
      setNote("");
      void client.invalidateQueries({ queryKey: ["assessment", assessmentId] });
      void client.invalidateQueries({ queryKey: ["assessments"] });
    },
  });
  if (assessment.isPending) return <Loading />;
  if (assessment.isError) return <ErrorBox error={assessment.error} />;
  const a = assessment.data;
  return (
    <Card title={`Assessment #${a.id}`} actions={<StatusPill status={a.status} />}>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Based on metric run {a.metric_run_id ?? "–"}. This records a human decision; KhataIQ does not score borrowers.
      </p>
      {a.allowed_transitions.length > 0 ? (
        <div className="flex flex-col gap-3">
          <Field label="Note">
            <textarea className={inputClass} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            {a.allowed_transitions.map((to) => (
              <Button key={to} variant={to === "rejected" ? "danger" : to === "draft" ? "secondary" : "primary"} disabled={move.isPending} onClick={() => move.mutate(to)}>
                {verbs[to]}
              </Button>
            ))}
          </div>
          {move.isError && <ErrorBox error={move.error} />}
        </div>
      ) : (
        <p className="text-sm">Final: {a.status}{a.note ? ` — ${a.note}` : ""}.</p>
      )}
      <h3 className="mb-1 mt-5 text-sm font-semibold">History</h3>
      <ol className="text-sm">
        {a.history.map((h, i) => (
          <li key={i} className="border-t border-[var(--line)] py-1">
            {new Date(h.at).toLocaleString("en-IN")} · {h.action.replace("assessment.", "")}
            {h.after && typeof h.after["status"] === "string" ? ` → ${h.after["status"]}` : ""}
            {h.after && typeof h.after["note"] === "string" && h.after["note"] ? ` (“${h.after["note"]}”)` : ""}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Assessments({ businessId }: { businessId: number }) {
  const client = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["assessments", businessId],
    queryFn: async () => unwrap(await api.GET("/v1/businesses/{business_id}/assessments", { params: { path: { business_id: businessId } } })),
  });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/v1/businesses/{business_id}/assessments", { params: { path: { business_id: businessId } }, body: {} })),
    onSuccess: (a) => {
      setSelected(a.id);
      void client.invalidateQueries({ queryKey: ["assessments", businessId] });
    },
  });
  const current = selected ?? list.data?.[0]?.id ?? null;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Assessment</h1>
        <Button onClick={() => create.mutate()} disabled={create.isPending}>New assessment</Button>
      </div>
      {list.isPending && <Loading />}
      {list.isError && <ErrorBox error={list.error} />}
      {list.data && list.data.length === 0 && <Empty>No assessments yet.</Empty>}
      {list.data && list.data.length > 1 && (
        <Field label="Assessment">
          <select className={inputClass} value={current ?? ""} onChange={(e) => setSelected(Number(e.target.value))}>
            {list.data.map((a) => <option key={a.id} value={a.id}>#{a.id} · {a.status}</option>)}
          </select>
        </Field>
      )}
      {current !== null && <Detail assessmentId={current} />}
    </div>
  );
}

export default function AssessmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireRole roles={["officer", "admin"]}>
      <Assessments businessId={Number(id)} />
    </RequireRole>
  );
}
