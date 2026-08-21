"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { RiskProfile } from "@/lib/types";
import RiskGauge from "@/components/ui/RiskGauge";

function SettingsInner() {
  const [profile, setProfile] = useState<RiskProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<RiskProfile>("/api/onboarding/me")
      .then(setProfile)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load profile"));
  }, []);

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <div className="rounded border bg-white p-4">
        <h2 className="mb-2 font-medium">Investor profile</h2>
        {error && <p className="text-sm text-slate-500">{error}</p>}
        {profile && (
          <div className="mb-4">
            <RiskGauge value={profile.risk_score} label={profile.risk_profile} />
          </div>
        )}
        {profile && (
          <dl className="space-y-1 text-sm">
            <Row label="Risk profile" value={profile.risk_profile} />
            <Row label="Horizon" value={`${profile.investment_horizon_years} years`} />
            <Row label="Capital" value={`₹${profile.capital.toLocaleString("en-IN")}`} />
            <Row label="Monthly contribution" value={`₹${profile.monthly_contribution.toLocaleString("en-IN")}`} />
            <Row label="Objective" value={profile.objective.replace(/_/g, " ")} />
            <Row label="Liquidity need" value={profile.liquidity_requirement} />
          </dl>
        )}
        <Link href="/onboarding" className="mt-4 inline-block text-sm text-brand-700 underline">
          Update my profile
        </Link>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between capitalize">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

export default function SettingsPage() {
  return <SettingsInner />;
}
