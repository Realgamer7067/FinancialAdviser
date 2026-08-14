"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { PortfolioOut } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";

function PortfolioInner() {
  const [portfolio, setPortfolio] = useState<PortfolioOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PortfolioOut>("/api/portfolio/latest")
      .then(setPortfolio)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load portfolio"));
  }, []);

  if (error) return <p className="text-sm text-slate-600">{error}</p>;
  if (!portfolio) return <p className="text-sm text-slate-500">Loading...</p>;

  const allocations = Object.entries(portfolio.allocations).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Portfolio</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Expected return" value={portfolio.expected_return ? `${(portfolio.expected_return * 100).toFixed(1)}%` : "UNKNOWN"} />
        <Stat label="Expected volatility" value={portfolio.expected_volatility ? `${(portfolio.expected_volatility * 100).toFixed(1)}%` : "UNKNOWN"} />
        <Stat label="Sharpe ratio" value={portfolio.sharpe ? portfolio.sharpe.toFixed(2) : "UNKNOWN"} />
      </div>

      <div className="rounded border bg-white p-4">
        <h2 className="mb-3 font-medium">Suggested allocation ({portfolio.method.replace(/_/g, " ")})</h2>
        <div className="space-y-2">
          {allocations.map(([symbol, weight]) => (
            <div key={symbol} className="flex items-center gap-3">
              <span className="w-24 text-sm font-medium">{symbol}</span>
              <div className="h-2 flex-1 rounded bg-slate-100">
                <div className="h-2 rounded bg-brand-600" style={{ width: `${Math.min(weight * 100, 100)}%` }} />
              </div>
              <span className="w-14 text-right text-sm text-slate-600">{(weight * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

export default function PortfolioPage() {
  return (
    <RequireAuth>
      <PortfolioInner />
    </RequireAuth>
  );
}
