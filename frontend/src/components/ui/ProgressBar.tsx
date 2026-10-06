"use client";

import { motion } from "framer-motion";
import { EASE_OUT } from "@/lib/motion";

export default function ProgressBar({
  label,
  value,
  displayValue,
  colorClass = "bg-accent",
}: {
  label: string;
  value: number; // 0-100
  displayValue?: string;
  colorClass?: string;
}) {
  const clamped = Math.max(0, Math.min(value, 100));
  return (
    <div className="flex items-center gap-3">
      <span className="w-32 shrink-0 text-sm text-text-muted">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-border/60">
        <motion.div
          className={`h-2 rounded-full ${colorClass}`}
          initial={{ width: 0 }}
          animate={{ width: `${clamped}%` }}
          transition={{ duration: 0.5, ease: EASE_OUT }}
        />
      </div>
      <span className="w-12 shrink-0 text-right text-sm text-text-muted">
        {displayValue ?? `${clamped.toFixed(0)}%`}
      </span>
    </div>
  );
}
