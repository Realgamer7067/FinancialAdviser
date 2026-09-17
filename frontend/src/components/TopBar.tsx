"use client";

import { usePathname } from "next/navigation";
import { Database } from "lucide-react";

const TITLES: { prefix: string; label: string }[] = [
  { prefix: "/dashboard", label: "Dashboard" },
  { prefix: "/recommendations", label: "Recommendations" },
  { prefix: "/portfolio", label: "Portfolio" },
  { prefix: "/holdings", label: "Holdings" },
  { prefix: "/goals", label: "Goals" },
  { prefix: "/catalogue", label: "Product Catalogue" },
  { prefix: "/compare", label: "Compare" },
  { prefix: "/planning", label: "Planner" },
  { prefix: "/research", label: "Research" },
  { prefix: "/safer-alternatives", label: "Safer Options" },
  { prefix: "/settings", label: "Settings" },
  { prefix: "/onboarding", label: "Onboarding" },
  { prefix: "/stocks", label: "Stock Detail" },
  { prefix: "/admin", label: "Admin / Debug" },
];

function titleFor(pathname: string): string {
  return TITLES.find((t) => pathname.startsWith(t.prefix))?.label ?? "Indian Equity Research";
}

// No live/streaming data anywhere in this app -- market data, fundamentals,
// and news are all fetched on a schedule and cached (TrueData is a one-time
// historical cache, not a live feed). This badge says so plainly rather than
// implying real-time freshness anywhere in the shell.
export default function TopBar() {
  const pathname = usePathname();
  return (
    <div className="hidden items-center justify-between border-b border-border bg-surface px-6 py-3 sm:flex">
      <h2 className="text-sm font-medium text-text-primary">{titleFor(pathname)}</h2>
      <span className="flex items-center gap-1.5 rounded-full bg-bg px-2.5 py-1 text-xs text-text-muted">
        <Database className="h-3 w-3" />
        Cached market data
      </span>
    </div>
  );
}
