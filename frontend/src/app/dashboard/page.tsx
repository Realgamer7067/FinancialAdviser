"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { AlertCircle, ArrowRight, Info } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DashboardOut, JobStatus } from "@/lib/types";
import { useApiData } from "@/lib/useApiData";
import { useJobPolling } from "@/lib/useJobPolling";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import StatCard from "@/components/ui/StatCard";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { SkeletonCard } from "@/components/ui/Skeleton";
import AnalysisProgress from "@/components/AnalysisProgress";
import { useState } from "react";

function DashboardInner() {
  const { data, error, reload } = useApiData<DashboardOut>("/api/dashboard");
  const { job, setJob, pollError } = useJobPolling(null, reload);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const running = job !== null && job.status !== "done" && job.status !== "failed";

  async function triggerAnalysis() {
    setTriggerError(null);
    try {
      const created = await api.post<JobStatus>("/api/recommendations/jobs");
      setJob(created);
    } catch (err) {
      setTriggerError(err instanceof ApiError ? err.message : "Could not start analysis");
    }
  }

  if (error) return <p className="text-sm text-negative">{error}</p>;
  if (!data) {
    return (
      <div className="grid gap-4 sm:grid-cols-3">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.h1 variants={fadeInUp} className="text-xl font-semibold text-text-primary">
        Dashboard
      </motion.h1>

      <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-3">
        <StatCard label="NSE market status" value={data.market_status} />
        <StatCard
          label="NIFTY 50"
          value={data.nifty_price ? data.nifty_price.toFixed(0) : "--"}
          hint={data.nifty_is_stale ? "cached — due for refresh" : "cached — up to date"}
        />
        <StatCard label="Your risk profile" value={data.risk_profile ? data.risk_profile : "Not set"} />
      </motion.div>

      {!data.has_profile && (
        <motion.div variants={fadeInUp} className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-subtle p-4 text-sm text-warning">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Finish your <Link href="/onboarding" className="underline">investor profile</Link> to get personalized
            recommendations.
          </p>
        </motion.div>
      )}

      {(data.risk_profile === "conservative" || data.risk_profile === "moderate") && (
        <motion.div variants={fadeInUp}>
          <Card>
            <p className="flex items-center gap-2 text-sm text-text-primary">
              Prefer lower-risk options?
              <Link href="/safer-alternatives" className="flex items-center gap-1 font-medium text-accent hover:text-accent-hover">
                See safer alternatives <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </p>
          </Card>
        </motion.div>
      )}

      <motion.div variants={fadeInUp}>
        <Card title="Opportunities">
          <p className="text-sm text-text-muted">
            {data.top_recommendation_count > 0
              ? `${data.strong_or_candidate_count} of ${data.top_recommendation_count} analyzed stocks currently fit your profile.`
              : "No analysis run yet."}
          </p>
          <div className="mt-3 flex items-center gap-3">
            <Button onClick={triggerAnalysis} disabled={!data.has_profile || running} loading={running}>
              {running ? "Analyzing..." : "Run analysis"}
            </Button>
            {job?.status === "done" && (
              <Link href="/recommendations" className="flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
                View results <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
          {triggerError && (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-negative">
              <AlertCircle className="h-3.5 w-3.5" /> {triggerError}
            </p>
          )}
          {job?.status === "failed" && (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-negative">
              <AlertCircle className="h-3.5 w-3.5" /> Analysis failed: {job.error}
            </p>
          )}

          {job && running && (
            <div className="mt-4 border-t border-border pt-4">
              <AnalysisProgress job={job} />
              {pollError && (
                <p className="mt-2 flex items-center gap-1.5 text-sm text-warning">
                  <AlertCircle className="h-3.5 w-3.5" /> {pollError}
                </p>
              )}
            </div>
          )}
        </Card>
      </motion.div>
    </motion.div>
  );
}

export default function DashboardPage() {
  return <DashboardInner />;
}
