"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, ApiError } from "@/lib/api";
import type { AllocateOut, PortfolioOut, RiskProfile } from "@/lib/types";
import { useApiData } from "@/lib/useApiData";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import StatCard from "@/components/ui/StatCard";
import Card from "@/components/ui/Card";
import { SkeletonCard } from "@/components/ui/Skeleton";
import ProgressBar from "@/components/ui/ProgressBar";
import AllocationDonut from "@/components/charts/AllocationDonut";
import EmptyState from "@/components/ui/EmptyState";
import { FileSearch } from "lucide-react";

function formatRupees(n: number): string {
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function PortfolioInner() {
  const { data: portfolio, error, reload } = useApiData<PortfolioOut>("/api/portfolio/latest");

  const [amount, setAmount] = useState<number | "">("");
  const [allocation, setAllocation] = useState<AllocateOut | null>(null);
  const [allocError, setAllocError] = useState<string | null>(null);

  useEffect(() => {
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [reload]);

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

  if (error) return <p className="text-sm text-text-muted">{error}</p>;
  if (!portfolio) {
    return (
      <div className="grid gap-4 sm:grid-cols-3">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (!portfolio.has_allocation) {
    return (
      <motion.div initial="hidden" animate="visible" variants={fadeInUp}>
        <EmptyState
          icon={FileSearch}
          title="No current allocation"
          message={portfolio.reason ?? "The latest analysis run did not produce a portfolio allocation."}
        />
      </motion.div>
    );
  }

  const allocations = Object.entries(portfolio.allocations).sort((a, b) => b[1] - a[1]);
  const byRupeeSymbol = new Map((allocation?.allocations ?? []).map((a) => [a.symbol, a]));

  const sectorWeights: Record<string, number> = {};
  for (const [symbol, weight] of Object.entries(portfolio.allocations)) {
    const sector = portfolio.sectors[symbol] ?? "Unknown";
    sectorWeights[sector] = (sectorWeights[sector] ?? 0) + weight;
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.h1 variants={fadeInUp} className="text-xl font-semibold text-text-primary">
        Portfolio
      </motion.h1>

      <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Expected return" value={portfolio.expected_return != null ? `${(portfolio.expected_return * 100).toFixed(1)}%` : "UNKNOWN"} />
        <StatCard label="Expected volatility" value={portfolio.expected_volatility != null ? `${(portfolio.expected_volatility * 100).toFixed(1)}%` : "UNKNOWN"} />
        <StatCard label="Sharpe ratio" value={portfolio.sharpe != null ? portfolio.sharpe.toFixed(2) : "UNKNOWN"} />
      </motion.div>

      {portfolio.method !== "mean_variance" && (
        <motion.div variants={fadeInUp} className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {portfolio.method === "equal_weight_fallback" &&
            "The mean-variance solver couldn't find a valid allocation for this candidate set (often too few candidates, or a covariance matrix it judged degenerate) -- this is an equal-weight split instead. Expected return/volatility/Sharpe are UNKNOWN because no real optimization ran, not because of missing data."}
          {portfolio.method === "mean_variance_min_volatility_fallback" &&
            "The solver couldn't maximize Sharpe ratio for this candidate set (e.g. no candidate's expected return exceeds the risk-free rate) -- this allocation minimizes volatility instead."}
          {portfolio.method === "single_candidate" &&
            "Only one candidate passed screening this run -- nothing to optimize a mix across."}
        </motion.div>
      )}

      <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-2">
        <Card title={`Suggested allocation (${portfolio.method.replace(/_/g, " ")})`}>
          <div className="space-y-2">
            {allocations.map(([symbol, weight]) => (
              <ProgressBar key={symbol} label={symbol} value={weight * 100} />
            ))}
            {portfolio.unallocated_cash > 0.001 && (
              <ProgressBar label="Cash (unallocated)" value={portfolio.unallocated_cash * 100} />
            )}
          </div>
        </Card>
        <Card title="Allocation breakdown">
          <AllocationDonut allocations={portfolio.allocations} />
        </Card>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="Sector concentration">
          <p className="mb-3 text-sm text-text-muted">
            How the suggested allocation splits across sectors — a big single slice flags concentration risk.
          </p>
          {Object.keys(sectorWeights).length === allocations.length && allocations.length > 1 && (
            <p className="mb-3 text-xs text-text-muted">
              Every held stock is in a different sector this run, so this looks identical to the per-stock chart above
              — that&apos;s a real result, not a bug, but it means sector overlap isn&apos;t reducing this
              allocation&apos;s diversification any further than the stock count already does.
            </p>
          )}
          <AllocationDonut allocations={sectorWeights} />
        </Card>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="How much do you want to invest?">
          <p className="mb-3 text-sm text-text-muted">
            Splits your amount across the suggested allocation, in whole shares at the latest known price.
          </p>
          <label className="mb-4 block max-w-xs text-sm text-text-primary">
            Investment amount (₹)
            <input
              type="number"
              min={0}
              value={amount}
              onChange={(e) => setAmount(e.target.value === "" ? "" : Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            />
          </label>

          {allocError && <p className="text-sm text-negative">{allocError}</p>}

          {allocation && (
            <div className="space-y-3">
              <div tabIndex={0} className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-text-muted">
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
                        <tr key={symbol} className="border-b border-border last:border-0">
                          <td className="py-1 pr-4 font-medium text-text-primary">{symbol}</td>
                          <td className="py-1 pr-4 text-text-muted">{row ? `${(row.weight * 100).toFixed(1)}%` : "-"}</td>
                          <td className="py-1 pr-4 text-text-muted">{row ? formatRupees(row.rupee_amount) : "-"}</td>
                          <td className="py-1 pr-4 text-text-muted">{row?.shares ?? "-"}</td>
                          <td className="py-1 text-text-muted">{row?.last_price ? formatRupees(row.last_price) : "unknown"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-sm text-text-muted">
                Total allocated: {formatRupees(allocation.total_allocated)} · Leftover cash (doesn&apos;t divide into
                whole shares, or NSE doesn&apos;t deliver fractional shares): {formatRupees(allocation.cash_remainder)}
              </p>
            </div>
          )}
        </Card>
      </motion.div>
    </motion.div>
  );
}

export default function PortfolioPage() {
  return <PortfolioInner />;
}
