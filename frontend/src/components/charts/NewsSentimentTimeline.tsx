"use client";

import { motion } from "framer-motion";
import { CartesianGrid, Cell, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import type { NewsArticle } from "@/lib/types";
import { fadeIn } from "@/lib/motion";

// Per-article sentiment (already fetched for the flat article list before
// this) plotted over time -- no backend change needed, purely a frontend
// free win the same way ScreeningFunnelChart is.
export default function NewsSentimentTimeline({ articles }: { articles: NewsArticle[] }) {
  if (articles.length === 0) {
    return <p className="text-sm text-text-muted">No recent news found for this stock.</p>;
  }

  const data = articles.map((a) => ({
    x: new Date(a.published_at).getTime(),
    y: a.sentiment,
    z: Math.max(a.confidence, 0.2) * 100,
    title: a.title,
    source: a.source,
    event_type: a.event_type,
    date: new Date(a.published_at).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
  }));

  return (
    <motion.div initial="hidden" animate="visible" variants={fadeIn} style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240)" />
          <XAxis
            dataKey="x"
            type="number"
            domain={["auto", "auto"]}
            tickFormatter={(v: number) => new Date(v).toLocaleDateString("en-IN", { month: "short", day: "numeric" })}
            tick={{ fontSize: 11, fill: "rgb(100 116 139)" }}
            stroke="rgb(226 232 240)"
          />
          <YAxis dataKey="y" domain={[-1, 1]} tick={{ fontSize: 11, fill: "rgb(100 116 139)" }} stroke="rgb(226 232 240)" width={36} />
          <ZAxis dataKey="z" range={[40, 160]} />
          <Tooltip
            formatter={(_v, _n, item: { payload?: (typeof data)[number] }) => {
              const d = item.payload;
              if (!d) return "";
              return [`${d.title} (${d.source}, ${d.event_type})`, ""];
            }}
          />
          <Scatter data={data} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.y >= 0.1 ? "#059669" : d.y <= -0.1 ? "#dc2626" : "#94a3b8"} fillOpacity={0.75} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </motion.div>
  );
}
