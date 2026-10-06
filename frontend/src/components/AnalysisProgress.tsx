"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";
import clsx from "clsx";
import type { JobStatus } from "@/lib/types";
import ProgressBar from "@/components/ui/ProgressBar";

// Mirrors the STAGE_* constants in backend/app/pipelines/progress.py, in
// pipeline order. A job's `stage` is null while queued and stays at its last
// value if it fails mid-run (deliberately, per the tracker's design) --
// unknown/absent stages are handled by simply not being "reached" below.
const STAGES: { key: string; label: string }[] = [
  { key: "loading_profile", label: "Loading your investor profile" },
  { key: "syncing_instruments", label: "Syncing Nifty50 instrument list" },
  { key: "market_regime", label: "Reading market regime" },
  { key: "fetching_market_data", label: "Fetching price, fundamentals & technicals" },
  { key: "screening", label: "Screening the universe" },
  { key: "news_ingestion", label: "Ingesting news & scoring sentiment" },
  { key: "kronos_forecast", label: "Forecasting price direction (Kronos)" },
  { key: "preliminary_scoring", label: "Ranking candidates" },
  { key: "portfolio_optimization", label: "Optimizing portfolio allocation" },
  { key: "council_setup", label: "Preparing analyst council" },
  { key: "planner", label: "Planning the analysis" },
  { key: "council_evaluation", label: "Running the analyst council" },
  { key: "finalizing", label: "Finalizing recommendations" },
];

function stageDetailText(job: JobStatus): string | null {
  const d = job.stage_detail;
  if (!d || !d.current_symbol) return null;
  if (d.index !== null && d.total !== null) return `${d.current_symbol} (${d.index + 1} of ${d.total})`;
  return d.current_symbol;
}

export default function AnalysisProgress({ job }: { job: JobStatus }) {
  const activeIndex = STAGES.findIndex((s) => s.key === job.stage);
  const pct = job.status === "done" ? 100 : job.progress_pct ?? 0;
  const detail = stageDetailText(job);

  return (
    <div className="space-y-3">
      <ProgressBar label="Overall progress" value={pct} displayValue={`${pct.toFixed(0)}%`} />
      {detail && <p className="pl-[8.5rem] text-xs text-text-muted">{detail}</p>}

      <ol className="mt-2 space-y-1">
        {STAGES.map((s, i) => {
          const done = job.status === "done" || i < activeIndex;
          const active = job.status !== "done" && i === activeIndex;
          return (
            <li key={s.key} className="flex items-center gap-2 text-sm">
              <span
                className={clsx(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
                  done && "bg-positive text-white",
                  active && "bg-accent text-white",
                  !done && !active && "bg-border/60"
                )}
              >
                {done && <Check className="h-3 w-3" />}
                {active && <Loader2 className="h-3 w-3 animate-spin" />}
              </span>
              <AnimatePresence initial={false} mode="wait">
                <motion.span
                  key={active ? "active" : done ? "done" : "pending"}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.2 }}
                  className={clsx(active ? "font-medium text-text-primary" : done ? "text-text-muted" : "text-text-muted/50")}
                >
                  {s.label}
                </motion.span>
              </AnimatePresence>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
