"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { RequireRole } from "@/components/guards";
import { Button, Card, Empty, ErrorBox, Field, inputClass, Loading } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/money";

function BusinessList() {
  const { me } = useAuth();
  const businesses = useQuery({
    queryKey: ["businesses"],
    queryFn: async () => unwrap(await api.GET("/v1/businesses", { params: { query: { limit: 100 } } })),
  });
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Businesses</h1>
      {me?.role === "owner" && <CreateBusiness />}
      <Card>
        {businesses.isPending && <Loading />}
        {businesses.isError && <ErrorBox error={businesses.error} />}
        {businesses.data && businesses.data.items.length === 0 && (
          <Empty>No businesses yet{me?.role === "owner" ? " — add your first one above." : "."}</Empty>
        )}
        {businesses.data && businesses.data.items.length > 0 && (
          <ul className="divide-y divide-[var(--line)]">
            {businesses.data.items.map((b) => (
              <li key={b.id}>
                <Link href={`/businesses/${b.id}`} className="flex items-center justify-between py-3 hover:bg-slate-50">
                  <span className="font-medium">{b.name}</span>
                  <span className="text-sm text-[var(--muted)]">
                    {b.category} · since {formatDate(b.created_at.slice(0, 10))}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function CreateBusiness() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [category, setCategory] = useState("kirana");
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/v1/businesses", { body: { name, category } })),
    onSuccess: () => {
      setName("");
      void client.invalidateQueries({ queryKey: ["businesses"] });
    },
  });
  return (
    <Card title="Add a business">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Name">
          <input className={inputClass} required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Category">
          <select className={inputClass} value={category} onChange={(e) => setCategory(e.target.value)}>
            {["kirana", "pharmacy", "salon", "hardware", "tiffin", "other"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Button type="submit" disabled={create.isPending}>
          Add
        </Button>
      </form>
      {create.isError && <div className="mt-3"><ErrorBox error={create.error} /></div>}
    </Card>
  );
}

export default function BusinessesPage() {
  return (
    <RequireRole>
      <BusinessList />
    </RequireRole>
  );
}
