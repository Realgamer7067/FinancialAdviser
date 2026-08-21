"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AllocateOut, PortfolioOut, RiskProfile } from "@/lib/types";
import StatCard from "@/components/ui/StatCard";
import AllocationDonut from "@/components/charts/AllocationDonut";

function formatRupees(n: number): string {
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function PortfolioInner() {
  const [portfolio, setPortfolio] = useState<PortfolioOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [amount, setAmount] = useState<number | "">("");
  const [allocation, setAllocation] = useState<AllocateOut | null>(null);
  const [allocError, setAllocError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => {
      api
        .get<PortfolioOut>("/api/portfolio/latest")
        .then(setPortfolio)
        .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load portfolio"));
    };
    load();
    // Refetch on refocus -- a rerun triggered from another tab would otherwise
    // leave this tab showing stale allocations indefinitely.
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, []);

  // Pre-fill from the amount already given during onboarding, so a returning
  // user sees a rupee breakdown immediately without having to retype it.
  useEffect(() => {
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then((profile) => setAmount(profile.capital))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (amount === "" || amount <= 0) {
      setAllocation(null);
      setAllocError(null);
      return;
    }
    const timer = setTimeout(() => {
      api
        .post<AllocateOut>("/api/portfolio/allocate", { amount })
        .then((res) => {
          setAllocation(res);
          setAllocError(null);
        })
        .catch((err) => setAllocError(err instanceof ApiError ? err.message : "Failed to compute allocation"));
    }, 400);
    return () => clearTimeout(timer);
  }, [amount]);

  if (error) return <p className="text-sm text-slate-600">{error}</p>;
  if (!portfolio) return <p className="text-sm text-slate-500">Loading...</p>;

  const allocations = Object.entries(portfolio.allocations).sort((a, b) => b[1] - a[1]);
  const byRupeeSymbol = new Map((allocation?.allocations ?? []).map((a) => [a.symbol, a]));

  const sectorWeights: Record<string, number> = {};
  for (const [symbol, weight] of Object.entries(portfolio.allocations)) {
    const sector = portfolio.sectors[symbol] ?? "Unknown";
    sectorWeights[sector] = (sectorWeights[sector] ?? 0) + weight;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Portfolio</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Expected return" value={portfolio.expected_return ? `${(portfolio.expected_return * 100).toFixed(1)}%` : "UNKNOWN"} />
        <StatCard label="Expected volatility" value={portfolio.expected_volatility ? `${(portfolio.expected_volatility * 100).toFixed(1)}%` : "UNKNOWN"} />
        <StatCard label="Sharpe ratio" value={portfolio.sharpe ? portfolio.sharpe.toFixed(2) : "UNKNOWN"} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
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
        <div className="rounded border bg-white p-4">
          <h2 className="mb-3 font-medium">Allocation breakdown</h2>
          <AllocationDonut allocations={portfolio.allocations} />
        </div>
      </div>

      <div className="rounded border bg-white p-4">
        <h2 className="mb-1 font-medium">Sector concentration</h2>
        <p className="mb-3 text-sm text-slate-500">
          How the suggested allocation splits across sectors -- a big single slice flags concentration risk.
        </p>
        <AllocationDonut allocations={sectorWeights} />
      </div>

      <div className="rounded border bg-white p-4">
        <h2 className="mb-1 font-medium">How much do you want to invest?</h2>
        <p className="mb-3 text-sm text-slate-500">
          Splits your amount across the suggested allocation, in whole shares at the latest known price.
        </p>
        <label className="mb-4 block max-w-xs text-sm">
          Investment amount (₹)
          <input
            type="number"
            min={0}
            value={amount}
            onChange={(e) => setAmount(e.target.value === "" ? "" : Number(e.target.value))}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </label>

        {allocError && <p className="text-sm text-red-600">{allocError}</p>}

        {allocation && (
          <div className="space-y-3">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-slate-500">
                    <th className="py-1 pr-4">Symbol</th>
                    <th className="py-1 pr-4">Weight</th>
                    <th className="py-1 pr-4">₹ Amount</th>
                    <th className="py-1 pr-4">Shares</th>
                    <th className="py-1">Last price</th>
                  </tr>
                </thead>
                <tbody>
                  {allocations.map(([symbol]) => {
                    const row = byRupeeSymbol.get(symbol);
                    return (
                      <tr key={symbol} className="border-b last:border-0">
                        <td className="py-1 pr-4 font-medium">{symbol}</td>
                        <td className="py-1 pr-4">{row ? `${(row.weight * 100).toFixed(1)}%` : "-"}</td>
                        <td className="py-1 pr-4">{row ? formatRupees(row.rupee_amount) : "-"}</td>
                        <td className="py-1 pr-4">{row?.shares ?? "-"}</td>
                        <td className="py-1">{row?.last_price ? formatRupees(row.last_price) : "unknown"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-sm text-slate-600">
              Total allocated: {formatRupees(allocation.total_allocated)} · Leftover cash (doesn&apos;t divide into
              whole shares, or NSE doesn&apos;t deliver fractional shares): {formatRupees(allocation.cash_remainder)}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function PortfolioPage() {
  return <PortfolioInner />;
}
