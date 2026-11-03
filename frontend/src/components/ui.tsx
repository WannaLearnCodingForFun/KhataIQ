"use client";

import { ApiError, type Schemas } from "@/lib/api";
import { formatPaise } from "@/lib/money";

export function Card({ title, children, actions }: { title?: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-[var(--line)] bg-white p-4 shadow-sm">
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary: "bg-[var(--brand)] text-white hover:opacity-90",
    secondary: "border border-[var(--line)] bg-white hover:bg-slate-50",
    danger: "bg-[var(--unresolved)] text-white hover:opacity-90",
  }[variant];
  return (
    <button
      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-[var(--muted)]">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "rounded-md border border-[var(--line)] bg-white px-2 py-1.5 text-sm focus:border-[var(--brand)]";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="py-6 text-center text-sm text-[var(--muted)]">
      {label}
    </p>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-center text-sm text-[var(--muted)]">{children}</p>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const requestId = error instanceof ApiError ? error.problem.request_id : null;
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      {message}
      {requestId && <span className="ml-2 text-xs text-red-600">(request {requestId})</span>}
    </div>
  );
}

type Level = Schemas["EvidenceLevel"];
const levelStyle: Record<Level, string> = {
  verified: "bg-emerald-50 text-[var(--verified)] border-emerald-200",
  inferred: "bg-amber-50 text-[var(--inferred)] border-amber-200",
  unresolved: "bg-rose-50 text-[var(--unresolved)] border-rose-200",
};
const levelHelp: Record<Level, string> = {
  verified: "Verified: both legs are in the ledger and the rule is fully met",
  inferred: "Inferred: one leg only, supported by named evidence in the row",
  unresolved: "Unresolved: more than one explanation fits; needs review",
};

export function LevelChip({ level }: { level: Level }) {
  return (
    <span title={levelHelp[level]} className={`inline-block rounded border px-1.5 py-0.5 text-xs ${levelStyle[level]}`}>
      {level}
    </span>
  );
}

/** An amount; if it came from evidence, its level shows on hover (spec: frontend rules). */
export function Money({ paise, level, whole }: { paise: number; level?: Level | null; whole?: boolean }) {
  return (
    <span className="tabular-nums" title={level ? levelHelp[level] : undefined}>
      {formatPaise(paise, { whole })}
    </span>
  );
}

const statusStyle: Record<string, string> = {
  processed: "bg-emerald-50 text-emerald-800",
  reconciled: "bg-emerald-50 text-emerald-800",
  succeeded: "bg-emerald-50 text-emerald-800",
  needs_review: "bg-amber-50 text-amber-800",
  failed: "bg-rose-50 text-rose-800",
  dead: "bg-rose-50 text-rose-800",
  open: "bg-amber-50 text-amber-800",
  confirmed: "bg-rose-50 text-rose-800",
  dismissed: "bg-slate-100 text-slate-700",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusStyle[status] ?? "bg-slate-100 text-slate-700"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
