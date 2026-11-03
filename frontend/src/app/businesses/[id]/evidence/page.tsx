"use client";

import { useQuery } from "@tanstack/react-query";
import type { Core } from "cytoscape";
import { use, useEffect, useMemo, useRef, useState } from "react";

import { RequireRole } from "@/components/guards";
import { Card, Empty, ErrorBox, Field, inputClass, Loading, Money } from "@/components/ui";
import { api, unwrap, type Schemas } from "@/lib/api";
import { formatDate } from "@/lib/money";

type Graph = Schemas["GraphOut"];
type Edge = Graph["edges"][number];

function cycleEdges(graph: Graph): Set<string> {
  const keys = new Set<string>();
  for (const cycle of graph.cycles) {
    cycle.forEach((node, i) => keys.add(`${node}->${cycle[(i + 1) % cycle.length]}`));
  }
  return keys;
}

const MAX_COUNTERPARTIES = 20;

/** Keep the graph readable: every account, every node on a cycle, and the counterparties with
 * the largest total flow. A month of UPI sales can have a hundred one-off customers. */
function focus(graph: Graph): { graph: Graph; hidden: number } {
  const onCycle = new Set(graph.cycles.flat());
  const flow = new Map<string, number>();
  for (const e of graph.edges) {
    flow.set(e.from, (flow.get(e.from) ?? 0) + e.total_paise);
    flow.set(e.to, (flow.get(e.to) ?? 0) + e.total_paise);
  }
  const counterparties = graph.nodes.filter((n) => n.kind === "counterparty");
  const top = new Set(
    [...counterparties].sort((a, b) => (flow.get(b.id) ?? 0) - (flow.get(a.id) ?? 0)).slice(0, MAX_COUNTERPARTIES).map((n) => n.id),
  );
  const keep = new Set(graph.nodes.filter((n) => n.kind === "account" || onCycle.has(n.id) || top.has(n.id)).map((n) => n.id));
  return {
    graph: { ...graph, nodes: graph.nodes.filter((n) => keep.has(n.id)), edges: graph.edges.filter((e) => keep.has(e.from) && keep.has(e.to)) },
    hidden: graph.nodes.length - keep.size,
  };
}

function GraphCanvas({ graph, onSelect }: { graph: Graph; onSelect: (edge: Edge) => void }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cy: Core | undefined;
    let cancelled = false;
    void (async () => {
      const cytoscape = (await import("cytoscape")).default;  // browser-only library
      if (cancelled || !container.current) return;
      const inCycle = cycleEdges(graph);
      const max = Math.max(1, ...graph.edges.map((e) => e.total_paise));
      cy = cytoscape({
        container: container.current,
        elements: [
          ...graph.nodes.map((n) => ({ data: { id: n.id, label: n.label, kind: n.kind } })),
          ...graph.edges.map((e, i) => ({
            data: {
              id: `e${i}`, source: e.from, target: e.to, index: i,
              width: 1 + 7 * Math.sqrt(e.total_paise / max),
              cycle: inCycle.has(`${e.from}->${e.to}`) ? 1 : 0,
            },
          })),
        ],
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)", "font-size": 9, color: "#334155", "background-color": "#94a3b8",
              width: 14, height: 14, "text-valign": "bottom", "text-margin-y": 3,
              "text-max-width": "90px", "text-wrap": "ellipsis",
            },
          },
          {
            selector: "node[kind = 'account']",
            style: { shape: "round-rectangle", "background-color": "#1f6f5b", width: 34, height: 24, "font-size": 11, "font-weight": "bold", color: "#1f6f5b" },
          },
          { selector: "edge", style: { width: "data(width)", "curve-style": "bezier", "target-arrow-shape": "triangle", "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1", opacity: 0.8 } },
          { selector: "edge[cycle = 1]", style: { "line-color": "#b4405c", "target-arrow-color": "#b4405c", opacity: 1 } },
        ],
        // Accounts in the middle, counterparties in rings around them.
        layout: {
          name: "concentric", animate: false, minNodeSpacing: 28,
          concentric: (node) => (node.data("kind") === "account" ? 2 : 1), levelWidth: () => 1,
        },
      });
      cy.on("tap", "edge", (event) => {
        const edge = graph.edges[event.target.data("index") as number];
        if (edge) onSelect(edge);
      });
    })();
    return () => {
      cancelled = true;
      cy?.destroy();
    };
  }, [graph, onSelect]);
  return <div ref={container} className="h-[28rem] w-full rounded border border-[var(--line)]" aria-label="Money-flow graph" role="img" />;
}

