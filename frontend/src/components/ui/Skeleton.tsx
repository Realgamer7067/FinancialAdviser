"use client";

import { motion } from "framer-motion";
import clsx from "clsx";

// Card/chart-shaped placeholder blocks, replacing the bare "Loading..." text
// every page used before this (Phase 1 "small details matter" pass).
export default function Skeleton({ className }: { className?: string }) {
  return (
    <motion.div
      className={clsx("rounded-lg bg-border/60", className)}
      animate={{ opacity: [0.5, 1, 0.5] }}
      transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
    />
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={clsx("space-y-3 rounded-lg border border-border bg-surface p-4", className)}>
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-6 w-32" />
      <Skeleton className="h-3 w-40" />
    </div>
  );
}

export function SkeletonChart({ className = "h-64" }: { className?: string }) {
  return <Skeleton className={clsx("w-full", className)} />;
}
