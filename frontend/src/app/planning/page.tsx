"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { GoalSipOut, RiskProfile, SipProjectionOut } from "@/lib/types";
import StatCard from "@/components/ui/StatCard";
import Button from "@/components/ui/Button";
import SipGrowthChart from "@/components/charts/SipGrowthChart";

function formatRupees(n: number): string {
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function PlanningInner() {
  const [monthlyAmount, setMonthlyAmount] = useState<number | "">("");
  const [years, setYears] = useState<number | "">("");
  const [rateInput, setRateInput] = useState<number | "">("");
  const [rateTouched, setRateTouched] = useState(false);
  const [projection, setProjection] = useState<SipProjectionOut | null>(null);
  const [projectionError, setProjectionError] = useState<string | null>(null);

  const [goalAmount, setGoalAmount] = useState<number | "">("");
  const [goalYears, setGoalYears] = useState<number | "">("");
  const [goalResult, setGoalResult] = useState<GoalSipOut | null>(null);
  const [goalError, setGoalError] = useState<string | null>(null);
  const [goalLoading, setGoalLoading] = useState(false);

  useEffect(() => {
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then((p) => {
        setMonthlyAmount(p.monthly_contribution);
        setYears(p.investment_horizon_years);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (monthlyAmount === "" || years === "" || monthlyAmount <= 0 || years <= 0) {
      setProjection(null);
      return;
    }
    const params = new URLSearchParams({ monthly_amount: String(monthlyAmount), years: String(years) });
    if (rateTouched && rateInput !== "") params.set("annual_rate_pct", String(rateInput));

    const timer = setTimeout(() => {
      api
        .get<SipProjectionOut>(`/api/planning/sip-projection?${params}`)
        .then((res) => {
          setProjection(res);
          setProjectionError(null);
          if (!rateTouched) setRateInput(res.annual_rate_pct);
        })
        .catch((err) => setProjectionError(err instanceof ApiError ? err.message : "Failed to compute projection"));
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monthlyAmount, years, rateInput, rateTouched]);

  async function onGoalSubmit(e: FormEvent) {
    e.preventDefault();
    if (goalAmount === "" || goalYears === "") return;
    setGoalLoading(true);
    setGoalError(null);
    try {
      const res = await api.post<GoalSipOut>("/api/planning/goal-sip", {
        target_amount: goalAmount,
        years: goalYears,
      });
      setGoalResult(res);
    } catch (err) {
      setGoalError(err instanceof ApiError ? err.message : "Failed to compute goal SIP");
    } finally {
      setGoalLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Planner</h1>

      <div className="rounded border bg-white p-4">
        <h2 className="mb-1 font-medium">SIP growth projection</h2>
        <p className="mb-3 text-sm text-slate-500">
          How a monthly investment could grow over time, compounded annually.
        </p>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <label className="text-sm">
            Monthly amount (₹)
            <input
              type="number"
              min={0}
              value={monthlyAmount}
              onChange={(e) => setMonthlyAmount(e.target.value === "" ? "" : Number(e.target.value))}
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Years
            <input
              type="number"
              min={1}
              value={years}
              onChange={(e) => setYears(e.target.value === "" ? "" : Number(e.target.value))}
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Assumed annual return (%)
            <input
              type="number"
              step={0.1}
              value={rateInput}
              onChange={(e) => {
                setRateTouched(true);
                setRateInput(e.target.value === "" ? "" : Number(e.target.value));
              }}
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </label>
        </div>

        {projectionError && <p className="text-sm text-red-600">{projectionError}</p>}

        {projection && (
          <div className="space-y-2">
            <p className="text-xs text-slate-500">
              {projection.assumed_return
                ? "No portfolio result yet -- this uses a general, non-guaranteed assumed rate. Not a promise of returns."
                : "Rate based on your latest portfolio's own expected return (or your override) -- still an estimate, not a guarantee."}
            </p>
            <SipGrowthChart points={projection.points} />
            <div className="grid gap-4 sm:grid-cols-2">
              <StatCard
                label="Total invested"
                value={formatRupees(projection.points[projection.points.length - 1].invested_cumulative)}
              />
              <StatCard
                label="Projected value"
                value={formatRupees(projection.points[projection.points.length - 1].projected_value)}
              />
            </div>
          </div>
        )}
      </div>

      <div className="rounded border bg-white p-4">
        <h2 className="mb-1 font-medium">Goal calculator</h2>
        <p className="mb-3 text-sm text-slate-500">How much to invest monthly to reach a target amount.</p>
        <form onSubmit={onGoalSubmit} className="grid gap-3 sm:grid-cols-3">
          <label className="text-sm">
            Target amount (₹)
            <input
              type="number"
              min={0}
              required
              value={goalAmount}
              onChange={(e) => setGoalAmount(e.target.value === "" ? "" : Number(e.target.value))}
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Years
            <input
              type="number"
              min={1}
              required
              value={goalYears}
              onChange={(e) => setGoalYears(e.target.value === "" ? "" : Number(e.target.value))}
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </label>
          <div className="flex items-end">
            <Button disabled={goalLoading} type="submit" className="w-full">
              {goalLoading ? "Computing..." : "Calculate"}
            </Button>
          </div>
        </form>

        {goalError && <p className="mt-2 text-sm text-red-600">{goalError}</p>}

        {goalResult && (
          <div className="mt-4 space-y-1">
            <StatCard label="Required monthly SIP" value={formatRupees(goalResult.required_monthly_sip)} />
            <p className="text-xs text-slate-500">
              Assumes {goalResult.annual_rate_pct.toFixed(1)}% annual return
              {goalResult.assumed_return ? " (general assumption, not a promise)" : " (from your latest portfolio)"}.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function PlanningPage() {
  return <PlanningInner />;
}
