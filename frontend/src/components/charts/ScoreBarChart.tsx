"use client";

import { motion } from "framer-motion";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { fadeIn } from "@/lib/motion";

export interface ScoreBarChartEntry {
  label: string;
  value: number;
}

// Bar chart, not radar: recharts' RadarChart renders a missing axis as zero,
// which would visually lie about a genuinely-absent subscore -- a bar chart
// can simply omit a row for a null value (caller filters those out).
export default function ScoreBarChart({ entries }: { entries: ScoreBarChartEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-text-muted">No sub-scores available.</p>;
  }
  return (
    <motion.div initial="hidden" animate="visible" variants={fadeIn} style={{ width: "100%", height: entries.length * 36 + 20 }}>
      <ResponsiveContainer>
        <BarChart data={entries} layout="vertical" margin={{ left: 16, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240)" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 12, fill: "rgb(100 116 139)" }} stroke="rgb(226 232 240)" />
          <YAxis type="category" dataKey="label" width={90} tick={{ fontSize: 12, fill: "rgb(100 116 139)" }} stroke="rgb(226 232 240)" />
          <Bar dataKey="value" fill="rgb(79 70 229)" radius={[0, 4, 4, 0]} animationDuration={500} />
        </BarChart>
      </ResponsiveContainer>
    </motion.div>
  );
}
