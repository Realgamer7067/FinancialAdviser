"use client";

import { motion } from "framer-motion";
import { fadeIn, staggerChildren } from "@/lib/motion";

// The 4-stage narrowing (universe -> screen -> kronos/news -> council) was
// already on CouncilRunSummary and only ever rendered as one sentence before
// this -- no backend change needed, purely a frontend free win.
export default function ScreeningFunnelChart({
  universeSize,
  afterScreen,
  afterKronosNews,
  toCouncil,
}: {
  universeSize: number;
  afterScreen: number;
  afterKronosNews: number;
  toCouncil: number;
}) {
  const stages = [
    { label: "Nifty50 universe", value: universeSize },
    { label: "Passed fundamental/technical screen", value: afterScreen },
    { label: "Ranked after forecast + news", value: afterKronosNews },
    { label: "Sent to council", value: toCouncil },
  ];
  const max = universeSize || 1;

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-2">
      {stages.map((s) => (
        <motion.div key={s.label} variants={fadeIn} className="flex items-center gap-3">
          <span className="w-56 shrink-0 text-sm text-text-muted">{s.label}</span>
          <div className="h-3 flex-1 overflow-hidden rounded-full bg-border/40">
            <motion.div
              className="h-3 rounded-full bg-accent"
              initial={{ width: 0 }}
              animate={{ width: `${Math.max((s.value / max) * 100, 2)}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
          <span className="w-8 shrink-0 text-right text-sm font-medium text-text-primary">{s.value}</span>
        </motion.div>
      ))}
    </motion.div>
  );
}
