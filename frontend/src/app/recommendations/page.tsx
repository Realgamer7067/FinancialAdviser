"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Check, FileSearch } from "lucide-react";
import { api } from "@/lib/api";
import type { CouncilRunSummary, RiskProfile } from "@/lib/types";
import { tierFitsProfile } from "@/lib/riskTiers";
import { useApiData } from "@/lib/useApiData";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import RecommendationBadge from "@/components/RecommendationBadge";
import RiskTierBadge from "@/components/RiskTierBadge";
import ProgressBar from "@/components/ui/ProgressBar";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";
import ScreeningFunnelChart from "@/components/charts/ScreeningFunnelChart";

function RecommendationsInner() {
  const { data: run, error, reload } = useApiData<CouncilRunSummary>("/api/recommendations/latest");
  const [userRiskProfile, setUserRiskProfile] = useState<string | null>(null);

  useEffect(() => {
    // Refetch on refocus -- a rerun triggered from another tab would otherwise
    // leave this tab showing a stale council run indefinitely.
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [reload]);

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
      <EmptyState
        icon={FileSearch}
        title="No recommendations yet"
        message={error}
        action={{ href: "/dashboard", label: "Go run an analysis from the dashboard" }}
      />
    );
  }
  if (!run) {
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Recommendations</h1>
        <p className="text-sm text-text-muted">
          Market regime: <span className="capitalize">{run.market_regime.replace(/_/g, " ")}</span> · screened{" "}
          {run.universe_size} stocks down to {run.candidates_to_council} for full review.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="Screening funnel">
          <ScreeningFunnelChart
            universeSize={run.universe_size}
            afterScreen={run.candidates_after_screen}
            afterKronosNews={run.candidates_after_kronos_news}
            toCouncil={run.candidates_to_council}
          />
        </Card>
      </motion.div>

      {run.recommendations.length === 0 && (
        <motion.div variants={fadeInUp}>
          <EmptyState icon={FileSearch} title="No candidates were generated in this run" />
        </motion.div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {run.recommendations.map((rec) => {
          const fits = tierFitsProfile(rec.risk_tier, userRiskProfile);
          return (
            <motion.div key={rec.id} variants={fadeInUp}>
              <Link href={`/stocks/${rec.symbol}`}>
                <Card interactive className="hover:border-accent/40">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-text-primary">{rec.symbol}</p>
                      <p className="text-xs text-text-muted">{rec.name}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <RecommendationBadge value={rec.recommendation} />
                      <RiskTierBadge value={rec.risk_tier} />
                    </div>
                  </div>

                  <div className="mt-3 space-y-1.5">
                    <ProgressBar label="Score" value={rec.score} displayValue={`${rec.score.toFixed(0)}/100`} />
                    {/* "Confidence" here is 0.5*signal-agreement + 0.5*evidence-coverage --
                        a deterministic heuristic, not a calibrated probability of being
                        right (docs/V2-RETHINK.md P1). Its two components are broken out
                        below with names that say what they actually measure. */}
                    <ProgressBar label="Confidence (heuristic)" value={rec.confidence * 100} />
                    <ProgressBar label="Signal agreement" value={rec.model_agreement * 100} colorClass="bg-sky-500" />
                    <ProgressBar label="Evidence coverage" value={rec.data_quality * 100} colorClass="bg-sky-500" />
                  </div>

                  <p className="mt-2 text-xs text-text-muted">Horizon: {rec.suggested_horizon}</p>
                  {fits && (
                    <p className="mt-1 flex items-center gap-1 text-xs font-medium text-accent">
                      <Check className="h-3 w-3" /> Fits your risk profile
                    </p>
                  )}
                  {rec.strengths.length > 0 && (
                    <p className="mt-2 flex items-start gap-1 text-sm text-text-primary">
                      <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive" /> {rec.strengths[0]}
                    </p>
                  )}
                </Card>
              </Link>
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
}

export default function RecommendationsPage() {
  return <RecommendationsInner />;
}
