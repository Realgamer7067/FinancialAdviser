"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { CouncilRunSummary, RiskProfile } from "@/lib/types";
import { tierFitsProfile } from "@/lib/riskTiers";
import RecommendationBadge from "@/components/RecommendationBadge";
import RiskTierBadge from "@/components/RiskTierBadge";
import ProgressBar from "@/components/ui/ProgressBar";

function RecommendationsInner() {
  const [run, setRun] = useState<CouncilRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [userRiskProfile, setUserRiskProfile] = useState<string | null>(null);

  useEffect(() => {
    const load = () => {
      api
        .get<CouncilRunSummary>("/api/recommendations/latest")
        .then(setRun)
        .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load recommendations"));
    };
    load();
    // Refetch on refocus -- a rerun triggered from another tab would otherwise
    // leave this tab showing a stale council run indefinitely.
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, []);

  useEffect(() => {
    // Best-effort: a missing risk profile just means we skip the "fits your
    // profile" hint, not a page-level error.
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then((p) => setUserRiskProfile(p.risk_profile))
      .catch(() => setUserRiskProfile(null));
  }, []);

  if (error) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-slate-600">{error}</p>
        <Link href="/dashboard" className="text-sm text-brand-700 underline">
          Go run an analysis from the dashboard
        </Link>
      </div>
    );
  }
  if (!run) return <p className="text-sm text-slate-500">Loading...</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Recommendations</h1>
        <p className="text-sm text-slate-500">
          Market regime: <span className="capitalize">{run.market_regime.replace(/_/g, " ")}</span> · screened{" "}
          {run.universe_size} stocks down to {run.candidates_to_council} for full review.
        </p>
      </div>

      {run.recommendations.length === 0 && (
        <p className="text-sm text-slate-600">No candidates were generated in this run.</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {run.recommendations.map((rec) => {
          const fits = tierFitsProfile(rec.risk_tier, userRiskProfile);
          return (
            <Link
              key={rec.id}
              href={`/stocks/${rec.symbol}`}
              className="block rounded border bg-white p-4 hover:border-brand-600"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold">{rec.symbol}</p>
                  <p className="text-xs text-slate-500">{rec.name}</p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <RecommendationBadge value={rec.recommendation} />
                  <RiskTierBadge value={rec.risk_tier} />
                </div>
              </div>

              <div className="mt-3 space-y-1.5">
                <ProgressBar label="Score" value={rec.score} displayValue={`${rec.score.toFixed(0)}/100`} />
                <ProgressBar label="Confidence" value={rec.confidence * 100} />
                <ProgressBar label="Model agreement" value={rec.model_agreement * 100} colorClass="bg-sky-500" />
                <ProgressBar label="Data quality" value={rec.data_quality * 100} colorClass="bg-sky-500" />
              </div>

              <p className="mt-2 text-xs text-slate-500">Horizon: {rec.suggested_horizon}</p>
              {fits && <p className="mt-1 text-xs font-medium text-brand-700">✓ Fits your risk profile</p>}
              {rec.strengths.length > 0 && <p className="mt-2 text-sm text-slate-700">✓ {rec.strengths[0]}</p>}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function RecommendationsPage() {
  return <RecommendationsInner />;
}
