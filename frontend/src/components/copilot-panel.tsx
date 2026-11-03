"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { api, unwrap, type Schemas } from "@/lib/api";

import { Button, ErrorBox, inputClass } from "./ui";

type Exchange = { question: string; reply: Schemas["CopilotOut"] };

/** Side panel on business pages (officers). Citations link to the transaction or month. */
export function CopilotPanel({ businessId }: { businessId: number }) {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<Exchange[]>([]);
  const conversationId = history.at(-1)?.reply.conversation_id ?? null;
  const ask = useMutation({
    mutationFn: async (q: string) =>
      unwrap(
        await api.POST("/v1/businesses/{business_id}/copilot", {
          params: { path: { business_id: businessId } },
          body: { question: q, conversation_id: conversationId },
        }),
      ),
    onSuccess: (reply, q) => {
      setHistory((h) => [...h, { question: q, reply }]);
      setQuestion("");
    },
  });

  return (
    <aside aria-label="Copilot" className="flex flex-col gap-3 rounded-lg border border-[var(--line)] bg-white p-4">
      <h2 className="font-semibold">Ask about this business</h2>
      <p className="text-xs text-[var(--muted)]">
        Answers use only this business&apos;s data; every figure is checked against the rows it cites.
      </p>
      <ol className="flex max-h-96 flex-col gap-3 overflow-y-auto text-sm" aria-live="polite">
        {history.map((x, i) => (
          <li key={i} className="flex flex-col gap-1">
            <p className="font-medium">{x.question}</p>
            <p className={x.reply.grounded ? "" : "text-[var(--muted)]"}>{x.reply.answer}</p>
            {x.reply.citations.length > 0 && (
              <p className="flex flex-wrap gap-1 text-xs">
                {x.reply.citations.map((c) => (
                  <Link
                    key={`${c.type}-${c.id}`}
                    className="rounded bg-slate-100 px-1.5 py-0.5 underline"
                    href={
                      c.type === "txn"
                        ? `/businesses/${businessId}/transactions#txn-${c.id}`
                        : `/businesses/${businessId}#month-${c.id}`
                    }
                  >
                    {c.type === "txn" ? `txn ${c.id}` : `month ${String(c.id).slice(0, 4)}-${String(c.id).slice(4)}`}
                  </Link>
                ))}
              </p>
            )}
          </li>
        ))}
      </ol>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim()) ask.mutate(question.trim());
        }}
      >
        <label className="sr-only" htmlFor="copilot-q">Question</label>
        <input id="copilot-q" className={`${inputClass} flex-1`} value={question} maxLength={2000} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. How much of October's inflow is uncertain?" />
        <Button type="submit" disabled={ask.isPending}>
          {ask.isPending ? "…" : "Ask"}
        </Button>
      </form>
      {ask.isError && <ErrorBox error={ask.error} />}
    </aside>
  );
}
