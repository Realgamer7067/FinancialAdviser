"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from "recharts";

export interface ScoreBarChartEntry {
  label: string;
  value: number;
}

// Bar chart, not radar: recharts' RadarChart renders a missing axis as zero,
// which would visually lie about a genuinely-absent subscore -- a bar chart
// can simply omit a row for a null value (caller filters those out).
export default function ScoreBarChart({ entries }: { entries: ScoreBarChartEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-slate-400">No sub-scores available.</p>;
  }
  return (
    <div style={{ width: "100%", height: entries.length * 36 + 20 }}>
      <ResponsiveContainer>
        <BarChart data={entries} layout="vertical" margin={{ left: 16, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 12 }} stroke="#94a3b8" />
          <YAxis type="category" dataKey="label" width={90} tick={{ fontSize: 12 }} stroke="#94a3b8" />
          <Bar dataKey="value" fill="#16a34a" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
