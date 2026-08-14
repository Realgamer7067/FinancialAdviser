"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { DashboardOut, JobStatus } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";

function DashboardInner() {
  const [data, setData] = useState<DashboardOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);

  async function load() {
    try {
      const d = await api.get<DashboardOut>("/api/dashboard");
      setData(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load dashboard");
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    const t = setTimeout(async () => {
      const updated = await api.get<JobStatus>(`/api/recommendations/jobs/${job.id}`);
      setJob(updated);
      if (updated.status === "done") load();
    }, 3000);
    return () => clearTimeout(t);
  }, [job]);

  async function triggerAnalysis() {
    setError(null);
    try {
      const created = await api.post<JobStatus>("/api/recommendations/jobs");
      setJob(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start analysis");
    }
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading dashboard...</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="NSE market status" value={data.market_status} />
        <StatCard
          label="NIFTY 50"
          value={data.nifty_price ? data.nifty_price.toFixed(0) : "--"}
          hint={data.nifty_is_stale ? "cached / stale" : "live"}
        />
        <StatCard label="Your risk profile" value={data.risk_profile ? data.risk_profile : "Not set"} />
      </div>

      {!data.has_profile && (
        <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm">
          Finish your <Link href="/onboarding" className="underline">investor profile</Link> to get personalized
          recommendations.
        </div>
      )}

      <div className="rounded border bg-white p-4">
        <h2 className="font-medium">Opportunities</h2>
        <p className="mt-1 text-sm text-slate-600">
          {data.top_recommendation_count > 0
            ? `${data.strong_or_candidate_count} of ${data.top_recommendation_count} analyzed stocks currently fit your profile.`
            : "No analysis run yet."}
        </p>
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={triggerAnalysis}
            disabled={!data.has_profile || (job !== null && job.status !== "done" && job.status !== "failed")}
            className="rounded bg-brand-600 px-4 py-2 text-sm text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {job && job.status !== "done" && job.status !== "failed" ? "Analyzing..." : "Run analysis"}
          </button>
          {job?.status === "done" && (
            <Link href="/recommendations" className="text-sm text-brand-700 underline">
              View results
            </Link>
          )}
          {job?.status === "failed" && <span className="text-sm text-red-600">Analysis failed: {job.error}</span>}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded border bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold capitalize">{value}</p>
      {hint && <p className="text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardInner />
    </RequireAuth>
  );
}
