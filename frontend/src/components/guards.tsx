"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth, type Role } from "@/lib/auth";

import { Empty, Loading } from "./ui";

/** Renders children only for signed-in users with one of the roles (any role if omitted). */
export function RequireRole({ roles, children }: { roles?: Role[]; children: React.ReactNode }) {
  const { me, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);
  if (loading || !me) return <Loading />;
  if (roles && !roles.includes(me.role)) return <Empty>This page isn&apos;t available for your role.</Empty>;
  return <>{children}</>;
}
