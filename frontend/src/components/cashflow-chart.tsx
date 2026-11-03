"use client";

import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/lib/api";
import { formatMonth, formatPaise } from "@/lib/money";

type Month = Schemas["MonthOut"];

/** Net business inflow as a line, the uncertain amount as a band above it, gross inflow as
 * faint bars. Values are converted to rupees only for plotting; labels use formatPaise. */
export function CashflowChart({ months }: { months: Month[] }) {
  const data = months.map((m) => ({
    month: formatMonth(m.month),
    gross: m.gross_inflow_paise / 100,
    net: m.net_business_inflow_paise / 100,
    band: [m.net_business_inflow_paise / 100, (m.net_business_inflow_paise + m.uncertain_paise) / 100],
    raw: m,
  }));
  return (
    <div className="h-72 w-full" aria-hidden="true">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e3e7ee" />
          <XAxis dataKey="month" fontSize={12} />
          <YAxis fontSize={12} tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`} width={56} />
          <Tooltip
            formatter={(value, name, item) => {
              const m = (item.payload as { raw: Month }).raw;
              if (name === "Uncertain") return [formatPaise(m.uncertain_paise), "Uncertain"];
              if (name === "Net business inflow") return [formatPaise(m.net_business_inflow_paise), name];
              return [formatPaise(m.gross_inflow_paise), name];
            }}
          />
          <Legend />
          {/* No animation: the numbers are the point, and it respects reduced-motion users. */}
          <Bar dataKey="gross" name="Gross inflow" fill="#cbd5e1" fillOpacity={0.5} isAnimationActive={false} />
          <Area dataKey="band" name="Uncertain" stroke="none" fill="#b7791f" fillOpacity={0.25} isAnimationActive={false} />
          <Line dataKey="net" name="Net business inflow" stroke="#1f6f5b" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
