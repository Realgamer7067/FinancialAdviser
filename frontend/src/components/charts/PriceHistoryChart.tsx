"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PriceHistoryPoint } from "@/lib/types";

export default function PriceHistoryChart({ points }: { points: PriceHistoryPoint[] }) {
  if (points.length === 0) {
    return <p className="text-sm text-slate-400">No price history available yet.</p>;
  }
  const data = points.map((p) => ({
    date: new Date(p.timestamp).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
    close: p.close,
  }));
  return (
    <div style={{ width: "100%", height: 220 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ left: 8, right: 16, top: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#94a3b8" minTickGap={30} />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 11 }}
            stroke="#94a3b8"
            width={56}
            tickFormatter={(v: number) => `₹${v.toFixed(0)}`}
          />
          <Tooltip formatter={(v: number) => [`₹${v.toFixed(2)}`, "Close"]} />
          <Line type="monotone" dataKey="close" stroke="#16a34a" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
