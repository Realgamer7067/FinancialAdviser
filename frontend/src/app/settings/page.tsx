"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { RiskProfile } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import RiskGauge from "@/components/ui/RiskGauge";
import Card from "@/components/ui/Card";
import { Row } from "@/components/ui/Panel";
import { SkeletonCard } from "@/components/ui/Skeleton";

function SettingsInner() {
  const [profile, setProfile] = useState<RiskProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then(setProfile)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load profile"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="max-w-lg space-y-6">
      <motion.h1 variants={fadeInUp} className="text-xl font-semibold text-text-primary">
        Settings
      </motion.h1>

      {loading && <SkeletonCard />}

      {!loading && (
      <motion.div variants={fadeInUp}>
        <Card title="Investor profile">
          {error && <p className="text-sm text-negative">{error}</p>}
          {profile && (
            <div className="mb-4">
              <RiskGauge value={profile.risk_score} label={profile.risk_profile} />
            </div>
          )}
          {profile && (
            <dl className="space-y-1 capitalize">
              <Row label="Risk profile" value={profile.risk_profile} />
              <Row label="Horizon" value={`${profile.investment_horizon_years} years`} />
              <Row label="Capital" value={`₹${profile.capital.toLocaleString("en-IN")}`} />
              <Row label="Monthly contribution" value={`₹${profile.monthly_contribution.toLocaleString("en-IN")}`} />
              <Row label="Objective" value={profile.objective.replace(/_/g, " ")} />
              <Row label="Liquidity need" value={profile.liquidity_requirement} />
            </dl>
          )}
          <Link href="/onboarding" className="mt-4 flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover">
            Update my profile <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </Card>
      </motion.div>
      )}
    </motion.div>
  );
}

export default function SettingsPage() {
  return <SettingsInner />;
}
