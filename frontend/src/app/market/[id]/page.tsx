"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { V4SecurityDetail } from "@/lib/types";
import Button from "@/components/ui/Button";
import SecurityDetail from "@/components/market/SecurityDetail";
import SecurityActions from "@/components/market/SecurityActions";

const KIND_LABEL: Record<string, string> = { stock: "Stock", etf: "ETF", mutual_fund: "Mutual fund" };

function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

// One durable page per security: the link can be bookmarked or shared with yourself, and Back returns to the list as you left it.
export default function SecurityPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [s, setS] = useState<V4SecurityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tries, setTries] = useState(0);

  useEffect(() => {
    setError(null);
    api.get<V4SecurityDetail>(`/api/v4/catalogue/securities/${id}`).then(setS).catch((e) => setError(e instanceof ApiError ? (e.status === 404 ? "We do not have a security with that link." : e.message) : "Could not load this security"));
  }, [id, tries]);

  const price = s?.price;
  const change = price?.percent_change != null ? Number(price.percent_change) : null;

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/market" className="inline-flex items-center gap-1 text-accent hover:text-accent-hover"><ArrowLeft aria-hidden className="h-3.5 w-3.5" /> Back to Market</Link>
      </nav>

      {error && (
        <div role="alert" className="space-y-2">
          <h1 className="text-xl font-semibold text-text-primary">Security</h1>
          <p className="text-sm text-negative">{error}</p>
          <Button size="sm" variant="secondary" onClick={() => setTries((t) => t + 1)}>Try again</Button>
        </div>
      )}
      {!s && !error && <div aria-busy="true"><h1 className="text-xl font-semibold text-text-primary">Security</h1><p className="text-sm text-text-muted">Loading…</p></div>}

      {s && (
        <>
          <header className="space-y-1">
            <p className="text-xs text-text-muted">{KIND_LABEL[s.kind] ?? s.kind}{s.sector ? ` · ${s.sector}` : ""}{s.category ? ` · ${s.category}` : ""}</p>
            <h1 className="text-2xl font-semibold text-text-primary">{s.symbol ?? s.name}</h1>
            <p className="text-sm text-text-muted">{s.name}</p>
            <p className="text-lg tabular-nums text-text-primary">
              {s.kind === "mutual_fund"
                ? <>NAV {rupees(s.nav)} <span className="text-xs text-text-muted">as of {s.nav_date ?? "unknown date"}</span></>
                : price
                  ? <>{rupees(price.ltp)}{change !== null && <span className={`ml-2 text-sm ${change >= 0 ? "text-positive" : "text-negative"}`}>{change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%</span>}{" "}
                      <span className="text-xs text-text-muted">{price.freshness.replace(/_/g, " ")} · saved {new Date(price.as_of).toLocaleString("en-IN")}</span></>
                  : <span className="text-sm text-text-muted">No saved price for this security.</span>}
            </p>
          </header>
          <SecurityActions s={s} />
          <div className="rounded-lg border border-border bg-surface shadow-sm"><SecurityDetail id={s.id} /></div>
          <p className="text-xs text-text-muted">Descriptions of past data, not recommendations. Prices are from Angel One and funds&apos; NAVs from AMFI; each carries its own date.</p>
        </>
      )}
    </div>
  );
}
