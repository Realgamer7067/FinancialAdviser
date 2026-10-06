"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { RiskProfile, SaferAlternativesOut } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import Card from "@/components/ui/Card";
import { SkeletonCard } from "@/components/ui/Skeleton";
import clsx from "clsx";

function SaferAlternativesInner() {
  const [data, setData] = useState<SaferAlternativesOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [userRiskProfile, setUserRiskProfile] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<SaferAlternativesOut>("/api/education/safer-alternatives")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load content"));
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then((p) => setUserRiskProfile(p.risk_profile))
      .catch(() => setUserRiskProfile(null));
  }, []);

  if (error) return <p className="text-sm text-negative">{error}</p>;
  if (!data) {
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  const items = [...data.items].sort((a, b) => {
    const aFits = userRiskProfile !== null && a.suited_risk_profiles.includes(userRiskProfile);
    const bFits = userRiskProfile !== null && b.suited_risk_profiles.includes(userRiskProfile);
    return aFits === bFits ? 0 : aFits ? -1 : 1;
  });

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Safer Alternatives</h1>
        <p className="text-sm text-text-muted">
          Lower-volatility ways to hold money alongside equities — general education, not a live quote.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp} className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-subtle p-4 text-sm text-warning">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>{data.disclaimer}</p>
      </motion.div>

      <div className="grid gap-4 sm:grid-cols-2">
        {items.map((item) => {
          const fits = userRiskProfile !== null && item.suited_risk_profiles.includes(userRiskProfile);
          return (
            <motion.div key={item.key} variants={fadeInUp}>
              <Card className={clsx(fits && "border-accent/50")}>
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-medium text-text-primary">{item.name}</h2>
                  {fits && (
                    <span className="flex shrink-0 items-center gap-1 rounded-full bg-accent-subtle px-2 py-1 text-xs font-medium text-accent">
                      <ShieldCheck className="h-3 w-3" /> Matches your risk profile
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-text-muted">{item.description}</p>
                <dl className="mt-3 space-y-1 text-sm">
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-text-muted">Indicative return</dt>
                    <dd className="text-right text-text-primary">{item.indicative_return_range}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="shrink-0 text-text-muted">Liquidity</dt>
                    <dd className="text-right text-text-primary">{item.liquidity}</dd>
                  </div>
                  {item.typical_lock_in && (
                    <div className="flex justify-between gap-2">
                      <dt className="shrink-0 text-text-muted">Typical lock-in</dt>
                      <dd className="text-right text-text-primary">{item.typical_lock_in}</dd>
                    </div>
                  )}
                </dl>
                <p className="mt-2 text-xs text-text-muted">{item.risk_note}</p>
                {item.eligibility_note && <p className="mt-1 text-xs text-text-muted">{item.eligibility_note}</p>}
              </Card>
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
}

export default function SaferAlternativesPage() {
  return <SaferAlternativesInner />;
}
