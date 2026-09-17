"use client";

import { motion } from "framer-motion";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { fadeIn } from "@/lib/motion";

// Muted multi-series palette -- leads with the indigo accent, through cool
// violets/teals, no neon.
const COLORS = ["#4f46e5", "#7c3aed", "#0d9488", "#0ea5e9", "#059669", "#8b5cf6", "#d97706", "#94a3b8"];

export default function AllocationDonut({ allocations }: { allocations: Record<string, number> }) {
  const data = Object.entries(allocations)
    .sort((a, b) => b[1] - a[1])
    .map(([symbol, weight]) => ({ symbol, weight: weight * 100 }));

  if (data.length === 0) {
    return <p className="text-sm text-text-muted">No allocation to chart.</p>;
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={fadeIn} style={{ width: "100%", height: 240 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="weight" nameKey="symbol" innerRadius="55%" outerRadius="90%" paddingAngle={1} animationDuration={500}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number, name: string) => [`${v.toFixed(1)}%`, name]} />
        </PieChart>
      </ResponsiveContainer>
    </motion.div>
  );
}
