"use client";

import { motion } from "framer-motion";
import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { KronosForecast } from "@/lib/types";
import { fadeIn } from "@/lib/motion";

const HORIZONS: KronosForecast["forecast_horizon"][] = ["7d", "30d", "90d"];

const DIRECTION_COLOR: Record<string, string> = {
  bullish: "#059669",
  neutral: "#94a3b8",
  bearish: "#dc2626",
};

// Only stocks that reached the council loop get all 3 horizons (Phase 0B
// #4) -- a symbol you land on directly may have just the 30d entry. Missing
// slots render as a muted "not forecast" placeholder bar rather than being
// omitted, so the 3-slot layout stays stable and honest about what's absent.
export default function KronosHorizonChart({ horizons }: { horizons: KronosForecast[] }) {
  const bySlot = new Map(horizons.map((h) => [h.forecast_horizon, h]));
  const data = HORIZONS.map((h) => {
    const f = bySlot.get(h);
    const predicted_return_pct = f ? f.predicted_return * 100 : 0;
    return {
      horizon: h,
      predicted_return_pct,
      // ErrorBar wants [lower_delta, upper_delta] relative to the bar value.
      band: f ? [predicted_return_pct - f.predicted_return_p10 * 100, f.predicted_return_p90 * 100 - predicted_return_pct] : [0, 0],
      direction: f?.direction ?? null,
      confidence: f?.confidence ?? null,
      sample_count: f?.sample_count ?? null,
      available: !!f,
    };
  });

  if (horizons.length === 0) {
    return <p className="text-sm text-text-muted">No forecast available for this stock yet.</p>;
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={fadeIn} style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ left: 8, right: 16, top: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240)" vertical={false} />
          <XAxis dataKey="horizon" tick={{ fontSize: 12, fill: "rgb(100 116 139)" }} stroke="rgb(226 232 240)" />
          <YAxis tick={{ fontSize: 11, fill: "rgb(100 116 139)" }} stroke="rgb(226 232 240)" width={44} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
          <Tooltip
            formatter={(_v: number, _n: string, item: { payload?: (typeof data)[number] }) => {
              const d = item.payload;
              if (!d?.available) return ["Not forecast", "Predicted return"];
              const confidenceLabel = d.confidence == null ? "not yet calibrated" : `${(d.confidence * 100).toFixed(0)}% confidence`;
              return [
                `${d.predicted_return_pct.toFixed(1)}% (${d.direction}, ${confidenceLabel}, ${d.sample_count} samples)`,
                "Predicted return (median, p10-p90 band)",
              ];
            }}
          />
          <Bar dataKey="predicted_return_pct" radius={[4, 4, 0, 0]} animationDuration={500}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.available ? DIRECTION_COLOR[d.direction ?? "neutral"] : "rgb(226 232 240)"} />
            ))}
            <ErrorBar dataKey="band" width={4} strokeWidth={1.5} stroke="rgb(71 85 105)" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-text-muted">
        Bar = median of sampled forecasts; whiskers = 10th-90th percentile range.{" "}
        {data.some((d) => d.available && d.confidence == null) && "Confidence not yet calibrated for this model version -- shown as evidence only, excluded from scoring."}
      </p>
    </motion.div>
  );
}