function Evidence({ businessId }: { businessId: number }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selected, setSelected] = useState<Edge | null>(null);
  const window = { ...(from ? { from } : {}), ...(to ? { to } : {}) };
  const graph = useQuery({
    queryKey: ["graph", businessId, window],
    queryFn: async () => unwrap(await api.GET("/v1/businesses/{business_id}/graph", { params: { path: { business_id: businessId }, query: window } })),
  });
  // The rows behind the window's edges, to list when an edge is clicked.
  const rows = useQuery({
    queryKey: ["graph-rows", businessId, graph.data?.window],
    enabled: !!graph.data,
    queryFn: async () => {
      const all: Schemas["TransactionOut"][] = [];
      let cursor: string | null = null;
      for (let page = 0; page < 10; page++) {
        const result: Schemas["Page_TransactionOut_"] = unwrap(await api.GET("/v1/businesses/{business_id}/transactions", {
          params: { path: { business_id: businessId }, query: { from: graph.data!.window.from, to: graph.data!.window.to, limit: 100, cursor } },
        }));
        all.push(...result.items);
        cursor = result.next_cursor;
        if (!cursor) break;
      }
      return new Map(all.map((t) => [t.id, t]));
    },
  });
  const onSelect = useMemo(() => (edge: Edge) => setSelected(edge), []);
  const focused = useMemo(() => (graph.data ? focus(graph.data) : null), [graph.data]);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Evidence graph</h1>
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="From"><input type="date" className={inputClass} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="To"><input type="date" className={inputClass} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          {graph.data && (
            <p className="text-sm text-[var(--muted)]">
              Showing {formatDate(graph.data.window.from)} – {formatDate(graph.data.window.to)} · accounts are green boxes ·{" "}
              <span className="text-[var(--unresolved)]">red edges</span> are on a flagged cycle
            </p>
          )}
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <Card>
          {graph.isPending && <Loading />}
          {graph.isError && <ErrorBox error={graph.error} />}
          {graph.data && graph.data.edges.length === 0 && <Empty>No money flows with known counterparties in this window.</Empty>}
          {focused && focused.graph.edges.length > 0 && (
            <>
              <GraphCanvas graph={focused.graph} onSelect={onSelect} />
              {focused.hidden > 0 && (
                <p className="mt-2 text-xs text-[var(--muted)]">
                  Showing the {MAX_COUNTERPARTIES} counterparties with the largest flows and everything on a cycle; {focused.hidden} smaller
                  ones are hidden.
                </p>
              )}
            </>
          )}
        </Card>
        <Card title={selected ? "Transactions on this edge" : "Click an edge"}>
          {selected && (
            <>
              <p className="mb-2 text-sm">
                {selected.from} → {selected.to}: <Money paise={selected.total_paise} />
              </p>
              <ul className="divide-y divide-[var(--line)] text-sm">
                {selected.txn_ids.map((id) => {
                  const t = rows.data?.get(id);
                  return (
                    <li key={id} className="py-1">
                      {t ? <>{formatDate(t.txn_date)} · <Money paise={t.amount_paise} /> · {t.narration}</> : `txn ${id}`}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function EvidencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireRole roles={["officer", "admin"]}>
      <Evidence businessId={Number(id)} />
    </RequireRole>
  );
}
