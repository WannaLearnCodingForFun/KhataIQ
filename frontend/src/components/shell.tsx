"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isOfficer, useAuth } from "@/lib/auth";

export function Shell({ children }: { children: React.ReactNode }) {
  const { me, logout } = useAuth();
  const pathname = usePathname();
  const links = [
    { href: "/businesses", label: "Businesses", show: !!me },
    { href: "/flags", label: "Review queue", show: isOfficer(me?.role) },
    { href: "/admin", label: "Admin", show: me?.role === "admin" },
  ].filter((l) => l.show);
  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--line)] bg-white">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
          <Link href="/businesses" className="font-semibold text-[var(--brand)]">
            KhataIQ
          </Link>
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              aria-current={pathname.startsWith(l.href) ? "page" : undefined}
              className="text-sm text-[var(--muted)] hover:text-[var(--ink)] aria-[current=page]:font-semibold aria-[current=page]:text-[var(--ink)]"
            >
              {l.label}
            </Link>
          ))}
          {me && (
            <div className="ml-auto flex items-center gap-3 text-sm">
              <span className="text-[var(--muted)]">
                {me.email} · {me.role}
              </span>
              <button onClick={() => void logout()} className="underline">
                Sign out
              </button>
            </div>
          )}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
