"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const COLORS = ["#16a34a", "#22c55e", "#4ade80", "#86efac", "#0ea5e9", "#38bdf8", "#f59e0b", "#fbbf24"];

export default function AllocationDonut({ allocations }: { allocations: Record<string, number> }) {
  const data = Object.entries(allocations)
    .sort((a, b) => b[1] - a[1])
    .map(([symbol, weight]) => ({ symbol, weight: weight * 100 }));

  if (data.length === 0) {
    return <p className="text-sm text-slate-400">No allocation to chart.</p>;
  }

  return (
    <div style={{ width: "100%", height: 240 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="weight" nameKey="symbol" innerRadius="55%" outerRadius="90%" paddingAngle={1}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number, name: string) => [`${v.toFixed(1)}%`, name]} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
