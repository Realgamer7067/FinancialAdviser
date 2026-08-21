"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SipProjectionPoint } from "@/lib/types";

export default function SipGrowthChart({ points }: { points: SipProjectionPoint[] }) {
  if (points.length === 0) {
    return <p className="text-sm text-slate-400">No projection to chart yet.</p>;
  }
  const data = points.map((p) => ({
    year: `Y${p.year}`,
    invested: p.invested_cumulative,
    projected: p.projected_value,
  }));
  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ left: 8, right: 16, top: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="year" tick={{ fontSize: 11 }} stroke="#94a3b8" />
          <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" width={64} tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`} />
          <Tooltip formatter={(v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="invested" name="Invested" stroke="#94a3b8" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="projected" name="Projected value" stroke="#0ea5e9" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
