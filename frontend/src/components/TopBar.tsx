"use client";

import { usePathname } from "next/navigation";
import { ShieldCheck } from "lucide-react";

const TITLES: { prefix: string; label: string }[] = [
  { prefix: "/overview", label: "Overview" },
  { prefix: "/actions", label: "Portfolio review" },
  { prefix: "/inbox", label: "Attention" },
  { prefix: "/theses", label: "Investment rationales" },
  { prefix: "/dashboard", label: "Market & old analysis" },
  { prefix: "/recommendations", label: "Earlier stock candidates" },
  { prefix: "/portfolio", label: "Earlier candidate portfolio" },
  { prefix: "/holdings", label: "Holdings" },
  { prefix: "/data", label: "Data freshness" },
  { prefix: "/market", label: "Market" },
  { prefix: "/allocate", label: "Plan new investment" },
  { prefix: "/watchlist", label: "Watchlists" },
  { prefix: "/scorecard", label: "Model evidence" },
  { prefix: "/risk", label: "Risk & exposure" },
  { prefix: "/simulate", label: "Compare a change" },
  { prefix: "/finances", label: "Financial profile" },
  { prefix: "/goals", label: "Earlier goals" },
  { prefix: "/catalogue", label: "Product Catalogue" },
  { prefix: "/compare", label: "Compare stocks" },
  { prefix: "/planning", label: "Calculators" },
  { prefix: "/plan", label: "Goals & SIPs" }, // after /planning: prefix match
  { prefix: "/research", label: "Research" },
  { prefix: "/safer-alternatives", label: "Safer options" },
  { prefix: "/settings", label: "Settings" },
  { prefix: "/onboarding", label: "Earlier investor questionnaire" },
  { prefix: "/stocks", label: "Stock Detail" },
  { prefix: "/admin", label: "Admin / Debug" },
];

function titleFor(pathname: string): string {
  return TITLES.find((t) => pathname.startsWith(t.prefix))?.label ?? "Portfolio Intelligence";
}

// The shell makes one claim only: nothing here places orders. Each page states the date of its own data
// (prices, holdings, review), because they differ.
export default function TopBar() {
  const pathname = usePathname();
  return (
    <header className="hidden items-center justify-between border-b border-border bg-surface px-6 py-3 sm:flex">
      {/* Not a heading: each page owns its single h1. */}
      <p className="text-sm font-medium text-text-primary">{titleFor(pathname)}</p>
      <span className="flex items-center gap-1.5 rounded-full bg-bg px-2.5 py-1 text-xs text-text-muted">
        <ShieldCheck aria-hidden className="h-3 w-3" />
        Read-only · no orders
      </span>
    </header>
  );
}
